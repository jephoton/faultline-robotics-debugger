import type { AuditFamily, Detail, MinimalCause } from '../../api/types';
import { percent, pluralise } from '../../lib/format';

/** "basket_1" becomes "Basket", "orange_juice_2" becomes "Orange juice". */
export function entityLabel(entity: string): string {
  const words = entity.replace(/_\d+$/, '').replace(/_/g, ' ').trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : entity;
}

function causeSize(row: MinimalCause): string {
  if (row.part === 'joints') return row.magnitude;
  return row.magnitude === 'changed' ? `${row.part} changed` : `${row.part} ${row.magnitude}`;
}

interface Result {
  lead: string;
  bullets: string[];
  /** A short closing line, only when the page shows no stop notice that already says it. */
  note?: string;
}

function scenarioResult(detail: Detail): Result | null {
  const scenario = detail.scenario;
  if (!scenario || scenario.minimal_cause.length === 0) return null;
  const rows = scenario.minimal_cause;
  const from = scenario.reference_start !== null ? `passing start ${scenario.reference_start}` : 'the passing reference';
  const lead =
    rows.length === 1
      ? `${pluralise(1, 'shift')} from ${from} is enough to make the policy fail (at least 4 of 5 attempts):`
      : `${pluralise(rows.length, 'shift')} from ${from} are needed together to make the policy fail (at least 4 of 5 attempts):`;
  const bullets = rows.map((row) => `${entityLabel(row.entity)}: ${causeSize(row)} (${percent(row.fraction)} of the difference)`);
  let note: string | undefined;
  if (!detail.stop_text) {
    if (scenario.reduced === false && scenario.entity_minimal) note = 'Each shift is needed, but their sizes were not fully shrunk.';
    else if (scenario.reduced === false && scenario.entity_minimal === false) note = 'The reduction was cut short, so this may not be the smallest cause.';
  }
  return { lead, bullets, note };
}

/** 0 confirmed threshold, 1 unconfirmed threshold, 2 no failure found, 3 stopped part-way, 4 never searched. */
function familyRank(family: AuditFamily): number {
  if (family.threshold_severity !== null) return family.threshold_unconfirmed ? 1 : 0;
  if (family.stop_reason === 'no_reproducible_failure') return 2;
  return family.levels.length > 0 ? 3 : 4;
}

function highestSeverity(family: AuditFamily): number | null {
  return family.levels.length > 0 ? Math.max(...family.levels.map((level) => level.severity)) : null;
}

function familyBullet(family: AuditFamily): string {
  const threshold = family.threshold_severity;
  const highest = highestSeverity(family);
  switch (familyRank(family)) {
    case 0:
      return `${family.label}: fails from s = ${threshold}`;
    case 1:
      return `${family.label}: fails from s = ${threshold}, unconfirmed (the start's own control failed)`;
    case 2:
      return highest !== null ? `${family.label}: no failure up to s = ${highest}` : `${family.label}: no failure found`;
    case 3:
      return `${family.label}: incomplete, searched up to s = ${highest} and then stopped`;
    default:
      return `${family.label}: not tested`;
  }
}

function auditResult(detail: Detail): Result | null {
  const families = detail.audit?.families ?? [];
  if (families.length === 0) return null;
  const confirmed = families.filter((family) => familyRank(family) === 0).length;
  const unconfirmed = families.some((family) => familyRank(family) === 1);
  const lead = unconfirmed
    ? 'No failure threshold is confirmed:'
    : confirmed > 0
      ? `Fails reliably under ${confirmed} of ${families.length} disturbance ${families.length === 1 ? 'family' : 'families'}:`
      : 'No disturbance family made it fail reliably:';
  const ordered = families
    .map((family, index) => ({ family, index }))
    .sort(
      (a, b) =>
        familyRank(a.family) - familyRank(b.family) ||
        (a.family.threshold_severity ?? 0) - (b.family.threshold_severity ?? 0) ||
        a.index - b.index,
    );
  return { lead, bullets: ordered.map(({ family }) => familyBullet(family)) };
}

/** The result under the case title. Structured data becomes a short lead and one bullet per item; anything else keeps the sentence. */
export function CaseResult({ detail }: { detail: Detail }) {
  const result = detail.kind === 'scenario' ? scenarioResult(detail) : detail.kind === 'audit' ? auditResult(detail) : null;
  if (!result) return <p className="lede">{detail.sentence ?? detail.verdict_text}</p>;
  return (
    <div className="case-result">
      <p className="lede lede--tight">{result.lead}</p>
      <ul className="case-result__list">
        {result.bullets.map((bullet) => (
          <li key={bullet}>{bullet}</li>
        ))}
      </ul>
      {result.note && <p className="muted case-result__note">{result.note}</p>}
    </div>
  );
}
