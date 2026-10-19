import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi, useControls } from '../../api/context';
import type { Detail } from '../../api/types';
import { usd } from '../../lib/format';
import { buildReplayYaml, extractBackend, REPLAY_DEFAULTS, suggestedReplayLimits, type ReplayForm } from '../../lib/specYaml';
import { useAsync } from '../../lib/useAsync';
import { Icon } from '../Icon';
import { StepReview } from '../new/StepReview';
import { Section } from '../Section';
import { checkpointText, ReplayHistory } from './CommonSections';

/** What the test checks, per kind of case (the Jobs are the same replay Job; the inputs differ). */
const REGRESSION_PURPOSE: Partial<Record<Detail['kind'], string>> = {
  scenario:
    "Reruns this case's minimal scene and its passing reference, five attempts each, to check whether the failure still happens. Run it after you change the policy.",
  audit:
    'Reruns each disturbance that broke the policy, at its threshold on the start, five attempts each, with the unchanged start as its control, to check whether each still fails. Run it after you change the policy.',
  paraphrase:
    'Reruns the failing wording on the start, five attempts, with the original wording as its control, to check whether it still fails. Run it after you change the policy.',
};

type Policy = 'original' | 'new';

function ReplayForm({ detail }: { detail: Detail }) {
  const api = useApi();
  const uid = useId();
  const [form, setForm] = useState<ReplayForm>(REPLAY_DEFAULTS);
  const [policy, setPolicy] = useState<Policy>('original');
  const [review, setReview] = useState(false);
  const template = useAsync(() => api.specTemplate('replay'), [api]);
  const backend = template.data ? extractBackend(template.data) : null;
  // The original policy is the case's own checkpoint, which the backend uses when the spec names none.
  const specForm: ReplayForm = policy === 'original' ? { ...form, checkpointId: '', checkpointRevision: '' } : form;
  const yaml = buildReplayYaml(detail.name, specForm, backend);
  const needsCheckpoint = policy === 'new' && (!form.checkpointId.trim() || !form.checkpointRevision.trim());
  // The Jobs of a replay depend on the case (a stress test runs one per probe group), so the default cap and
  // hour limit come from a plan made for this case, until the person types their own.
  const planYaml = template.data ? buildReplayYaml(detail.name, REPLAY_DEFAULTS, backend) : null;
  const suggestion = useAsync(() => (planYaml ? api.dryRun(planYaml, undefined, detail.id) : Promise.resolve(null)), [api, detail.id, planYaml]);
  const typed = useRef({ spend: false, hours: false });
  useEffect(() => {
    if (!suggestion.data) return;
    const limits = suggestedReplayLimits(suggestion.data);
    setForm((previous) => ({
      ...previous,
      spend: typed.current.spend ? previous.spend : limits.spend,
      hours: typed.current.hours ? previous.hours : limits.hours,
    }));
  }, [suggestion.data]);

  const change = (patch: Partial<ReplayForm>) => {
    if (patch.spend !== undefined) typed.current.spend = true;
    if (patch.hours !== undefined) typed.current.hours = true;
    setForm((previous) => ({ ...previous, ...patch }));
    setReview(false);
  };
  const choose = (next: Policy) => {
    setPolicy(next);
    setReview(false);
  };
  const id = (name: string) => `${uid}-${name}`;
  const original = detail.checkpoint ? checkpointText(detail.checkpoint) : null;

  return (
    <div className="panel">
      <h3>Test a policy</h3>
      <fieldset className="choices choices--policy">
        <legend>Which policy do you want to test?</legend>
        <div className="choices__grid">
          <label className={policy === 'original' ? 'choice choice--selected' : 'choice'}>
            <input type="radio" name={id('policy')} checked={policy === 'original'} onChange={() => choose('original')} />
            <span className="choice__title">The original policy</span>
            <span className="choice__text">
              {original ? <span className="mono">{original}</span> : 'The checkpoint this case was made with.'}
              <br />
              Confirms the failure still repeats.
            </span>
          </label>
          <label className={policy === 'new' ? 'choice choice--selected' : 'choice'}>
            <input type="radio" name={id('policy')} checked={policy === 'new'} onChange={() => choose('new')} />
            <span className="choice__title">A new checkpoint</span>
            <span className="choice__text">Tests another policy, for example a retrained one. Your Hugging Face account needs access to it.</span>
          </label>
        </div>
        {policy === 'new' && (
          <div className="form-grid">
            <div className="field">
              <label htmlFor={id('ckpt')}>Checkpoint id</label>
              <input
                id={id('ckpt')}
                type="text"
                value={form.checkpointId}
                onChange={(event) => change({ checkpointId: event.target.value })}
                placeholder="your-org/your-checkpoint"
                spellCheck={false}
              />
            </div>
            <div className="field">
              <label htmlFor={id('rev')}>Revision</label>
              <input
                id={id('rev')}
                type="text"
                value={form.checkpointRevision}
                onChange={(event) => change({ checkpointRevision: event.target.value })}
                placeholder="commit sha"
                spellCheck={false}
              />
              <span className="field__hint">Both are needed, so the result names exactly which policy ran.</span>
            </div>
          </div>
        )}
      </fieldset>
      <p className="replay__cost">
        {suggestion.data ? (
          <>
            Costs up to <strong>{usd(suggestion.data.worst_case_total_usd)}</strong> on your Nebius account if you run it.
          </>
        ) : (
          'The worst-case cost appears here once the test is planned.'
        )}
      </p>
      <details className="reruns">
        <summary>Limits</summary>
        <div className="form-grid">
          <div className="field">
            <label htmlFor={id('spend')}>Spend cap (US$)</label>
            <input id={id('spend')} type="text" inputMode="decimal" value={form.spend} onChange={(event) => change({ spend: event.target.value })} />
          </div>
          <div className="field">
            <label htmlFor={id('hours')}>Hour limit</label>
            <input id={id('hours')} type="text" inputMode="decimal" value={form.hours} onChange={(event) => change({ hours: event.target.value })} />
          </div>
        </div>
      </details>
      {template.error && <p className="muted">The replay template could not be loaded ({template.error.message}).</p>}
      {!review ? (
        <div className="actions actions--tight">
          <button type="button" className="btn" disabled={needsCheckpoint} onClick={() => setReview(true)}>
            <Icon name="replay" /> Estimate cost
          </button>
          {needsCheckpoint && <span className="muted">Fill in the checkpoint id and revision first.</span>}
        </div>
      ) : (
        <div className="replay-review">
          <StepReview
            key={yaml}
            yaml={yaml}
            importFile={null}
            startLabel="Run the test"
            headingLevel={4}
            caseId={detail.id}
            consequence="This test creates one cloud Job on your Nebius account and spends real credit, up to the worst case above."
            launch={(plan) => api.startReplay(detail.id, { yaml, plan_hash: plan.plan_hash })}
          />
        </div>
      )}
      <p className="muted replay__script">
        In a script: <code>faultline replay &lt;case folder&gt; --spec replay.yaml --expect fixed</code> exits 0 when the verdict is the one you
        expect (<code>--expect reproduces</code> for the original policy). A new checkpoint goes under <code>policy.checkpoint</code> in the spec;
        the command has no checkpoint flag.
      </p>
    </div>
  );
}

/**
 * Scenario cases always have the section (it says when the inputs were not saved). Audit and wording cases have
 * it when a diagnosis run kept their replay inputs, or when they were already replayed.
 */
export function showsReplay(detail: Detail): boolean {
  if (detail.kind === 'scenario') return true;
  if (detail.kind === 'audit' || detail.kind === 'paraphrase') return detail.replayable || detail.replays.length > 0;
  return false;
}

export function ReplaySection({ detail }: { detail: Detail }) {
  const controls = useControls();
  return (
    <Section title="Regression test">
      <p className="replay__purpose">{REGRESSION_PURPOSE[detail.kind] ?? REGRESSION_PURPOSE.scenario}</p>
      <ReplayHistory detail={detail} slot={(run) => <ReplayRunLink run={run} />} />
      {controls && detail.replayable && <ReplayForm detail={detail} />}
      {controls && !detail.replayable && (
        <p className="muted">This case cannot be replayed: its replay inputs were not saved.</p>
      )}
    </Section>
  );
}

/** Link from a replay row to its run page, when the run folder is known (local mode). */
export function ReplayRunLink({ run }: { run: string | null }) {
  const controls = useControls();
  if (!run || !controls) return null;
  return (
    <Link to={`/run/${encodeURIComponent(run)}`} className="replay__link">
      Open the run
    </Link>
  );
}
