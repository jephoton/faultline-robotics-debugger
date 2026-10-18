// Stored-report fixtures, shaped like the Markdown the report scripts write (scripts/report_*.py):
// a title, a "## Summary" of bullets, then the detail. All ids and hashes are fake: the repository is public.

/** A Candidates table long enough to be folded on the case page (the real ones run to 26 rows or more). */
function candidatesTable(rows: number): string {
  const header = [
    '| # | phase | role | selection | outcomes | decision | gate met | skipped | late |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
  ];
  const body = Array.from({ length: rows }, (_, index) => {
    if (index === 0) return `| 0 | gate | failing | - | F F F F | reproduces | True | 1 | - |`;
    if (index === 1) return `| 1 | gate | reference 28 | - | S S S S S | passes | True | 0 | - |`;
    const phase = index < 8 ? 'probe' : index < 22 ? 'ddmin' : 'shrink';
    const failing = index % 5 === 0;
    const outcomes = failing ? 'F F F F' : 'S S';
    return `| ${index} | ${phase} | hybrid 28 | alphabet_soup_1 (position ${failing ? 0.875 : 1}) | ${outcomes} | ${
      failing ? 'reproduces' : 'does_not_reproduce'
    } | ${failing} | ${failing ? 1 : 3} | - |`;
  });
  return [...header, ...body].join('\n');
}

export const soupReport = `# Scenario reduction: put both the alphabet soup and the tomato sauce in the basket

## Summary

- Verdict: Reproduces. Applying the kept shifts to the passing reference makes the policy fail at least 4 of 5 attempts.
- Failing start: benchmark start 14.
- Reference: benchmark start 28, the nearest start that passed.
- Kept shift: alphabet_soup_1 position, 2.5 cm (87.5% of the full difference).
- Kept shift: cream_cheese_1 position, 1.1 cm (100% of the full difference).
- Kept shift: milk_1 position, 2.4 cm (100% of the full difference).
- Kept shift: orange_juice_1 position, 3.7 cm (100% of the full difference).
- Kept shift: robot joints, 6 joints, up to 2.3° (87.5% of the full difference).
- Status: Stopped at the candidate budget: entity-minimal (each kept entity is needed), sizes not fully shrunk.

Suite \`libero_10\`, task 0. Reference runs decide everything below; the model only proposes an order and a hypothesis.

## Result

- Stop reason: \`budget_exhausted\`
- Failing start: 14; reference (nearest passing start): 28; candidate references tried: 28 (passes)
- Entity-minimal: yes
- Checkpoint: \`nvidia/gr00t17-lerobot-libero_10-640\` at revision \`5ee08ab\`

### Minimal cause

Moving alphabet_soup_1 by 2.5 cm (of the original 2.9 cm), cream_cheese_1 by 1.1 cm, milk_1 by 2.4 cm, orange_juice_1 by 3.7 cm and 6 joints of robot 88% of the way to their failing values are enough to make the policy fail from the passing start 28 (at least 4 of 5 attempts); sizes not fully shrunk; the reduction stopped early, so this is the smallest cause found so far.

This is a local minimum found by reruns, not proof of the globally smallest cause.

## Hypothesis

- Order source: \`model\`
- Ranking: orange_juice_1, robot, alphabet_soup_1, milk_1, cream_cheese_1, tomato_sauce_1
- Verdict (top-ranked entity against the surviving entities): **partly_confirmed**

## Candidates

Every rerun, in order. Phases: \`gate\`, \`probe\`, \`ddmin\`, \`shrink\`. Outcomes: S success, F policy failure, I invalid scene.

${candidatesTable(26)}

Invalid scenes (never counted as failures): none

## Effort

- Candidates tested: 24; attempts run: 98
- Job seconds: 3100; server start-up seconds: 410
`;

export const importedReport = `# Scenario reduction: put both the alphabet soup and the cream cheese box in the basket

## Summary

- Verdict: Reproduces. Applying the kept shifts to the passing reference makes the policy fail at least 4 of 5 attempts.
- Failing start: imported file f00dfeedf00d (from benchmark start 3).
- Reference: benchmark start 6, the nearest start that passed.
- Kept shift: milk_1 position, 2.1 cm (50% of the full difference).
- Kept shift: robot joints, 4 joints, up to 1.9° (75% of the full difference).
- Status: Fully reduced: every kept shift was shrunk to within 1/16 of its original size.

Suite \`libero_10\`, task 7. Reference runs decide everything below.

## Candidates

${candidatesTable(5)}
`;

export const auditReport = `# M6 results: camera reliance and scalar image families

## Summary

- Unperturbed control: 0 of 5 attempts failed.
- Blur: fails from s = 0.50.
- Noise: no failure up to s = 1.00.
- Darken: no failure up to s = 1.00.
- Contrast: fails from s = 0.75.

Scope: GR00T N1.7 on LIBERO-Object task 0, benchmark start 0, seed 7, on one L40S. Thresholds are budget-local and describe reliable failure, not the onset of any failure.

## Threshold search per family (main Job)

| Family | Smallest reproducibly failing severity | Stop reason |
| --- | --- | --- |
| Blur | 0.5 | threshold found |
| Noise | none up to 1 | no reproducible failure up to s = 1 |
| Darken | none up to 1 | no reproducible failure up to s = 1 |
| Contrast | 0.75 | threshold found |
`;

export const paraphraseReport = `# Faultline paraphrase report

## Summary

- Control: the original wording passed (S S S S S).
- Rewordings: 5 screened; 4 kept by the meaning check, 1 dropped (an object or target word of the instruction was missing).
- Failures: 2 rewordings failed at least 4 of 5 attempts (p02, p04).
- Smallest failing wording: 2 word edits from the original; each remaining edit is needed.
- Minimal wording: "pick the alphabet soup and put it in the basket"

## Screen

| label | kind | outcomes | decision | word edits | meaning check |
| --- | --- | --- | --- | --- | --- |
| orig | original | S S | control | - | - |
| p01 | paraphrase | S S | passed | 2 | kept |
| p02 | paraphrase | F F F S F | reproduces | 2 | kept |
`;
