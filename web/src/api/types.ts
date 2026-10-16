// Types for the Faultline control-panel API, contract version 1.
// Source of truth: docs/superpowers/plans/2026-10-17-control-panel-ui.md ("API contract").

export const API_VERSION = 1;

export interface Session {
  api_version: number;
  mode: 'local' | 'static';
  controls: boolean;
  token: string | null;
  version: string;
}

export type Kind = 'scenario' | 'audit' | 'paraphrase' | 'occlusion';
export type Verdict = 'reproduces' | 'no_failure' | 'stopped' | 'failed' | 'incomplete';

export interface LibraryItem {
  id: string;
  fault_code: string;
  kind: Kind;
  name: string;
  verdict: Verdict;
  verdict_text: string;
  attention: boolean;
  suite: string | null;
  task_id: number | null;
  instruction: string | null;
  created: string | null;
  case_id: string | null;
  run: string | null;
}

export interface Library {
  items: LibraryItem[];
  warnings: string[];
}

export interface VideoRef {
  role: string;
  label: string;
  url: string | null;
  outcome: string | null;
}

export interface MinimalCause {
  entity: string;
  part: 'position' | 'rotation' | 'joints';
  fraction: number;
  magnitude: string;
}

export interface HypothesisEntity {
  entity: string;
  label: string;
  necessary: boolean | null;
  sufficient: boolean | null;
}

export interface Rerun {
  index: number;
  phase: string;
  role: string;
  selection: Record<string, Record<string, number>> | null;
  outcomes: string[];
  decision: string;
}

export interface ScenarioDetail {
  failing_start: number | null;
  imported: { file_sha256: string; state_sha256: string } | null;
  reference_start: number | null;
  entity_minimal: boolean | null;
  reduced: boolean | null;
  minimal_cause: MinimalCause[];
  differences_count: number;
  hypothesis: {
    ranked: string[];
    measured_verdict: string | null;
    verdict_text: string | null;
    entities: HypothesisEntity[];
  } | null;
  reruns: Rerun[];
}

export interface AuditLevel {
  severity: number;
  failures: number;
  attempts: number;
}

export interface AuditFamily {
  family: string;
  label: string;
  threshold_severity: number | null;
  stop_reason: string;
  levels: AuditLevel[];
}

export interface AuditDetail {
  start_index: number | null;
  nominal: { failures: number; attempts: number } | null;
  families: AuditFamily[];
}

export interface ParaphraseRow {
  text: string;
  outcomes: string[];
  failures: number;
  meaning: string | null;
}

export interface ParaphraseDetail {
  original: string | null;
  control: string[];
  paraphrases: ParaphraseRow[];
  minimal_edit: { text: string; edits: string[] } | null;
}

export interface OcclusionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface OcclusionDetail {
  perturbation: Record<string, unknown>;
  lineage: { rectangle: OcclusionRect; edge: string; delta: number }[];
  episodes: { episode_id: string; stage: string; role: string; outcome: string; url: string | null }[];
}

export interface TextWithEvidence {
  text: string;
  evidence_ids: string[];
}

export interface Explanation {
  status: string;
  model: string | null;
  disclaimer: string | null;
  hypotheses: TextWithEvidence[];
  observations: TextWithEvidence[];
  limitations: string[];
}

export interface HistoryStep {
  key: string;
  label: string;
  status: string;
  state: string | null;
  partial: boolean;
  cost_usd: number | null;
}

export interface History {
  steps: HistoryStep[];
  jobs: number;
  spent_usd: number | null;
  cap_usd: number | null;
  hourly_usd: number | null;
  elapsed_seconds: number | null;
  max_hours: number | null;
}

export interface ReplayRow {
  run: string | null;
  verdict: string;
  verdict_text: string;
  created: string | null;
  cost_usd: number | null;
}

export interface Detail extends LibraryItem {
  sentence: string | null;
  stop_reason: string | null;
  stop_text: string | null;
  checkpoint: { id: string; revision: string; pinned: boolean } | null;
  videos: VideoRef[];
  scenario?: ScenarioDetail;
  audit?: AuditDetail;
  paraphrase?: ParaphraseDetail;
  occlusion?: OcclusionDetail;
  explanation: Explanation | null;
  research: { related: string | null; sources: { title: string; url: string }[] } | null;
  history: History | null;
  replays: ReplayRow[];
  report_markdown: string | null;
  files: { name: string; url: string }[];
  replayable: boolean;
}

export interface RunSummary {
  run: string;
  name: string;
  mode: string;
  status: 'running' | 'stopping';
  step: string | null;
  spent_usd: number | null;
  cap_usd: number | null;
  attention: boolean;
}

export type JobPhase = 'submitting' | 'waiting_for_gpu' | 'running' | 'downloading' | 'settled';

export interface ProgressStep {
  key: string;
  label: string;
  status: string;
  state: string | null;
  attempts: number;
  capacity_waits: number;
}

export interface Progress extends Omit<RunSummary, 'status' | 'spent_usd' | 'cap_usd'> {
  status: 'running' | 'stopping' | 'completed' | 'stopped' | 'failed' | 'interrupted';
  stop_reason: string | null;
  stop_text: string | null;
  steps: ProgressStep[];
  job: { name: string; phase: JobPhase | null } | null;
  spent_usd: number;
  reserved_usd: number;
  cap_usd: number;
  elapsed_seconds: number;
  max_hours: number;
  log_tail: string[];
  library_id: string | null;
  resumable: boolean;
  stoppable: boolean;
}

export interface EnvironmentCheck {
  key: string;
  ok: boolean;
  detail: string;
  fix?: string;
}

export interface Environment {
  checks: EnvironmentCheck[];
}

/** One episode of the "All evidence" catalog (GET /api/evidence). */
export interface EvidenceEpisode {
  episode_id: string;
  run_name: string;
  benchmark: string;
  created_at: string;
  instruction: string;
  outcome: string;
  steps: number;
  elapsed_seconds: number;
  task_id: number;
  episode_index: number;
  failure_detail: string | null;
  /** Path under /media/, or null when no video was recorded. */
  video_path: string | null;
}

export interface Evidence {
  episodes: EvidenceEpisode[];
  warnings: string[];
}

export type SpecMode =
  | 'scenario-start'
  | 'scenario-screen'
  | 'scenario-import'
  | 'audit'
  | 'paraphrase'
  | 'replay';

export interface FieldError {
  path: string;
  message: string;
}

export interface ValidateResult {
  ok: boolean;
  errors: FieldError[];
  summary: Record<string, unknown>;
}

export interface ImportFile {
  name: string;
  content: string;
}

export interface DryRunJob {
  name: string;
  deadline_seconds: number;
  worst_case_usd: number;
}

export interface DryRun {
  plan_hash: string;
  jobs: DryRunJob[];
  worst_case_total_usd: number;
  cap_usd: number;
  max_hours: number;
  lines: string[];
}
