import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useApi, useAppData, useControls } from '../api/context';
import type { Progress } from '../api/types';
import { Icon } from '../components/Icon';
import { ReadoutHeader } from '../components/ReadoutHeader';
import { JobPanel, LogTail, Meters, StepList, StopConfirm } from '../components/run/RunParts';
import { Section } from '../components/Section';
import { usd } from '../lib/format';
import { usePoll } from '../lib/polling';
import { isTerminal, pendingCode, runStatusView } from '../lib/runs';
import { MODE_LABEL } from '../lib/status';
import { useDocumentTitle } from '../lib/useDocumentTitle';
import { LocalOnlyPage } from './NotFoundPage';

const POLL_MS = 5000;
const RESUME_GRACE_MS = 20_000;
const AUTO_OPEN_SECONDS = 3;

export function RunPage() {
  const controls = useControls();
  const { session } = useAppData();
  if (session.mode !== 'local') return <LocalOnlyPage what="Run" />;
  return <Run controls={controls} />;
}

function Run({ controls }: { controls: boolean }) {
  const { run = '' } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const { items, refreshLibrary, refreshRuns } = useAppData();
  // A resume restarts the same run folder: bump the epoch to restart polling, and keep polling through the few
  // seconds before the resumed process has recorded itself (the folder still reads as finished until then).
  const [epoch, setEpoch] = useState(0);
  const resumedAt = useRef(0);
  const poll = usePoll(() => api.progress(run), POLL_MS, {
    key: `${run}#${epoch}`,
    until: (data) => isTerminal(data.status) && Date.now() - resumedAt.current > RESUME_GRACE_MS,
  });
  const progress: Progress | null = poll.data && poll.data.run === run ? poll.data : null;
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [autoOpen, setAutoOpen] = useState<number | null>(null);
  const previous = useRef<Progress['status'] | null>(null);
  const stopButton = useRef<HTMLButtonElement>(null);
  const openButton = useRef<HTMLAnchorElement>(null);

  const label = progress?.name ?? run;
  useDocumentTitle(label);

  // Watching a run finish: refresh the sidebar and offer to open the case.
  useEffect(() => {
    const status = progress?.status ?? null;
    if (status !== null && previous.current !== null && previous.current !== status && isTerminal(status)) {
      refreshLibrary();
      refreshRuns();
    }
    if (status === 'completed' && progress?.library_id && previous.current !== null && previous.current !== 'completed') {
      setAutoOpen(AUTO_OPEN_SECONDS);
    }
    previous.current = status;
  }, [progress?.status, progress?.library_id, refreshLibrary, refreshRuns]);

  useEffect(() => {
    if (autoOpen === null) return undefined;
    if (autoOpen <= 0) {
      if (progress?.library_id) navigate(`/case/${encodeURIComponent(progress.library_id)}`);
      return undefined;
    }
    const timer = setTimeout(() => setAutoOpen((value) => (value === null ? null : value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [autoOpen, navigate, progress?.library_id]);

  if (!progress) {
    if (poll.error instanceof ApiError && poll.error.status === 404) {
      return (
        <section>
          <h1>Run not found</h1>
          <p className="lede">{poll.error.message}</p>
          <Link to="/" className="btn btn--secondary">
            Back to the start
          </Link>
        </section>
      );
    }
    return (
      <section aria-busy={!poll.error}>
        <h1>{run}</h1>
        {poll.error ? (
          <div className="notice notice--attention" role="alert">
            <Icon name="attention" />
            <div className="notice__body">
              <p className="notice__title">Progress could not be read</p>
              <p>{poll.error.message} Trying again every few seconds.</p>
            </div>
          </div>
        ) : (
          <p role="status">Reading the run.</p>
        )}
      </section>
    );
  }

  const view = runStatusView(progress);
  const caseItem = progress.library_id ? items.find((item) => item.id === progress.library_id) : undefined;
  const code = caseItem?.fault_code ?? pendingCode(progress.mode);
  const terminal = isTerminal(progress.status);
  const step = progress.steps.find((entry) => entry.status === 'running')?.label ?? progress.step;

  async function stop() {
    setBusy(true);
    setActionError(null);
    try {
      await api.stopRun(run);
      setConfirming(false);
      refreshRuns();
      poll.refresh();
      stopButton.current?.focus();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'The run could not be stopped.');
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    setBusy(true);
    setActionError(null);
    try {
      const result = await api.resumeRun(run);
      refreshRuns();
      resumedAt.current = Date.now();
      if (result.run === run) setEpoch((value) => value + 1);
      else navigate(`/run/${encodeURIComponent(result.run)}`);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'The run could not be resumed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <ReadoutHeader
        code={code}
        tag={caseItem ? 'Fault code' : 'Fault code (assigned when the case is saved)'}
        fields={[
          { label: 'Status', value: view.word },
          { label: 'Step', value: step ?? 'none' },
          { label: 'Kind', value: MODE_LABEL[progress.mode] ?? progress.mode },
          { label: 'Spent', value: `${usd(progress.spent_usd)} of ${usd(progress.cap_usd)}` },
        ]}
        foot={run}
      />
      <h1>{progress.name}</h1>
      <p className="sr-only" role="status" aria-live="polite">
        {`${progress.name}: ${view.word.toLowerCase()}${step ? `, step ${step}` : ''}, ${usd(progress.spent_usd)} spent.`}
      </p>

      {terminal && progress.stop_text && progress.status !== 'completed' && (
        <div className="notice notice--attention" role="note">
          <Icon name="attention" />
          <div className="notice__body">
            <p className="notice__title">{progress.status === 'failed' ? 'The run failed' : 'The run stopped'}</p>
            <p>{progress.stop_text}</p>
            {progress.stop_reason === 'auth_expired' && (
              <p>
                <Link to="/setup">Open Setup</Link> to check your sign-in.
              </p>
            )}
            {progress.resumable && <p>Nothing is lost: Resume re-attaches to the Jobs already submitted and never pays twice.</p>}
          </div>
        </div>
      )}
      {progress.status === 'interrupted' && !progress.stop_text && (
        <div className="notice notice--attention" role="note">
          <Icon name="attention" />
          <div className="notice__body">
            <p className="notice__title">The run was interrupted</p>
            <p>Its process is no longer running. Resume continues from the last finished step.</p>
          </div>
        </div>
      )}
      {progress.status === 'stopping' && (
        <div className="notice notice--attention" role="status">
          <Icon name="stop" />
          <div className="notice__body">
            <p className="notice__title">Stopping</p>
            <p>The current Job is being cancelled. Faultline waits for the provider to confirm, then settles the cost.</p>
          </div>
        </div>
      )}

      {progress.status === 'completed' && (
        <div className="notice notice--neutral" role="status">
          <Icon name="check" />
          <div className="notice__body">
            <p className="notice__title">The run finished</p>
            {progress.library_id ? (
              <>
                <p>
                  The case is saved.
                  {autoOpen !== null && autoOpen > 0 && ` Opening it in ${autoOpen} ${autoOpen === 1 ? 'second' : 'seconds'}.`}
                </p>
                <div className="actions actions--tight">
                  <Link className="btn" to={`/case/${encodeURIComponent(progress.library_id)}`} ref={openButton}>
                    Open the case
                  </Link>
                  {autoOpen !== null && autoOpen > 0 && (
                    <button type="button" className="btn btn--secondary" onClick={() => setAutoOpen(null)}>
                      Stay here
                    </button>
                  )}
                </div>
              </>
            ) : (
              <p>No case was saved because nothing reproduced, or the run did not produce one. The log below says why.</p>
            )}
          </div>
        </div>
      )}

      {controls && (progress.stoppable || progress.resumable) && (
        <div className="run-actions">
          {progress.stoppable && !confirming && (
            <button type="button" className="btn btn--stop" ref={stopButton} onClick={() => setConfirming(true)}>
              <Icon name="stop" /> Stop
            </button>
          )}
          {progress.resumable && (
            <button type="button" className="btn" onClick={() => void resume()} aria-busy={busy}>
              <Icon name="replay" /> Resume
            </button>
          )}
        </div>
      )}
      {confirming && <StopConfirm onConfirm={() => void stop()} onCancel={() => setConfirming(false)} busy={busy} />}
      {actionError && (
        <div className="notice notice--attention" role="alert">
          <Icon name="attention" />
          <div className="notice__body">
            <p>{actionError}</p>
          </div>
        </div>
      )}
      {poll.error && (
        <p className="muted" role="status">
          The latest update could not be read ({poll.error.message}). Showing the last one received.
        </p>
      )}

      <Section title="Cloud Job">
        <JobPanel progress={progress} />
      </Section>
      <Section title="Spend and time">
        <Meters progress={progress} />
      </Section>
      <Section title="Steps">
        <StepList steps={progress.steps} />
      </Section>
      <Section title="Log">
        <LogTail lines={progress.log_tail} />
      </Section>
    </article>
  );
}
