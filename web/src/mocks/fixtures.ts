// Fixtures built from the API contract types (docs/superpowers/plans/2026-10-17-control-panel-ui.md).
// Content is modelled on the committed demo case but every id here is obviously fake: the repository is public.
import type {
  Detail,
  Environment,
  Evidence,
  EvidenceEpisode,
  Library,
  LibraryItem,
  Progress,
  RunSummary,
  Session,
} from '../api/types';
import { auditReport, importedReport, paraphraseReport, pipelineAuditReport, pipelineWordingReport, soupReport } from './reports';

const hex = (prefix: string): string => (prefix + '0123456789abcdef'.repeat(4)).slice(0, 64);

export const IDS = {
  soup: `d-${hex('afb5')}`,
  imported: `d-${hex('7e31')}`,
  audit: `d-${hex('1c20')}`,
  wording: `d-${hex('4d9a')}`,
  // One diagnosis run that passed untouched and was probed: an audit case, then a wording case.
  pipeAudit: `d-${hex('5a10')}`,
  pipeWording: `d-${hex('6b21')}`,
  quiet: 'r-para-quiet-20261016-141500',
  nominal: `d-${hex('9b07')}`,
  occlusion: `m-${hex('0f42')}`,
};

export const RUN_IDS = {
  waiting: 'para-demo-20261017-093000',
  running: 'audit-demo-20261017-101500',
  stopping: 'soup-demo-20261017-110000',
  completed: 'para-done-20261017-084500',
  authExpired: 'soup-expired-20261016-193000',
  // Diagnosis runs, one per route the untouched check can choose.
  probing: 'diag-probing-20261018-100000',
  layoutRoute: 'diag-layout-20261018-110000',
  flaky: 'diag-flaky-20261018-120000',
  passes: 'diag-passes-20261018-130000',
};

export const PLACEHOLDER_VIDEO = '/media/placeholder.webm';

export const sessionLocal: Session = { api_version: 1, mode: 'local', controls: true, token: 'mock-session-token', version: '0.0.0-mock' };
export const sessionStatic: Session = { api_version: 1, mode: 'static', controls: false, token: null, version: '0.0.0-mock' };

const SOUP_INSTRUCTION = 'put both the alphabet soup and the tomato sauce in the basket';
const OBJECT_INSTRUCTION = 'pick up the alphabet soup and place it in the basket';

const items: LibraryItem[] = [
  {
    id: IDS.soup,
    fault_code: 'FL-S-AFB5',
    kind: 'scenario',
    name: 'soup-start14',
    verdict: 'reproduces',
    verdict_text: 'The policy fails from start 14 and passes from start 28; five shifts account for the failure.',
    attention: true,
    suite: 'libero_10',
    task_id: 0,
    instruction: SOUP_INSTRUCTION,
    created: '2026-10-08T09:14:00Z',
    case_id: hex('afb5'),
    run: 'soup-start14-20261008-091400',
  },
  {
    id: IDS.imported,
    fault_code: 'FL-S-7E31',
    kind: 'scenario',
    name: 'my-failing-start',
    verdict: 'reproduces',
    verdict_text: 'Your imported start fails 5 of 5 attempts; moving the milk and the robot arm explains it.',
    attention: false,
    suite: 'libero_10',
    task_id: 7,
    instruction: 'put both the alphabet soup and the cream cheese box in the basket',
    created: '2026-10-15T16:40:00Z',
    case_id: hex('7e31'),
    run: 'my-failing-start-20261015-164000',
  },
  {
    id: IDS.nominal,
    fault_code: 'FL-S-9B07',
    kind: 'scenario',
    name: 'soup-screen',
    verdict: 'stopped',
    verdict_text: 'The unperturbed policy did not pass reliably, so no disturbance can be judged.',
    attention: true,
    suite: 'libero_10',
    task_id: 0,
    instruction: SOUP_INSTRUCTION,
    created: '2026-10-12T11:05:00Z',
    case_id: hex('9b07'),
    run: 'soup-screen-20261012-110500',
  },
  {
    id: IDS.audit,
    fault_code: 'FL-A-1C20',
    kind: 'audit',
    name: 'audit-task0',
    verdict: 'reproduces',
    verdict_text: 'Blur breaks the policy from severity 0.50 and contrast from 0.75; noise and darkening did not.',
    attention: false,
    suite: 'libero_object',
    task_id: 0,
    instruction: OBJECT_INSTRUCTION,
    created: '2026-10-10T13:20:00Z',
    case_id: hex('1c20'),
    run: 'audit-task0-20261010-132000',
  },
  {
    id: IDS.wording,
    fault_code: 'FL-L-4D9A',
    kind: 'paraphrase',
    name: 'paraphrase-task0',
    verdict: 'reproduces',
    verdict_text: 'Dropping one word and swapping another is enough to make the policy fail.',
    attention: false,
    suite: 'libero_object',
    task_id: 0,
    instruction: OBJECT_INSTRUCTION,
    created: '2026-10-14T10:02:00Z',
    case_id: hex('4d9a'),
    run: 'paraphrase-task0-20261014-100200',
  },
  {
    id: IDS.pipeAudit,
    fault_code: 'FL-A-5A10',
    kind: 'audit',
    name: 'diagnose-obj0',
    verdict: 'reproduces',
    verdict_text: 'Blur breaks the policy from severity 0.50; the other nine families did not.',
    attention: false,
    suite: 'libero_object',
    task_id: 0,
    instruction: OBJECT_INSTRUCTION,
    created: '2026-10-16T09:40:00Z',
    case_id: hex('5a10'),
    run: 'diagnose-obj0-20261016-090000',
  },
  {
    id: IDS.pipeWording,
    fault_code: 'FL-L-6B21',
    kind: 'paraphrase',
    name: 'diagnose-obj0 (wording)',
    verdict: 'reproduces',
    verdict_text: 'Replacing "place" with "put" is enough to make the policy fail from this start.',
    attention: false,
    suite: 'libero_object',
    task_id: 0,
    instruction: OBJECT_INSTRUCTION,
    created: '2026-10-16T09:55:00Z',
    case_id: hex('6b21'),
    run: 'diagnose-obj0-20261016-090000',
  },
  {
    id: IDS.quiet,
    fault_code: 'FL-L-C3E8',
    kind: 'paraphrase',
    name: 'paraphrase-task4',
    verdict: 'no_failure',
    verdict_text: 'No wording failed 4 of 5 times.',
    attention: false,
    suite: 'libero_object',
    task_id: 4,
    instruction: 'pick up the ketchup and place it in the basket',
    created: '2026-10-16T14:15:00Z',
    case_id: null,
    run: 'para-quiet-20261016-141500',
  },
  {
    id: IDS.occlusion,
    fault_code: 'FL-M-0F42',
    kind: 'occlusion',
    name: 'Occlusion case (M4)',
    verdict: 'reproduces',
    verdict_text: 'A small rectangle over the agent-view camera makes the policy fail, and the rectangle was shrunk to its smallest size.',
    attention: false,
    suite: 'libero_object',
    task_id: 0,
    instruction: OBJECT_INSTRUCTION,
    created: '2026-09-20T08:00:00Z',
    case_id: hex('0f42'),
    run: null,
  },
];

export const library: Library = { items, warnings: [] };

function base(id: string): LibraryItem {
  const found = items.find((entry) => entry.id === id);
  if (!found) throw new Error(`Unknown fixture ${id}`);
  return found;
}

const defaultHistorySteps = [
  { key: 'screen', label: 'Screen starts', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.62 },
  { key: 'reference', label: 'Choose a reference', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.41 },
  { key: 'hypothesis', label: 'Nemotron hypothesis', status: 'completed', state: null, partial: false, cost_usd: null },
  { key: 'reduce', label: 'Reduce the difference', status: 'completed', state: 'succeeded', partial: false, cost_usd: 1.18 },
  { key: 'continue', label: 'Continue the reduction', status: 'stopped', state: 'budget_exhausted', partial: true, cost_usd: 0.55 },
  { key: 'check', label: 'Check the result', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.33 },
  { key: 'explain', label: 'Nemotron explanation', status: 'completed', state: null, partial: false, cost_usd: null },
  { key: 'case', label: 'Save the case', status: 'completed', state: null, partial: false, cost_usd: null },
];

function history(over?: Partial<NonNullable<Detail['history']>>): NonNullable<Detail['history']> {
  return {
    steps: defaultHistorySteps,
    jobs: 4,
    spent_usd: 3.09,
    cap_usd: 3.5,
    hourly_usd: 1.7468,
    elapsed_seconds: 5150,
    max_hours: 2,
    ...over,
  };
}

const details: Record<string, Detail> = {};

details[IDS.soup] = {
  ...base(IDS.soup),
  sentence:
    'From start 14 the policy fails; from the nearest passing start (28) it succeeds, and moving five objects and the robot arm 88% to 100% of the way is enough to make it fail.',
  stop_reason: 'budget_exhausted',
  stop_text: 'Stopped at the candidate budget; this is the smallest cause found so far.',
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_10-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  videos: [
    { role: 'original', label: 'Original failing start', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'minimal', label: 'Minimal cause applied to the reference', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'reference', label: 'Passing reference', url: PLACEHOLDER_VIDEO, outcome: 'success' },
  ],
  scenario: {
    failing_start: 14,
    imported: null,
    reference_start: 28,
    entity_minimal: true,
    reduced: true,
    minimal_cause: [
      { entity: 'alphabet_soup_1', part: 'position', fraction: 0.875, magnitude: '2.5 cm' },
      { entity: 'cream_cheese_1', part: 'position', fraction: 1, magnitude: '1.1 cm' },
      { entity: 'milk_1', part: 'position', fraction: 1, magnitude: '2.4 cm' },
      { entity: 'orange_juice_1', part: 'position', fraction: 1, magnitude: '3.7 cm' },
      { entity: 'robot', part: 'joints', fraction: 0.875, magnitude: '6 joints, up to 2.3°' },
    ],
    differences_count: 6,
    hypothesis: {
      ranked: ['orange_juice_1', 'robot', 'alphabet_soup_1', 'milk_1', 'cream_cheese_1', 'tomato_sauce_1'],
      measured_verdict: 'partly_confirmed',
      verdict_text:
        'Nemotron ranked the orange juice first. The measured reruns found the robot joints and the soup necessary, and the tomato sauce not needed.',
      entities: [
        { entity: 'alphabet_soup_1', label: 'Alphabet soup', necessary: true, sufficient: false },
        { entity: 'robot', label: 'Robot joints', necessary: true, sufficient: false },
        { entity: 'orange_juice_1', label: 'Orange juice', necessary: null, sufficient: false },
        { entity: 'tomato_sauce_1', label: 'Tomato sauce', necessary: false, sufficient: false },
      ],
    },
    reruns: [
      { index: 0, phase: 'gate', role: 'failing', selection: null, outcomes: ['policy_failure', 'policy_failure', 'policy_failure', 'policy_failure'], decision: 'reproduces' },
      { index: 1, phase: 'gate', role: 'reference', selection: null, outcomes: ['success', 'success', 'success', 'success', 'success'], decision: 'passes' },
      { index: 2, phase: 'probe', role: 'hybrid', selection: { alphabet_soup_1: { position: 1 } }, outcomes: ['success', 'success'], decision: 'does_not_reproduce' },
      { index: 3, phase: 'probe', role: 'hybrid', selection: { robot: { joints: 1 }, alphabet_soup_1: { position: 1 } }, outcomes: ['policy_failure', 'success', 'policy_failure', 'policy_failure'], decision: 'reproduces' },
      { index: 4, phase: 'shrink', role: 'hybrid', selection: { robot: { joints: 0.875 }, alphabet_soup_1: { position: 0.875 } }, outcomes: ['policy_failure', 'policy_failure', 'policy_failure', 'success', 'policy_failure'], decision: 'reproduces' },
      { index: 5, phase: 'shrink', role: 'hybrid', selection: { robot: { joints: 0.75 }, alphabet_soup_1: { position: 0.75 } }, outcomes: ['success', 'success'], decision: 'does_not_reproduce' },
    ],
  },
  explanation: {
    status: 'review_required',
    model: 'nvidia/nemotron-3-super-120b-a12b',
    disclaimer:
      'The packet counts reruns only. Necessary and sufficient are relative to the final selection, which is a local minimum; there is no causal proof and the interpretation requires human review.',
    hypotheses: [
      {
        text: 'The failure may require the combined workspace perturbation from all four moved objects plus the robot joint offsets. Test: revert the orange juice to the reference while keeping the others at their final fractions.',
        evidence_ids: ['c12', 'c19', 'c32'],
      },
      {
        text: 'The cream cheese and the milk were never shrink-tested; their full offsets might be larger than necessary. Test: shrink the cream cheese position to 87.5% and check that the failure still reproduces.',
        evidence_ids: ['c32'],
      },
    ],
    observations: [
      { text: 'Moving the soup alone to its failing position did not reproduce the failure (2 of 2 successes).', evidence_ids: ['c4'] },
      { text: 'Adding the robot joint offsets turned that into a repeatable failure (3 of 4).', evidence_ids: ['c9'] },
    ],
    limitations: [
      'Result is a local minimum from a limited number of reruns on one task and one start pair; the reduction stopped early because the budget was used.',
      'No causal proof is provided; human review is required before drawing conclusions.',
    ],
  },
  research: null,
  history: history(),
  replays: [
    { run: 'replay-soup-20261011-153000', verdict: 'reproduces', verdict_text: 'Still reproduces: 4 of 5 attempts failed on the minimal scene, 5 of 5 passed on the reference.', created: '2026-10-11T15:30:00Z', cost_usd: 0.34, checkpoint: null, original: null },
    { run: 'replay-soup-20261014-120000', verdict: 'fixed', verdict_text: 'No longer reproduces after the checkpoint change: 5 of 5 attempts passed.', created: '2026-10-14T12:00:00Z', cost_usd: 0.35, checkpoint: { id: 'my-org/retrained-libero_10', revision: '9f2c1d04a7b3e85c61d0f2a4b8c93e17d5a60b42' }, original: false },
  ],
  report_markdown: soupReport,
  files: [
    { name: 'report.md', url: '/media/cases/afb5/report.md' },
    { name: 'case.json', url: '/media/cases/afb5/case.json' },
    { name: 'explanation.json', url: '/media/cases/afb5/explanation.json' },
  ],
  replayable: true,
};

details[IDS.imported] = {
  ...base(IDS.imported),
  sentence: 'Your imported start fails every time, and moving the milk by 2.1 cm together with the robot arm accounts for it.',
  stop_reason: null,
  stop_text: null,
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_10-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  videos: [
    { role: 'original', label: 'Your imported start', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'minimal', label: 'Minimal cause applied to the reference', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'reference', label: 'Passing reference', url: null, outcome: 'success' },
  ],
  scenario: {
    failing_start: null,
    imported: { file_sha256: 'f00dfeed'.repeat(8), state_sha256: 'cafe1234'.repeat(8) },
    reference_start: 6,
    entity_minimal: true,
    reduced: true,
    minimal_cause: [
      { entity: 'milk_1', part: 'position', fraction: 0.5, magnitude: '2.1 cm' },
      { entity: 'robot', part: 'joints', fraction: 0.75, magnitude: '4 joints, up to 1.9°' },
    ],
    differences_count: 3,
    hypothesis: null,
    reruns: [
      { index: 0, phase: 'gate', role: 'failing', selection: null, outcomes: ['policy_failure', 'policy_failure', 'policy_failure', 'policy_failure', 'policy_failure'], decision: 'reproduces' },
      { index: 1, phase: 'gate', role: 'reference', selection: null, outcomes: ['success', 'success', 'success', 'success', 'success'], decision: 'passes' },
      { index: 2, phase: 'shrink', role: 'hybrid', selection: { milk_1: { position: 0.5 }, robot: { joints: 0.75 } }, outcomes: ['policy_failure', 'policy_failure', 'success', 'policy_failure', 'policy_failure'], decision: 'reproduces' },
    ],
  },
  explanation: null,
  research: null,
  history: history({ jobs: 3, spent_usd: 2.2, cap_usd: 3, elapsed_seconds: 3600, max_hours: 2 }),
  replays: [],
  report_markdown: importedReport,
  files: [{ name: 'report.md', url: '/media/cases/7e31/report.md' }],
  replayable: true,
};

details[IDS.nominal] = {
  ...base(IDS.nominal),
  sentence: null,
  stop_reason: 'nominal_controls_failed',
  stop_text: 'The unperturbed policy did not pass reliably, so no disturbance can be judged.',
  checkpoint: null,
  videos: [],
  scenario: {
    failing_start: null,
    imported: null,
    reference_start: null,
    entity_minimal: null,
    reduced: null,
    minimal_cause: [],
    differences_count: 0,
    hypothesis: null,
    reruns: [],
  },
  explanation: null,
  research: null,
  history: history({
    steps: defaultHistorySteps.slice(0, 2).map((step, index) => (index === 1 ? { ...step, status: 'stopped', state: 'nominal_controls_failed' } : step)),
    jobs: 2,
    spent_usd: 1.03,
    cap_usd: 4,
    elapsed_seconds: 2400,
    max_hours: 3,
  }),
  replays: [],
  report_markdown: null,
  files: [],
  replayable: false,
};

details[IDS.audit] = {
  ...base(IDS.audit),
  sentence: 'Starting from a start that passes cleanly, blur breaks the policy from severity 0.50 and contrast from 0.75. Noise and darkening did not break it up to the strongest level.',
  stop_reason: null,
  stop_text: null,
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_object-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  videos: [{ role: 'threshold', label: 'Blur at severity 0.50', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' }],
  audit: {
    start_index: 0,
    nominal: { failures: 0, attempts: 5 },
    families: [
      {
        family: 'blur',
        label: 'Blur',
        threshold_severity: 0.5,
        stop_reason: 'threshold_found',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 0.25, failures: 0, attempts: 5 },
          { severity: 0.5, failures: 4, attempts: 5 },
        ],
      },
      {
        family: 'noise',
        label: 'Noise',
        threshold_severity: null,
        stop_reason: 'no_reproducible_failure',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 0.5, failures: 0, attempts: 5 },
          { severity: 1, failures: 1, attempts: 5 },
        ],
      },
      {
        family: 'darken',
        label: 'Darken',
        threshold_severity: null,
        stop_reason: 'robust_to_maximum',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 0.5, failures: 0, attempts: 5 },
          { severity: 1, failures: 0, attempts: 5 },
        ],
      },
      {
        family: 'contrast',
        label: 'Contrast',
        threshold_severity: 0.75,
        stop_reason: 'threshold_found',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 0.5, failures: 1, attempts: 5 },
          { severity: 0.75, failures: 5, attempts: 5 },
        ],
      },
    ],
  },
  explanation: null,
  research: null,
  history: history({
    steps: [
      { key: 'audit', label: 'Audit the start', status: 'completed', state: 'succeeded', partial: false, cost_usd: 1.46 },
      { key: 'case', label: 'Save the case', status: 'completed', state: null, partial: false, cost_usd: null },
    ],
    jobs: 1,
    spent_usd: 1.46,
    cap_usd: 2,
    elapsed_seconds: 2900,
    max_hours: 1.5,
  }),
  replays: [],
  report_markdown: auditReport,
  files: [{ name: 'report.md', url: '/media/cases/1c20/report.md' }],
  replayable: false,
};

details[IDS.wording] = {
  ...base(IDS.wording),
  sentence: 'Of ten rewordings, three made the policy fail; removing "up" and replacing "place" with "put" is the smallest edit that still does.',
  stop_reason: null,
  stop_text: null,
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_object-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  videos: [],
  paraphrase: {
    original: OBJECT_INSTRUCTION,
    control: ['success', 'success', 'success', 'success', 'success'],
    paraphrases: [
      { text: 'grab the alphabet soup and put it in the basket', outcomes: ['success', 'success'], failures: 0, meaning: 'Same task' },
      { text: 'pick the alphabet soup and put it in the basket', outcomes: ['policy_failure', 'policy_failure', 'policy_failure', 'success', 'policy_failure'], failures: 4, meaning: 'Same task' },
      { text: 'lift the soup can and set it into the basket', outcomes: ['success', 'policy_failure', 'success'], failures: 1, meaning: 'Same task' },
      { text: 'put the alphabet soup in the basket', outcomes: ['policy_failure', 'policy_failure', 'policy_failure', 'policy_failure', 'policy_failure'], failures: 5, meaning: 'Same task' },
      { text: 'move the basket to the soup', outcomes: [], failures: 0, meaning: 'Changed meaning, discarded' },
    ],
    minimal_edit: { text: 'pick the alphabet soup and put it in the basket', edits: ['remove "up"', 'replace "place" with "put"'] },
  },
  explanation: null,
  research: null,
  history: history({
    steps: [
      { key: 'paraphrase', label: 'Write rewordings', status: 'completed', state: null, partial: false, cost_usd: null },
      { key: 'screen', label: 'Screen rewordings', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.31 },
      { key: 'reduce', label: 'Reduce the wording', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.36 },
      { key: 'case', label: 'Save the case', status: 'completed', state: null, partial: false, cost_usd: null },
    ],
    jobs: 2,
    spent_usd: 0.67,
    cap_usd: 4,
    elapsed_seconds: 1800,
    max_hours: 3,
  }),
  replays: [],
  report_markdown: paraphraseReport,
  files: [{ name: 'report.md', url: '/media/cases/4d9a/report.md' }],
  replayable: false,
};

/* ---- One diagnosis run that passed untouched and was probed ----------------- */

/** Every item the run registered, in route order: the audit case first, then the wording case. */
const pipelineFindings = (): NonNullable<Detail['findings']> =>
  [IDS.pipeAudit, IDS.pipeWording].map((id) => {
    const item = base(id);
    return { id: item.id, fault_code: item.fault_code, kind: item.kind, verdict: item.verdict, verdict_text: item.verdict_text };
  });

const pipelineHistory = history({
  steps: [
    { key: 'check', label: 'Check the start untouched', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.52 },
    { key: 'probe_images_1', label: 'Probe image disturbances (1 of 2)', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.61 },
    { key: 'probe_images_2', label: 'Probe image disturbances (2 of 2)', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.58 },
    { key: 'probe_scene', label: 'Probe scene disturbances', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.49 },
    { key: 'rewordings_screen', label: 'Screen rewordings', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.33 },
    { key: 'rewordings_reduce', label: 'Reduce the wording', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.36 },
    { key: 'case', label: 'Save the cases', status: 'completed', state: null, partial: false, cost_usd: null },
  ],
  jobs: 6,
  spent_usd: 2.89,
  cap_usd: 6,
  elapsed_seconds: 6300,
  max_hours: 4,
});

details[IDS.pipeAudit] = {
  ...base(IDS.pipeAudit),
  sentence:
    'The start passed untouched, so ten disturbance families were probed: blur breaks the policy from severity 0.50, and the other nine did not within their range.',
  stop_reason: null,
  stop_text: null,
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_object-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  // Listed with the failing family first on purpose: the page puts the control first.
  videos: [
    { role: 'blur@0.50', label: 'Blur at s = 0.50 (failed)', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'control', label: 'Control: the start untouched (passed)', url: PLACEHOLDER_VIDEO, outcome: 'success' },
    { role: 'contrast@0.75', label: 'Contrast at s = 0.75 (failed)', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
  ],
  audit: {
    start_index: 0,
    nominal: { failures: 0, attempts: 5 },
    families: [
      {
        family: 'blur',
        label: 'Blur',
        threshold_severity: 0.5,
        stop_reason: 'threshold_found',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 0.5, failures: 4, attempts: 5 },
        ],
      },
      {
        family: 'noise',
        label: 'Noise',
        threshold_severity: null,
        stop_reason: 'no_reproducible_failure',
        levels: [
          { severity: 0, failures: 0, attempts: 5 },
          { severity: 1, failures: 1, attempts: 5 },
        ],
      },
    ],
  },
  explanation: null,
  research: {
    related: 'Image blur is a common robustness test for vision-based manipulation policies; this case is one small, repeatable instance.',
    sources: [{ title: 'Robustness of vision-based policies to image corruptions', url: 'https://example.org/image-corruptions' }],
  },
  history: pipelineHistory,
  replays: [],
  report_markdown: pipelineAuditReport,
  files: [{ name: 'report.md', url: '/media/cases/5a10/report.md' }],
  findings: pipelineFindings(),
  replayable: true,
};

details[IDS.pipeWording] = {
  ...base(IDS.pipeWording),
  sentence: 'Of ten rewordings, one made the policy fail; replacing "place" with "put" is the smallest edit that still does.',
  stop_reason: null,
  stop_text: null,
  checkpoint: { id: 'nvidia/gr00t17-lerobot-libero_object-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db', pinned: true },
  videos: [
    { role: 'control', label: 'Control: the original wording (passed)', url: PLACEHOLDER_VIDEO, outcome: 'success' },
    { role: 'wording', label: 'Failing wording: "pick up the alphabet soup and put it in the basket" (failed)', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
  ],
  paraphrase: {
    original: OBJECT_INSTRUCTION,
    control: ['success', 'success', 'success', 'success', 'success'],
    paraphrases: [
      { text: 'pick up the alphabet soup and put it in the basket', outcomes: ['policy_failure', 'policy_failure', 'success', 'policy_failure', 'policy_failure'], failures: 4, meaning: 'Same task' },
      { text: 'grab the alphabet soup and put it in the basket', outcomes: ['success', 'success'], failures: 0, meaning: 'Same task' },
    ],
    minimal_edit: { text: 'pick up the alphabet soup and put it in the basket', edits: ['replace "place" with "put"'] },
  },
  explanation: null,
  research: null,
  history: pipelineHistory,
  replays: [],
  report_markdown: pipelineWordingReport,
  files: [{ name: 'report.md', url: '/media/cases/6b21/report.md' }],
  findings: pipelineFindings(),
  replayable: true,
};

details[IDS.quiet] = {
  ...base(IDS.quiet),
  sentence: 'None of ten rewordings made the policy fail 4 of 5 times, so there is no case to keep.',
  stop_reason: 'no_reproducible_failure',
  stop_text: 'No failure repeated 4 of 5 times.',
  checkpoint: null,
  videos: [],
  paraphrase: {
    original: 'pick up the ketchup and place it in the basket',
    control: ['success', 'success', 'success', 'success', 'success'],
    paraphrases: [
      { text: 'grab the ketchup and put it in the basket', outcomes: ['success', 'success'], failures: 0, meaning: 'Same task' },
      { text: 'lift the ketchup bottle into the basket', outcomes: ['success', 'success'], failures: 0, meaning: 'Same task' },
      { text: 'place the ketchup in the basket', outcomes: ['success', 'success', 'policy_failure'], failures: 1, meaning: 'Same task' },
    ],
    minimal_edit: null,
  },
  explanation: null,
  research: null,
  history: history({
    steps: [
      { key: 'paraphrase', label: 'Write rewordings', status: 'completed', state: null, partial: false, cost_usd: null },
      { key: 'screen', label: 'Screen rewordings', status: 'completed', state: 'succeeded', partial: false, cost_usd: 0.33 },
    ],
    jobs: 1,
    spent_usd: 0.33,
    cap_usd: 4,
    elapsed_seconds: 1100,
    max_hours: 3,
  }),
  replays: [],
  report_markdown: null,
  files: [],
  replayable: false,
};

details[IDS.occlusion] = {
  ...base(IDS.occlusion),
  sentence: 'A rectangle over 6% of the agent-view image makes the policy fail 4 of 5 times; it was shrunk from 25% of the image.',
  stop_reason: null,
  stop_text: null,
  checkpoint: null,
  videos: [
    { role: 'parent', label: 'Starting rectangle', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'reduced', label: 'Reduced rectangle', url: PLACEHOLDER_VIDEO, outcome: 'policy_failure' },
    { role: 'nominal', label: 'No occlusion', url: PLACEHOLDER_VIDEO, outcome: 'success' },
  ],
  occlusion: {
    perturbation: { agentview_occlusion: { enabled: true, fill: 'black' } },
    lineage: [
      { rectangle: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 }, edge: 'start', delta: 0 },
      { rectangle: { x: 0.2, y: 0.2, width: 0.375, height: 0.5 }, edge: 'right', delta: 0.125 },
      { rectangle: { x: 0.2, y: 0.275, width: 0.375, height: 0.425 }, edge: 'top', delta: 0.075 },
      { rectangle: { x: 0.2, y: 0.275, width: 0.25, height: 0.25 }, edge: 'bottom', delta: 0.175 },
    ],
    episodes: [
      { episode_id: 'ep-nominal-0', stage: 'nominal', role: 'control', outcome: 'success', url: PLACEHOLDER_VIDEO },
      { episode_id: 'ep-parent-0', stage: 'parent', role: 'candidate', outcome: 'policy_failure', url: PLACEHOLDER_VIDEO },
      { episode_id: 'ep-reduced-0', stage: 'reduced', role: 'confirmation', outcome: 'policy_failure', url: PLACEHOLDER_VIDEO },
      { episode_id: 'ep-reduced-1', stage: 'reduced', role: 'confirmation', outcome: 'policy_failure', url: null },
    ],
  },
  explanation: null,
  research: {
    related:
      'Camera occlusion is a common robustness test for vision-based policies. This case is a small, repeatable instance on one task.',
    sources: [
      { title: 'LIBERO benchmark', url: 'https://example.org/libero' },
      { title: 'Occlusion robustness in manipulation policies', url: 'https://example.org/occlusion-robustness' },
    ],
  },
  history: null,
  replays: [],
  report_markdown: null,
  files: [],
  replayable: false,
};

// A diagnosis run that routed to the layout branch registers one case: its findings list is just itself.
{
  const soup = base(IDS.soup);
  (details[IDS.soup] as Detail).findings = [
    { id: soup.id, fault_code: soup.fault_code, kind: soup.kind, verdict: soup.verdict, verdict_text: soup.verdict_text },
  ];
}

export const detailById = details;

/* ---- Runs ---------------------------------------------------------------- */

const stepsWaiting = [
  { key: 'paraphrase', label: 'Write rewordings', status: 'completed', state: null, attempts: 1, capacity_waits: 0 },
  { key: 'screen', label: 'Screen rewordings', status: 'running', state: 'waiting_for_gpu', attempts: 3, capacity_waits: 2 },
  { key: 'reduce', label: 'Reduce the wording', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
  { key: 'case', label: 'Save the case', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
];

const logTail = [
  '[09:31:02] screen: submitting Job (attempt 3)',
  '[09:31:05] screen: Job submitted, waiting for a GPU',
  '[09:36:05] screen: no GPU yet (capacity wait 2 of 6)',
  '[09:41:07] screen: resubmitting',
];

export const progressById: Record<string, Progress> = {
  [RUN_IDS.waiting]: {
    run: RUN_IDS.waiting,
    name: 'paraphrase-task1',
    mode: 'paraphrase',
    status: 'running',
    step: 'screen',
    attention: true,
    stop_reason: null,
    stop_text: null,
    steps: stepsWaiting,
    job: { name: 'screen-attempt-3', phase: 'waiting_for_gpu' },
    spent_usd: 0.04,
    reserved_usd: 0.82,
    cap_usd: 4,
    elapsed_seconds: 1260,
    max_hours: 3,
    log_tail: logTail,
    library_id: null,
    resumable: false,
    stoppable: true,
  },
  [RUN_IDS.running]: {
    run: RUN_IDS.running,
    name: 'audit-task0',
    mode: 'audit',
    status: 'running',
    step: 'audit',
    attention: false,
    stop_reason: null,
    stop_text: null,
    steps: [
      { key: 'audit', label: 'Audit the start', status: 'running', state: 'running', attempts: 1, capacity_waits: 0 },
      { key: 'case', label: 'Save the case', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: { name: 'audit-attempt-1', phase: 'running' },
    spent_usd: 0.31,
    reserved_usd: 0.9,
    cap_usd: 2,
    elapsed_seconds: 1540,
    max_hours: 1.5,
    log_tail: ['[10:16:10] audit: Job running', '[10:24:41] audit: still running (8 min)'],
    library_id: null,
    resumable: false,
    stoppable: true,
  },
  [RUN_IDS.stopping]: {
    run: RUN_IDS.stopping,
    name: 'soup-start14',
    mode: 'scenario',
    status: 'stopping',
    step: 'reduce',
    attention: true,
    stop_reason: 'stopped_by_user',
    stop_text: 'Stopped from the control panel or `faultline stop`.',
    steps: [
      { key: 'screen', label: 'Screen starts', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reference', label: 'Choose a reference', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reduce', label: 'Reduce the difference', status: 'running', state: 'cancelling', attempts: 1, capacity_waits: 0 },
      { key: 'case', label: 'Save the case', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: { name: 'reduce-attempt-1', phase: 'running' },
    spent_usd: 1.2,
    reserved_usd: 0.4,
    cap_usd: 3.5,
    elapsed_seconds: 3300,
    max_hours: 2,
    log_tail: ['[11:55:00] stop requested', '[11:55:02] reduce: cancelling the Job'],
    library_id: null,
    resumable: false,
    stoppable: false,
  },
  [RUN_IDS.completed]: {
    run: RUN_IDS.completed,
    name: 'paraphrase-task0',
    mode: 'paraphrase',
    status: 'completed',
    step: null,
    attention: false,
    stop_reason: null,
    stop_text: null,
    steps: [
      { key: 'paraphrase', label: 'Write rewordings', status: 'completed', state: null, attempts: 1, capacity_waits: 0 },
      { key: 'screen', label: 'Screen rewordings', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reduce', label: 'Reduce the wording', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'case', label: 'Save the case', status: 'completed', state: null, attempts: 1, capacity_waits: 0 },
    ],
    job: { name: 'reduce-attempt-1', phase: 'settled' },
    spent_usd: 0.67,
    reserved_usd: 0,
    cap_usd: 4,
    elapsed_seconds: 1800,
    max_hours: 3,
    log_tail: ['[08:59:12] case: saved', '[08:59:12] done'],
    library_id: IDS.wording,
    resumable: false,
    stoppable: false,
  },
  [RUN_IDS.authExpired]: {
    run: RUN_IDS.authExpired,
    name: 'soup-start14',
    mode: 'scenario',
    status: 'stopped',
    step: 'reduce',
    attention: true,
    stop_reason: 'auth_expired',
    stop_text: 'Your Nebius sign-in expired. Sign in, then resume.',
    steps: [
      { key: 'screen', label: 'Screen starts', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reference', label: 'Choose a reference', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 1 },
      { key: 'reduce', label: 'Reduce the difference', status: 'stopped', state: 'unconfirmed', attempts: 2, capacity_waits: 0 },
      { key: 'case', label: 'Save the case', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: { name: 'reduce-attempt-2', phase: 'running' },
    spent_usd: 1.4,
    reserved_usd: 0.9,
    cap_usd: 3.5,
    elapsed_seconds: 4100,
    max_hours: 2,
    log_tail: ['[20:41:09] reduce: the cloud call failed (sign-in expired)', '[20:41:09] run stopped; resume after signing in'],
    library_id: null,
    resumable: true,
    stoppable: false,
  },
  // A diagnosis whose start passed untouched: the probes are running.
  [RUN_IDS.probing]: {
    run: RUN_IDS.probing,
    name: 'diagnose-obj0',
    mode: 'diagnose',
    status: 'running',
    step: 'probe_images_1',
    attention: false,
    stop_reason: null,
    stop_text: null,
    route: 'probes',
    steps: [
      { key: 'check', label: 'Check the start untouched', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'probe_images_1', label: 'Probe image disturbances (1 of 2)', status: 'running', state: 'running', attempts: 1, capacity_waits: 0 },
      { key: 'probe_images_2', label: 'Probe image disturbances (2 of 2)', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
      { key: 'probe_scene', label: 'Probe scene disturbances', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
      { key: 'rewordings_screen', label: 'Screen rewordings', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
      { key: 'case', label: 'Save the cases', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: { name: 'probe-images-1-attempt-1', phase: 'running' },
    spent_usd: 0.9,
    reserved_usd: 1.3,
    cap_usd: 6,
    elapsed_seconds: 2100,
    max_hours: 4,
    log_tail: ['[10:05:00] check: the start passed 5 of 5; probing', '[10:07:12] probe_images_1: Job running'],
    library_id: null,
    resumable: false,
    stoppable: true,
  },
  // A diagnosis whose start failed untouched: the layout diagnosis is running.
  [RUN_IDS.layoutRoute]: {
    run: RUN_IDS.layoutRoute,
    name: 'soup-start14',
    mode: 'diagnose',
    status: 'running',
    step: 'reduce',
    attention: false,
    stop_reason: null,
    stop_text: null,
    route: 'layout',
    steps: [
      { key: 'check', label: 'Check the start untouched', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reference', label: 'Choose a reference', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'reduce', label: 'Reduce the difference', status: 'running', state: 'running', attempts: 1, capacity_waits: 0 },
      { key: 'case', label: 'Save the case', status: 'pending', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: { name: 'reduce-attempt-1', phase: 'running' },
    spent_usd: 1.4,
    reserved_usd: 1.3,
    cap_usd: 6,
    elapsed_seconds: 3000,
    max_hours: 4,
    log_tail: ['[11:20:00] check: the start failed 4 of 5; diagnosing the layout'],
    library_id: null,
    resumable: false,
    stoppable: true,
  },
  // The untouched start is flaky: the audit's control failed, so the rewordings were skipped.
  [RUN_IDS.flaky]: {
    run: RUN_IDS.flaky,
    name: 'diagnose-flaky',
    mode: 'diagnose',
    status: 'completed',
    step: null,
    attention: true,
    stop_reason: 'nominal_controls_failed',
    stop_text: 'The unperturbed policy did not pass reliably, so no disturbance can be judged.',
    route: 'flaky',
    steps: [
      { key: 'check', label: 'Check the start untouched', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 },
      { key: 'probe_images_1', label: 'Probe image disturbances (1 of 2)', status: 'stopped', state: 'nominal_controls_failed', attempts: 1, capacity_waits: 0 },
      { key: 'rewordings_screen', label: 'Screen rewordings', status: 'skipped', state: null, attempts: 0, capacity_waits: 0 },
    ],
    job: null,
    spent_usd: 1.1,
    reserved_usd: 0,
    cap_usd: 6,
    elapsed_seconds: 2400,
    max_hours: 4,
    log_tail: ['[12:40:00] probe_images_1: the control failed 3 of 5; the start is flaky'],
    library_id: null,
    resumable: false,
    stoppable: false,
  },
  // Nothing to reduce and no probes chosen.
  [RUN_IDS.passes]: {
    run: RUN_IDS.passes,
    name: 'diagnose-clean',
    mode: 'diagnose',
    status: 'completed',
    step: null,
    attention: false,
    stop_reason: null,
    stop_text: null,
    route: 'passes',
    steps: [{ key: 'check', label: 'Check the start untouched', status: 'completed', state: 'succeeded', attempts: 1, capacity_waits: 0 }],
    job: null,
    spent_usd: 0.52,
    reserved_usd: 0,
    cap_usd: 6,
    elapsed_seconds: 900,
    max_hours: 4,
    log_tail: ['[13:15:00] check: the start passed 5 of 5; no probes chosen'],
    library_id: null,
    resumable: false,
    stoppable: false,
  },
};

export function activeRunSummaries(): RunSummary[] {
  return [RUN_IDS.waiting].map((id) => {
    const p = progressById[id] as Progress;
    return {
      run: p.run,
      name: p.name,
      mode: p.mode,
      status: p.status as 'running' | 'stopping',
      step: p.step,
      spent_usd: p.spent_usd,
      cap_usd: p.cap_usd,
      attention: p.attention,
    };
  });
}

/* ---- Environment ----------------------------------------------------------- */

export const environment: Environment = {
  checks: [
    { key: 'nebius_cli', ok: true, detail: 'The Nebius CLI is installed and signed in.' },
    { key: 'docker', ok: true, detail: 'Docker is available (only needed to build the image).' },
    {
      key: 'token_factory_key',
      ok: false,
      detail: 'NEBIUS_API_KEY was not found in .env.',
      fix: 'Add a line NEBIUS_API_KEY=<your Token Factory key> to a file named .env in the folder where you started Faultline. The key stays on this machine.',
    },
    { key: 'spec_template', ok: true, detail: 'A local spec has backend.image and hf_token_secret filled (secret name: faultline-hf-token).' },
  ],
};

/* ---- Evidence --------------------------------------------------------------- */

function episode(index: number, outcome: string, video: boolean): EvidenceEpisode {
  return {
    episode_id: `ep-${String(index).padStart(3, '0')}`,
    run_name: index < 6 ? 'm4-occlusion-sweep' : 'baseline-eval',
    benchmark: 'libero_object',
    created_at: `2026-09-${String(10 + index).padStart(2, '0')}T10:00:00Z`,
    instruction: OBJECT_INSTRUCTION,
    outcome,
    steps: 180 + index * 7,
    elapsed_seconds: 42 + index,
    task_id: 0,
    episode_index: index,
    failure_detail: outcome === 'policy_failure' ? 'Timed out before the soup reached the basket.' : null,
    perturbation: {},
    video_url: video ? '/media/placeholder.webm' : null,
    trace_url: null,
  };
}

export const evidence: Evidence = {
  episodes: [
    episode(0, 'success', true),
    episode(1, 'policy_failure', true),
    episode(2, 'policy_failure', true),
    episode(3, 'success', false),
    episode(4, 'policy_failure', true),
    episode(5, 'success', true),
    episode(6, 'success', false),
    episode(7, 'success', true),
  ],
  warnings: [],
};

/* ---- Spec templates ---------------------------------------------------------- */

const backend = `backend:
  kind: nebius
  project: from-cli-profile
  platform: gpu-l40s-a
  preset: 1gpu-16vcpu-64gb
  image: cr.example.test/fake-registry/faultline-serverless@sha256:0000
  hf_token_secret: faultline-hf-token
  hourly_usd: 1.7468`;

export const specTemplates: Record<string, string> = {
  diagnose: `faultline: 1
name: soup-start14
mode: diagnose
policy: {suite: libero_10}
diagnose:
  task: 0
  start: 14
  probes:
    families: [blur, noise, darken, contrast]
    rewordings: 0
    enabled: true
  layout: true
budget:
  max_spend_usd: 2.5
  max_hours: 1.5
  max_candidates: 36
nemotron: {hypothesis: true, explain: true}
${backend}
`,
  'scenario-start': `faultline: 1
name: soup-start14
mode: scenario
policy: {suite: libero_10}
scenario:
  task: 0
  start: 14
  reference: auto
budget:
  max_spend_usd: 3.5
  max_hours: 2
  max_candidates: 36
nemotron: {hypothesis: true, explain: true}
${backend}
`,
  'scenario-screen': `faultline: 1
name: soup-screen
mode: scenario
policy: {suite: libero_10}
scenario:
  task: 0
  screen: {starts: "10-49", confirm: 4}
  reference: auto
budget:
  max_spend_usd: 4.0
  max_hours: 3
  max_candidates: 36
nemotron: {hypothesis: true, explain: true}
${backend}
`,
  'scenario-import': `faultline: 1
name: my-failing-start
mode: scenario
policy: {suite: libero_10}
scenario:
  task: 0
  import: my-failing-start.candidate.json
  pool: "0-19"
  reference: auto
budget:
  max_spend_usd: 3.0
  max_hours: 2
  max_candidates: 36
nemotron: {hypothesis: true, explain: true}
${backend}
`,
  audit: `faultline: 1
name: audit-task0
mode: audit
policy: {suite: libero_object}
audit:
  task: 0
  start: 0
  families: [blur, noise, darken, contrast]
budget:
  max_spend_usd: 2.0
  max_hours: 1.5
nemotron: {hypothesis: false, explain: false}
${backend}
`,
  paraphrase: `faultline: 1
name: paraphrase-task0
mode: paraphrase
policy: {suite: libero_object}
paraphrase:
  task: 0
  start: 0
  count: 10
budget:
  max_spend_usd: 4.0
  max_hours: 3
nemotron: {hypothesis: false, explain: false}
${backend}
`,
  replay: `faultline: 1
name: replay-soup
mode: replay
budget:
  max_spend_usd: 1.0
  max_hours: 1
${backend}
`,
};
