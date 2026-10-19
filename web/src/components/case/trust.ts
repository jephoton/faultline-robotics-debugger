import type { AuditFamily, Detail, Rerun, ReplayRow } from '../../api/types';
import { entityLabel } from './CaseResult';
import { isFail } from '../Outcomes';

/** How a claim reads at a glance: the badge word comes from the tone. */
export type TrustTone = 'alarm' | 'pass' | 'attention';

export interface TrustLine {
  text: string;
}

export interface TrustClaim {
  key: string;
  tone: TrustTone;
  /** The badge word: "Fails", "Passes", "Flaky", "Borderline". */
  word: string;
  /** The claim in one sentence. */
  title: string;
  /** The rows or levels behind it; empty for a claim that needs no list. */
  lines: TrustLine[];
}

const counts = (outcomes: string[]) => ({ failed: outcomes.filter(isFail).length, total: outcomes.length });
const ofText = (outcomes: string[]) => {
  const { failed, total } = counts(outcomes);
  return `${failed} of ${total} attempts failed`;
};

function entitiesOf(rerun: Rerun): string[] | null {
  return rerun.selection ? Object.keys(rerun.selection).sort() : null;
}

function sameSet(a: string[] | null, b: string[]): boolean {
  if (!a) return false;
  const sorted = [...b].sort();
  return a.length === sorted.length && a.every((value, index) => value === sorted[index]);
}

/** The most attempts wins when several rows match; the first of equals. */
function bestRow(rows: Rerun[]): Rerun | undefined {
  return rows.reduce<Rerun | undefined>((best, row) => (!best || row.outcomes.length > best.outcomes.length ? row : best), undefined);
}

const decidedPass = (rerun: Rerun) => rerun.decision === 'does_not_reproduce' && rerun.outcomes.length > 0;

/**
 * Why a scenario case can be trusted, from its reruns: the gate on both starts, each kept shift passing alone
 * and removing any one passing. A claim whose rows cannot all be found is left out, never guessed.
 */
export function scenarioTrust(detail: Detail): TrustClaim[] {
  const scenario = detail.scenario;
  if (!scenario) return [];
  const claims: TrustClaim[] = [];
  const gate = scenario.reruns.filter((rerun) => rerun.phase === 'gate');

  const failing = gate.find((rerun) => rerun.role.startsWith('failing') && rerun.outcomes.length > 0);
  if (failing) {
    const start = scenario.imported ? 'Your imported start' : scenario.failing_start !== null ? `The failing start (${scenario.failing_start})` : 'The failing start';
    claims.push({
      key: 'gate-failing',
      tone: 'alarm',
      word: 'Fails',
      title: `${start} fails again: ${ofText(failing.outcomes)} (row ${failing.index}).`,
      lines: [],
    });
  }
  const reference = [...gate].reverse().find((rerun) => rerun.role.startsWith('reference') && rerun.decision === 'passes' && rerun.outcomes.length > 0);
  if (reference) {
    const start = scenario.reference_start !== null ? `The reference (start ${scenario.reference_start})` : 'The reference';
    const { failed } = counts(reference.outcomes);
    claims.push({
      key: 'gate-reference',
      tone: failed === 0 ? 'pass' : 'attention',
      word: failed === 0 ? 'Passes' : 'Mostly passes',
      title: `${start} passes: ${ofText(reference.outcomes)} (row ${reference.index}).`,
      lines: [],
    });
  }

  const kept = [...new Set(scenario.minimal_cause.map((row) => row.entity))];
  const others = scenario.reruns.filter((rerun) => rerun.phase !== 'gate');
  if (kept.length >= 2) {
    const alone = kept.map((entity) => bestRow(others.filter((rerun) => rerun.phase === 'probe' && sameSet(entitiesOf(rerun), [entity]) && decidedPass(rerun))));
    if (alone.every(Boolean)) {
      claims.push({
        key: 'alone',
        tone: 'pass',
        word: 'Passes',
        title: 'Each kept shift alone is not enough: the policy passes with only that shift.',
        lines: kept.map((entity, index) => {
          const row = alone[index] as Rerun;
          return { text: `${entityLabel(entity)} alone: ${ofText(row.outcomes)} (row ${row.index})` };
        }),
      });
    }
    const without = kept.map((entity) =>
      bestRow(others.filter((rerun) => rerun.phase === 'ddmin' && sameSet(entitiesOf(rerun), kept.filter((other) => other !== entity)) && decidedPass(rerun))),
    );
    if (without.every(Boolean)) {
      claims.push({
        key: 'without',
        tone: 'pass',
        word: 'Passes',
        title: 'Removing any one kept shift makes the policy pass again, so each is needed.',
        lines: kept.map((entity, index) => {
          const row = without[index] as Rerun;
          return { text: `Without ${entityLabel(entity)}: ${ofText(row.outcomes)} (row ${row.index})` };
        }),
      });
    }
  }
  return claims;
}

function severityText(value: number): string {
  return `s = ${value}`;
}

/** The family keys a replay sentence says no longer failed ("no longer fails at s = 0.60 (noise)"). */
export function replayGoneFamilies(verdictText: string): { family: string; severity: number; higher: number | null }[] {
  const start = verdictText.indexOf('no longer fails at ');
  if (start < 0) return [];
  let segment = verdictText.slice(start + 'no longer fails at '.length);
  const cut = segment.indexOf('; not tested');
  if (cut >= 0) segment = segment.slice(0, cut);
  const found: { family: string; severity: number; higher: number | null }[] = [];
  for (const match of segment.matchAll(/s = ([0-9.]+) \(([^;)]+?)(?:; fails only at higher s = ([0-9.]+))?\)/g)) {
    found.push({ family: (match[2] as string).trim().toLowerCase(), severity: Number(match[1]), higher: match[3] ? Number(match[3]) : null });
  }
  return found;
}

/** The latest replay that tested the original policy (a replay of a new checkpoint says nothing about flakiness). */
function latestOriginalReplay(replays: ReplayRow[]): ReplayRow | null {
  let latest: ReplayRow | null = null;
  for (const replay of replays) {
    if (replay.original === false) continue;
    if (!latest || (replay.created ?? '') >= (latest.created ?? '')) latest = replay;
  }
  return latest;
}

function levelAt(family: AuditFamily, severity: number) {
  return family.levels.find((level) => level.severity === severity);
}

function levelBelow(family: AuditFamily, threshold: number) {
  const below = family.levels.filter((level) => level.severity < threshold);
  return below.length > 0 ? below.reduce((best, level) => (level.severity > best.severity ? level : best)) : undefined;
}

/** Why a stress-test case can be trusted: the control, and the counts around each family's threshold. */
export function auditTrust(detail: Detail): TrustClaim[] {
  const audit = detail.audit;
  if (!audit) return [];
  const claims: TrustClaim[] = [];
  const nominal = audit.nominal;
  if (nominal && nominal.attempts > 0) {
    const clean = nominal.failures === 0;
    claims.push({
      key: 'control',
      tone: clean ? 'pass' : 'attention',
      word: clean ? 'Passes' : 'Flaky',
      title: `The untouched start (the control): ${nominal.failures} of ${nominal.attempts} attempts failed.`,
      lines: [],
    });
  }
  const replay = latestOriginalReplay(detail.replays);
  const gone = replay ? replayGoneFamilies(replay.verdict_text) : [];
  for (const family of audit.families) {
    const threshold = family.threshold_severity;
    if (threshold === null) continue;
    const at = levelAt(family, threshold);
    const below = levelBelow(family, threshold);
    const lines: TrustLine[] = [];
    if (at) lines.push({ text: `At ${severityText(threshold)}, the threshold: ${at.failures} of ${at.attempts} attempts failed` });
    if (below) lines.push({ text: `At ${severityText(below.severity)}, the highest level below it that did not reproduce: ${below.failures} of ${below.attempts} attempts failed` });
    if (lines.length === 0) continue;
    const slipped = gone.find((item) => item.family === family.family.toLowerCase() || item.family === family.label.toLowerCase());
    claims.push({
      key: `family-${family.family}`,
      tone: slipped ? 'attention' : 'alarm',
      word: slipped ? 'Borderline' : 'Fails',
      title: slipped
        ? `${family.label} met the gate, but the latest replay did not repeat it at ${severityText(slipped.severity)}${
            slipped.higher !== null ? ` (it failed only at higher ${severityText(slipped.higher)})` : ''
          }, so treat the threshold as approximate.`
        : `${family.label} fails from ${severityText(threshold)}${family.threshold_unconfirmed ? ', unconfirmed because the control failed' : ''}.`,
      lines,
    });
  }
  return claims;
}

export function trustClaims(detail: Detail): TrustClaim[] {
  return detail.kind === 'scenario' ? scenarioTrust(detail) : detail.kind === 'audit' ? auditTrust(detail) : [];
}
