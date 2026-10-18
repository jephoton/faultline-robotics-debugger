import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi, useControls } from '../../api/context';
import type { Detail } from '../../api/types';
import { buildReplayYaml, extractBackend, REPLAY_DEFAULTS, suggestedReplayLimits, type ReplayForm } from '../../lib/specYaml';
import { useAsync } from '../../lib/useAsync';
import { Icon } from '../Icon';
import { StepReview } from '../new/StepReview';
import { Section } from '../Section';
import { ReplayHistory } from './CommonSections';

type Expect = '' | 'reproduces' | 'fixed';

/** What a replay runs, per kind of case (the Jobs are the same replay Job; the inputs differ). */
const REPLAY_INTRO: Partial<Record<Detail['kind'], string>> = {
  scenario:
    "A replay runs the case's minimal scene and its passing reference five times each, and says whether the failure still reproduces. Use it as a regression test after you change the policy.",
  audit:
    'A replay reruns each disturbance that broke the policy at its threshold on the start, five times each, plus the unchanged start five times as its control, and says whether each still fails. Use it as a regression test after you change the policy.',
  paraphrase:
    'A replay reruns the failing wording on the start five times, with the original wording as its control, and says whether it still fails. Use it as a regression test after you change the policy.',
};

function ReplayForm({ detail }: { detail: Detail }) {
  const api = useApi();
  const uid = useId();
  const [form, setForm] = useState<ReplayForm>(REPLAY_DEFAULTS);
  const [expect, setExpect] = useState<Expect>('');
  const [review, setReview] = useState(false);
  const template = useAsync(() => api.specTemplate('replay'), [api]);
  const backend = template.data ? extractBackend(template.data) : null;
  const yaml = buildReplayYaml(detail.name, form, backend);
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
  const id = (name: string) => `${uid}-${name}`;

  return (
    <div className="panel">
      <h3>Replay this case</h3>
      <p>{REPLAY_INTRO[detail.kind] ?? REPLAY_INTRO.scenario}</p>
      <div className="form-grid">
        <div className="field">
          <label htmlFor={id('expect')}>What do you expect?</label>
          <select
            id={id('expect')}
            value={expect}
            onChange={(event) => {
              setExpect(event.target.value as Expect);
              setReview(false);
            }}
          >
            <option value="">No expectation</option>
            <option value="reproduces">Still reproduces</option>
            <option value="fixed">Fixed (after a change meant to cure it)</option>
          </select>
          <span className="field__hint">With an expectation, the command's exit code tells a script whether you got it.</span>
        </div>
        <div className="field">
          <label htmlFor={id('spend')}>Spend cap (US$)</label>
          <input id={id('spend')} type="text" inputMode="decimal" value={form.spend} onChange={(event) => change({ spend: event.target.value })} />
        </div>
        <div className="field">
          <label htmlFor={id('hours')}>Hour limit</label>
          <input id={id('hours')} type="text" inputMode="decimal" value={form.hours} onChange={(event) => change({ hours: event.target.value })} />
        </div>
      </div>
      <fieldset>
        <legend>A different checkpoint (optional)</legend>
        <p className="muted">
          Fill in both to replay against another policy, for example a retrained one. Leave them empty to use the checkpoint the case
          was made with. Your Hugging Face account needs access to it.
        </p>
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
          </div>
        </div>
      </fieldset>
      {template.error && <p className="muted">The replay template could not be loaded ({template.error.message}).</p>}
      {!review ? (
        <div className="actions actions--tight">
          <button type="button" className="btn" onClick={() => setReview(true)}>
            <Icon name="replay" /> Dry run the replay
          </button>
        </div>
      ) : (
        <div className="replay-review">
          <StepReview
            key={yaml}
            yaml={yaml}
            importFile={null}
            startLabel="Start replay"
            headingLevel={4}
            caseId={detail.id}
            consequence="A replay creates one cloud Job on your Nebius account and spends real credit, up to the worst case above."
            launch={(plan) => api.startReplay(detail.id, { yaml, plan_hash: plan.plan_hash, ...(expect ? { expect } : {}) })}
          />
        </div>
      )}
    </div>
  );
}

/** What a replay is for, in one line (shown above the replay history in the report-first layout). */
export const REPLAY_PURPOSE =
  'Replay re-runs the minimal scene and its reference to check whether the failure still reproduces, for example after you change the policy.';

const REPLAY_PURPOSE_BY_KIND: Partial<Record<Detail['kind'], string>> = {
  scenario: REPLAY_PURPOSE,
  audit:
    'Replay reruns this disturbance at its threshold on the start, with its control, to check whether it still breaks the policy, for example after you change the policy.',
  paraphrase:
    'Replay reruns this wording on the start, with the original instruction as its control, to check whether it still breaks the policy, for example after you change the policy.',
};

/**
 * Scenario cases always have the section (it says when the inputs were not saved). Audit and wording cases have
 * it when a diagnosis run kept their replay inputs, or when they were already replayed.
 */
export function showsReplay(detail: Detail): boolean {
  if (detail.kind === 'scenario') return true;
  if (detail.kind === 'audit' || detail.kind === 'paraphrase') return detail.replayable || detail.replays.length > 0;
  return false;
}

export function ReplaySection({ detail, purpose = false }: { detail: Detail; purpose?: boolean }) {
  const controls = useControls();
  return (
    <Section title="Replays">
      {purpose && <p className="replay__purpose">{REPLAY_PURPOSE_BY_KIND[detail.kind] ?? REPLAY_PURPOSE}</p>}
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
