import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { ApiError } from '../api/client';
import type { Detail } from '../api/types';
import { AuditSection } from '../components/case/AuditSection';
import {
  CaseVideos,
  ExplanationSection,
  FilesSection,
  HistorySection,
  ReadingFold,
  ReportBody,
  ReportSection,
  ResearchSection,
  RunDetails,
} from '../components/case/CommonSections';
import { OcclusionSection } from '../components/case/OcclusionSection';
import { ReplaySection } from '../components/case/ReplaySection';
import { ParaphraseSection } from '../components/case/ParaphraseSection';
import { ScenarioSection } from '../components/case/ScenarioSection';
import { Icon } from '../components/Icon';
import { ReadoutHeader } from '../components/ReadoutHeader';
import { shortDate, suiteLabel } from '../lib/format';
import { KIND_LABEL, statusFor } from '../lib/status';
import { useAsync } from '../lib/useAsync';
import { useDocumentTitle } from '../lib/useDocumentTitle';

function CaseFacts({ detail }: { detail: Detail }) {
  return (
    <dl className="facts">
      <dt>Case id</dt>
      <dd className="mono">{detail.case_id ?? detail.id}</dd>
      {detail.run && (
        <>
          <dt>Run folder</dt>
          <dd className="mono">{detail.run}</dd>
        </>
      )}
      {detail.checkpoint && (
        <>
          <dt>Policy checkpoint</dt>
          <dd>
            <span className="mono">{detail.checkpoint.id}</span>
            <span className="muted">
              {' '}
              at <span className="mono">{detail.checkpoint.revision.slice(0, 10)}</span>
              {detail.checkpoint.pinned ? ' (pinned)' : ' (not pinned)'}
            </span>
          </dd>
        </>
      )}
    </dl>
  );
}

/** A case with a stored report: the report is the body, in the order the person reads it. */
function ReportFirstBody({ detail }: { detail: Detail }) {
  return (
    <>
      <CaseVideos detail={detail} />
      <ReportBody detail={detail} />
      <ReadingFold detail={detail} />
      <ResearchSection detail={detail} />
      {detail.kind === 'scenario' && <ReplaySection detail={detail} purpose />}
      <RunDetails detail={detail} />
    </>
  );
}

/** A case with no stored report (the September occlusion case): the structured view. */
function StructuredBody({ detail }: { detail: Detail }) {
  return (
    <>
      {detail.kind === 'scenario' && <ScenarioSection detail={detail} />}
      {detail.kind === 'audit' && <AuditSection detail={detail} />}
      {detail.kind === 'paraphrase' && <ParaphraseSection detail={detail} />}
      {detail.kind === 'occlusion' && <OcclusionSection detail={detail} />}

      <HistorySection detail={detail} />
      <ExplanationSection detail={detail} />
      <ResearchSection detail={detail} />
      {detail.kind === 'scenario' && <ReplaySection detail={detail} />}
      <ReportSection detail={detail} />
    </>
  );
}

export function CaseView({ detail }: { detail: Detail }) {
  const status = statusFor(detail.verdict, detail.attention);
  useDocumentTitle(`${detail.fault_code} ${detail.name}`);
  const attentionNotice = detail.attention || detail.verdict === 'stopped' || detail.verdict === 'failed';
  return (
    <article>
      <ReadoutHeader
        code={detail.fault_code}
        fields={[
          { label: 'Verdict', value: status.label, tone: status.tone, icon: status.icon },
          { label: 'Kind', value: KIND_LABEL[detail.kind] },
          { label: 'Suite and task', value: detail.suite ? `${suiteLabel(detail.suite)}, task ${detail.task_id ?? '?'}` : 'not recorded' },
          { label: 'Made', value: shortDate(detail.created) },
        ]}
        foot={detail.instruction ?? undefined}
      />
      <h1>{detail.name}</h1>
      <p className="lede">{detail.sentence ?? detail.verdict_text}</p>
      {detail.stop_text && (
        <div className={attentionNotice ? 'notice notice--attention' : 'notice notice--neutral'} role="note">
          <Icon name={attentionNotice ? 'attention' : 'info'} />
          <div className="notice__body">
            <p className="notice__title">{attentionNotice ? 'Stopped early' : 'Why it stopped'}</p>
            <p>{detail.stop_text}</p>
          </div>
        </div>
      )}
      <CaseFacts detail={detail} />

      {detail.report_markdown ? <ReportFirstBody detail={detail} /> : <StructuredBody detail={detail} />}
      <FilesSection detail={detail} />
    </article>
  );
}

export function CasePage() {
  const { id = '' } = useParams();
  const api = useApi();
  const result = useAsync(() => api.detail(id), [api, id]);
  const { error, loading } = result;
  // Drop the previous case while the next one loads.
  const data = result.data && result.data.id === id ? result.data : null;

  if (loading && !data) {
    return (
      <p role="status" aria-busy="true">
        Loading the case.
      </p>
    );
  }
  if (error || !data) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <section>
        <h1>{missing ? 'Case not found' : 'The case could not be loaded'}</h1>
        <p className="lede">{error?.message ?? 'Nothing was returned.'}</p>
        <Link to="/" className="btn btn--secondary">
          Back to the start
        </Link>
      </section>
    );
  }
  return <CaseView key={data.id} detail={data} />;
}
