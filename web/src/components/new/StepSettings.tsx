import { useId, useRef, useState, type ReactNode } from 'react';
import type { FieldError, ImportFile } from '../../api/types';
import { AUDIT_FAMILIES, SUITES, SUITE_LABEL, TASKS, taskInstruction } from '../../data/tasks';
import { errorsByField, sortFamilies, type DiagnosisChoice, type FieldKey, type FormState } from '../../lib/specYaml';
import { Icon } from '../Icon';

export type ValidationState =
  | { status: 'idle' | 'checking' }
  | { status: 'done'; ok: boolean; errors: FieldError[] };

interface Props {
  choice: DiagnosisChoice;
  form: FormState;
  onChange: (patch: Partial<FormState>) => void;
  yaml: string;
  yamlEdited: boolean;
  onYamlChange: (yaml: string) => void;
  onYamlReset: () => void;
  validation: ValidationState;
  templateReady: boolean;
}

function Field({
  id,
  label,
  hint,
  errors,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  errors?: string[];
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? (
        <span className="field__hint" id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
      {errors?.map((message) => (
        <span className="field__error" id={`${id}-error`} key={message}>
          <Icon name="alarm" /> {message}
        </span>
      ))}
    </div>
  );
}

function describedBy(id: string, hint: boolean, errors?: string[]): string | undefined {
  const ids = [hint ? `${id}-hint` : null, errors?.length ? `${id}-error` : null].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('The file could not be read.'));
    reader.readAsText(file);
  });
}

const MAX_IMPORT_BYTES = 1_500_000;

export function StepSettings({ choice, form, onChange, yaml, yamlEdited, onYamlChange, onYamlReset, validation, templateReady }: Props) {
  const uid = useId();
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const allErrors = validation.status === 'done' ? validation.errors : [];
  const { byField, other } = errorsByField(allErrors);
  const fieldErrors = (key: FieldKey): string[] | undefined => byField[key];
  const suite = (SUITES as readonly string[]).includes(form.suite) ? form.suite : 'libero_10';
  const taskNumber = Number(form.task);
  const instruction = taskInstruction(form.suite, taskNumber);
  const id = (name: string) => `${uid}-${name}`;

  async function pickFile(file: File | undefined) {
    setFileProblem(null);
    if (!file) {
      onChange({ importFile: null });
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setFileProblem('That file is larger than the server accepts (about 1.5 MB).');
      onChange({ importFile: null });
      return;
    }
    try {
      const content = await readFileText(file);
      JSON.parse(content);
      const importFile: ImportFile = { name: file.name, content };
      onChange({ importFile });
    } catch (error) {
      setFileProblem(error instanceof SyntaxError ? 'That file is not valid JSON.' : 'The file could not be read.');
      onChange({ importFile: null });
    }
  }

  const fileErrors = [...(fileProblem ? [fileProblem] : []), ...(fieldErrors('file') ?? [])];

  return (
    <div className="settings">
      {!templateReady && (
        <p role="status" className="muted">
          Loading the spec template.
        </p>
      )}

      <div className="form-grid">
        <Field id={id('name')} label="Name" hint="Used for the run folder and the case." errors={fieldErrors('name')}>
          <input
            id={id('name')}
            type="text"
            value={form.name}
            onChange={(event) => onChange({ name: event.target.value })}
            aria-invalid={fieldErrors('name') ? true : undefined}
            aria-describedby={describedBy(id('name'), true, fieldErrors('name'))}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>

        <Field id={id('suite')} label="Suite" errors={fieldErrors('suite')}>
          <select id={id('suite')} value={suite} onChange={(event) => onChange({ suite: event.target.value, task: '0' })}>
            {SUITES.map((value) => (
              <option key={value} value={value}>
                {SUITE_LABEL[value]}
              </option>
            ))}
          </select>
        </Field>

        <Field
          id={id('task')}
          label="Task"
          hint={instruction ? <>Instruction: &ldquo;{instruction}&rdquo;</> : 'The benchmark task number.'}
          errors={fieldErrors('task')}
        >
          <select
            id={id('task')}
            value={form.task}
            onChange={(event) => onChange({ task: event.target.value })}
            aria-describedby={describedBy(id('task'), true, fieldErrors('task'))}
          >
            {(TASKS[suite as keyof typeof TASKS] ?? []).map((text, index) => (
              <option key={index} value={String(index)}>
                {index}: {text}
              </option>
            ))}
          </select>
        </Field>

        {choice === 'start' && (
          <Field id={id('start')} label="Start" hint="The benchmark start, 0 to 49." errors={fieldErrors('start')}>
            <input
              id={id('start')}
              type="text"
              inputMode="numeric"
              value={form.start}
              onChange={(event) => onChange({ start: event.target.value })}
              aria-invalid={fieldErrors('start') ? true : undefined}
              aria-describedby={describedBy(id('start'), true, fieldErrors('start'))}
            />
          </Field>
        )}

        {choice === 'screen' && (
          <>
            <Field id={id('range')} label="Starts to search" hint="For example 10-49." errors={fieldErrors('range')}>
              <input
                id={id('range')}
                type="text"
                value={form.range}
                onChange={(event) => onChange({ range: event.target.value })}
                aria-invalid={fieldErrors('range') ? true : undefined}
                aria-describedby={describedBy(id('range'), true, fieldErrors('range'))}
              />
            </Field>
            <Field id={id('confirm')} label="Confirmation attempts" hint="Extra attempts (4 to 8) for a start that fails its first try. It counts as failing reliably at 4 failures; the default 4 gives the usual 4 of 5." errors={undefined}>
              <input
                id={id('confirm')}
                type="text"
                inputMode="numeric"
                value={form.confirm}
                onChange={(event) => onChange({ confirm: event.target.value })}
                aria-describedby={describedBy(id('confirm'), true)}
              />
            </Field>
          </>
        )}

        {choice === 'import' && (
          <Field
            id={id('file')}
            label="Start file"
            hint="A JSON start-state file for the suite and task above. Faultline checks that it fails 4 of 5 times first."
            errors={fileErrors}
          >
            <input
              id={id('file')}
              ref={fileInput}
              type="file"
              accept=".json,application/json"
              onChange={(event) => void pickFile(event.target.files?.[0])}
              aria-invalid={fileErrors.length ? true : undefined}
              aria-describedby={describedBy(id('file'), true, fileErrors)}
            />
            {form.importFile && (
              <span className="field__hint">
                <Icon name="file" /> {form.importFile.name} ({Math.max(1, Math.round(form.importFile.content.length / 1024))} KB)
              </span>
            )}
          </Field>
        )}

      </div>

      {choice === 'start' && (
        <fieldset className="probes">
          <legend>If the start passes untouched, also probe</legend>
          <label className="check">
            <input type="checkbox" checked={form.probes} onChange={(event) => onChange({ probes: event.target.checked })} />
            Probe with disturbances and rewordings
          </label>
          <span className="field__hint">
            Turn this off to only check the start and diagnose the layout if it fails. If the start passes, nothing more runs.
          </span>

          <fieldset disabled={!form.probes} aria-describedby={fieldErrors('families') ? id('families-error') : undefined}>
            <legend>Disturbance families</legend>
            <p className="muted">
              Each family is searched from severity 0 (no change) to 1 (the strongest) for the smallest severity that breaks the policy. More
              families cost more time.
            </p>
            {(['image', 'scene'] as const).map((group) => (
              <div key={group}>
                <p className="section-label">{group === 'image' ? 'Image, both cameras' : 'Scene, applied when the simulator resets'}</p>
                <div>
                  {AUDIT_FAMILIES.filter((family) => family.group === group).map((family) => (
                    <label key={family.key} className="check">
                      <input
                        type="checkbox"
                        checked={form.families.includes(family.key)}
                        onChange={(event) =>
                          onChange({
                            families: sortFamilies(
                              event.target.checked ? [...form.families, family.key] : form.families.filter((key) => key !== family.key),
                            ),
                          })
                        }
                      />
                      {family.label}
                    </label>
                  ))}
                </div>
              </div>
            ))}
            <p className="field__hint">
              These four are where the policy has failed before; each extra family adds about half an hour and can need another Job.
            </p>
            {fieldErrors('families')?.map((message) => (
              <span className="field__error" id={id('families-error')} key={message}>
                <Icon name="alarm" /> {message}
              </span>
            ))}
          </fieldset>

          <Field
            id={id('rewordings')}
            label="Rewordings to ask for"
            hint="0 skips this probe; 1 to 12 asks Nemotron for that many rewordings, and the smallest word change that breaks the policy is kept."
            errors={fieldErrors('rewordings')}
          >
            <input
              id={id('rewordings')}
              type="text"
              inputMode="numeric"
              value={form.rewordings}
              disabled={!form.probes}
              onChange={(event) => onChange({ rewordings: event.target.value })}
              aria-invalid={fieldErrors('rewordings') ? true : undefined}
              aria-describedby={describedBy(id('rewordings'), true, fieldErrors('rewordings'))}
            />
          </Field>
        </fieldset>
      )}

      <div className="form-grid">
        <Field id={id('spend')} label="Spend cap (US$)" hint="The most this run may cost. It stops before a Job could go over." errors={fieldErrors('spend')}>
          <input
            id={id('spend')}
            type="text"
            inputMode="decimal"
            value={form.spend}
            onChange={(event) => onChange({ spend: event.target.value })}
            aria-invalid={fieldErrors('spend') ? true : undefined}
            aria-describedby={describedBy(id('spend'), true, fieldErrors('spend'))}
          />
        </Field>
        <Field id={id('hours')} label="Hour limit" hint="The most wall-clock time before the run stops." errors={fieldErrors('hours')}>
          <input
            id={id('hours')}
            type="text"
            inputMode="decimal"
            value={form.hours}
            onChange={(event) => onChange({ hours: event.target.value })}
            aria-invalid={fieldErrors('hours') ? true : undefined}
            aria-describedby={describedBy(id('hours'), true, fieldErrors('hours'))}
          />
        </Field>
      </div>

      <div className="field">
        <label className="check">
          <input type="checkbox" checked={form.nemotron} onChange={(event) => onChange({ nemotron: event.target.checked })} />
          Ask Nemotron for a hypothesis and an explanation if the layout diagnosis runs
        </label>
        <span className="field__hint">
          Needs a Token Factory key in your .env file. Nemotron only proposes an order and a reading; the reruns decide the result.
          {choice === 'start' && ' Rewordings are written by Nemotron too, whatever you choose here.'}
        </span>
        {fieldErrors('nemotron')?.map((message) => (
          <span className="field__error" key={message}>
            <Icon name="alarm" /> {message}
          </span>
        ))}
      </div>

      <div className="field">
        <label className="check">
          <input type="checkbox" checked={form.research} onChange={(event) => onChange({ research: event.target.checked })} />
          Find related research
        </label>
        <span className="field__hint">
          Searches public sources with Tavily and summarises them with Nemotron 3 Nano. Context, not evidence. Needs a Tavily key in .env.
        </span>
        {fieldErrors('research')?.map((message) => (
          <span className="field__error" key={message}>
            <Icon name="alarm" /> {message}
          </span>
        ))}
      </div>

      <details className="yaml-panel" open={yamlEdited || other.length > 0 ? true : undefined}>
        <summary>Edit YAML</summary>
        <p className="muted">
          This is the spec that will run, the same file you could pass to <code>faultline diagnose</code>. Any spec key works here. Once you
          edit it, the YAML is the source of truth.
        </p>
        {yamlEdited && (
          <div className="notice notice--attention" role="note">
            <Icon name="attention" />
            <div className="notice__body">
              <p className="notice__title">Your YAML edits take priority</p>
              <p>Changing the fields above no longer changes the spec.</p>
              <button type="button" className="btn btn--secondary btn--small" onClick={onYamlReset}>
                Discard YAML edits and use the fields
              </button>
            </div>
          </div>
        )}
        <label htmlFor={id('yaml')} className="sr-only">
          Spec in YAML
        </label>
        <textarea
          id={id('yaml')}
          value={yaml}
          onChange={(event) => onYamlChange(event.target.value)}
          rows={Math.min(30, Math.max(12, yaml.split('\n').length + 1))}
          spellCheck={false}
          aria-describedby={other.length ? id('yaml-errors') : undefined}
        />
        {other.length > 0 && (
          <ul className="yaml-errors" id={id('yaml-errors')}>
            {other.map((error) => (
              <li key={`${error.path}-${error.message}`} className="field__error">
                <Icon name="alarm" />
                <span>
                  <code>{error.path || 'spec'}</code> {error.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </details>

      <p className="validation" role="status" aria-live="polite">
        {validation.status === 'checking' && 'Checking the spec.'}
        {validation.status === 'done' && validation.ok && (
          <>
            <Icon name="check" /> The spec has no problems.
          </>
        )}
        {validation.status === 'done' && !validation.ok && (
          <>
            <Icon name="alarm" /> {allErrors.length} {allErrors.length === 1 ? 'problem' : 'problems'} to fix before the review.
          </>
        )}
      </p>
    </div>
  );
}
