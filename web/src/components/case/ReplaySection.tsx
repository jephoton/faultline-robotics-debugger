import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi, useControls } from '../../api/context';
import type { Detail } from '../../api/types';
import { buildReplayYaml, extractBackend, REPLAY_DEFAULTS, type ReplayForm } from '../../lib/specYaml';
import { useAsync } from '../../lib/useAsync';
import { Icon } from '../Icon';
import { StepReview } from '../new/StepReview';
import { Section } from '../Section';
import { ReplayHistory } from './CommonSections';

type Expect = '' | 'reproduces' | 'fixed';

function ReplayForm({ detail }: { detail: Detail }) {
  const api = useApi();
  const uid = useId();
  const [form, setForm] = useState<ReplayForm>(REPLAY_DEFAULTS);
  const [expect, setExpect] = useState<Expect>('');
  const [review, setReview] = useState(false);
  const template = useAsync(() => api.specTemplate('replay'), [api]);
  const yaml = buildReplayYaml(detail.name, form, template.data ? extractBackend(template.data) : null);

  const change = (patch: Partial<ReplayForm>) => {
    setForm((previous) => ({ ...previous, ...patch }));
    setReview(false);
  };
  const id = (name: string) => `${uid}-${name}`;

  return (
    <div className="panel">
      <h3>Replay this case</h3>
      <p>
        A replay runs the case's minimal scene and its passing reference five times each, and says whether the failure still
        reproduces. Use it as a regression test after you change the policy.
      </p>
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
            consequence="A replay creates one cloud Job on your Nebius account and spends real credit, up to the worst case above."
            launch={(plan) => api.startReplay(detail.id, { yaml, plan_hash: plan.plan_hash, ...(expect ? { expect } : {}) })}
          />
        </div>
      )}
    </div>
  );
}

export function ReplaySection({ detail }: { detail: Detail }) {
  const controls = useControls();
  return (
    <Section title="Replays">
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
