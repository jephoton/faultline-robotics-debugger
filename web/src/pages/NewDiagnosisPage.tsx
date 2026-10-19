import { useEffect, useRef, useState } from 'react';
import { useApi, useControls } from '../api/context';
import { Icon } from '../components/Icon';
import { StepChoose } from '../components/new/StepChoose';
import { StepReview } from '../components/new/StepReview';
import { StepSettings, type ValidationState } from '../components/new/StepSettings';
import { applyPatch, buildYaml, defaultsFor, extractBackend, usesNemotron, type DiagnosisChoice, type FormState } from '../lib/specYaml';
import { useAsync } from '../lib/useAsync';
import { useDocumentTitle } from '../lib/useDocumentTitle';
import { LocalOnlyPage } from './NotFoundPage';

const STEPS = ['What to check', 'Settings', 'Review'] as const;
const DEBOUNCE_MS = 400;

export function NewDiagnosisPage() {
  const controls = useControls();
  if (!controls) return <LocalOnlyPage what="New diagnosis" />;
  return <NewDiagnosis />;
}

function NewDiagnosis() {
  useDocumentTitle('New diagnosis');
  const api = useApi();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [choice, setChoice] = useState<DiagnosisChoice>('start');
  const [form, setForm] = useState<FormState>(() => defaultsFor('start'));
  const [override, setOverride] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationState>({ status: 'idle' });
  const [blocked, setBlocked] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);

  const template = useAsync(() => api.specTemplate('diagnose'), [api]);
  // Related research needs a Tavily key: it starts ticked only when the key is there (or not known to be missing).
  const environment = useAsync(() => api.environment(), [api]);
  const researchDefault = environment.data?.checks.find((entry) => entry.key === 'tavily_key')?.ok !== false;
  const researchTouched = useRef(false);
  // Whether the person has typed their own Name; until then it follows Suite, Task and Start.
  const nameTyped = useRef(false);
  useEffect(() => {
    if (!researchTouched.current) setForm((previous) => ({ ...previous, research: researchDefault }));
  }, [researchDefault]);
  const backend = template.data ? extractBackend(template.data) : null;
  const generated = buildYaml(choice, form, backend);
  const yaml = override ?? generated;

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    heading.current?.focus();
  }, [step]);

  // Check the spec as it changes (debounced) while the settings are on screen.
  useEffect(() => {
    if (step !== 2 || template.loading) return undefined;
    let cancelled = false;
    setValidation({ status: 'checking' });
    const timer = setTimeout(() => {
      api
        .validateSpec(yaml)
        .then((result) => {
          if (!cancelled) setValidation({ status: 'done', ok: result.ok, errors: result.errors });
        })
        .catch((error: Error) => {
          if (!cancelled) setValidation({ status: 'done', ok: false, errors: [{ path: '', message: error.message }] });
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [api, yaml, step, template.loading]);

  function choose(next: DiagnosisChoice) {
    setChoice(next);
    setForm(defaultsFor(next, researchDefault));
    researchTouched.current = false;
    nameTyped.current = false;
    setOverride(null);
    setValidation({ status: 'idle' });
    setBlocked(null);
  }

  async function toReview() {
    setBlocked(null);
    if (choice === 'import' && !form.importFile && override === null) {
      setValidation({ status: 'done', ok: false, errors: [{ path: 'diagnose.import', message: 'Choose the start file to upload.' }] });
      setBlocked('Choose your start file first.');
      return;
    }
    try {
      const result = await api.validateSpec(yaml);
      setValidation({ status: 'done', ok: result.ok, errors: result.errors });
      if (!result.ok) {
        setBlocked(`The spec has ${result.errors.length} ${result.errors.length === 1 ? 'problem' : 'problems'}. Fix what is marked below, then review.`);
        return;
      }
      setStep(3);
    } catch (error) {
      setBlocked(error instanceof Error ? error.message : 'The spec could not be checked.');
    }
  }

  return (
    <section>
      <h1 ref={heading} tabIndex={-1}>
        New diagnosis
      </h1>
      <ol className="steps" aria-label="Steps">
        {STEPS.map((label, index) => {
          const number = index + 1;
          const state = number === step ? 'current' : number < step ? 'done' : 'todo';
          return (
            <li key={label} className={`steps__item steps__item--${state}`} aria-current={number === step ? 'step' : undefined}>
              <span className="steps__num">{state === 'done' ? <Icon name="tick" /> : number}</span>
              <span>{label}</span>
            </li>
          );
        })}
      </ol>

      {step === 1 && (
        <>
          <StepChoose choice={choice} onChoose={choose} />
          <p className="muted">Nothing is created or charged until you confirm on the review step.</p>
          <div className="actions">
            <button type="button" className="btn" onClick={() => setStep(2)}>
              Next: settings
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <StepSettings
            choice={choice}
            form={form}
            onChange={(patch) => {
              if (patch.research !== undefined) researchTouched.current = true;
              if (patch.name !== undefined) nameTyped.current = patch.name.trim() !== '';
              const typed = nameTyped.current;
              setForm((previous) => applyPatch(previous, patch, choice, typed));
            }}
            yaml={yaml}
            yamlEdited={override !== null}
            onYamlChange={(text) => setOverride(text)}
            onYamlReset={() => setOverride(null)}
            validation={validation}
            templateReady={!template.loading}
          />
          {template.error && (
            <p className="muted">The spec template could not be loaded ({template.error.message}); add the backend block in the YAML.</p>
          )}
          {blocked && (
            <div className="notice notice--attention" role="alert">
              <Icon name="attention" />
              <div className="notice__body">
                <p>{blocked}</p>
              </div>
            </div>
          )}
          <div className="actions">
            <button type="button" className="btn btn--secondary" onClick={() => setStep(1)}>
              Back
            </button>
            <button type="button" className="btn" onClick={() => void toReview()}>
              Review
            </button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <StepReview
            yaml={yaml}
            importFile={form.importFile}
            launch={(plan) =>
              api.startRun({
                yaml,
                plan_hash: plan.plan_hash,
                ...(form.importFile ? { import_file: form.importFile } : {}),
                ...(!usesNemotron(yaml) ? { no_llm: true } : {}),
              })
            }
          />
          <div className="actions">
            <button type="button" className="btn btn--secondary" onClick={() => setStep(2)}>
              Back to settings
            </button>
          </div>
        </>
      )}
    </section>
  );
}
