import {
  REPLAY_DEFAULTS,
  asksForRewordings,
  buildReplayYaml,
  buildYaml,
  defaultsFor,
  errorsByField,
  extractBackend,
  fieldForPath,
  sortFamilies,
  suggestedReplayLimits,
  usesNemotron,
  yamlValue,
} from './specYaml';

const BACKEND = `backend:
  kind: nebius
  project: from-cli-profile
  image: cr.example.test/fake@sha256:0000`;

describe('buildYaml', () => {
  it('builds one diagnose spec for a benchmark start, with four families, no rewordings and probes on', () => {
    const yaml = buildYaml('start', defaultsFor('start'), BACKEND);
    expect(yaml).toContain('faultline: 1');
    expect(yaml).toContain('mode: diagnose');
    expect(yaml).toContain('diagnose:\n  task: 0\n  start: 14');
    expect(yaml).toContain('    families: [blur, noise, darken, contrast]');
    expect(yaml).toContain('    rewordings: 0');
    expect(yaml).toContain('    enabled: true');
    expect(yaml).toContain('max_spend_usd: 2.5');
    expect(yaml).toContain('max_hours: 1.5');
    expect(yaml).toContain('  layout: true');
    expect(yaml).toContain('nemotron: {hypothesis: true, explain: true}');
    expect(yaml).toContain('max_candidates: 36');
    expect(yaml).not.toContain('mode: scenario');
    expect(yaml.trimEnd().endsWith('image: cr.example.test/fake@sha256:0000')).toBe(true);
  });

  it('turns the probes off without losing the choices', () => {
    const yaml = buildYaml('start', { ...defaultsFor('start'), probes: false, families: ['blur'], rewordings: '0' }, BACKEND);
    expect(yaml).toContain('    families: [blur]');
    expect(yaml).toContain('    rewordings: 0');
    expect(yaml).toContain('    enabled: false');
  });

  it('writes the research choice as a top-level key', () => {
    expect(buildYaml('start', defaultsFor('start'), null)).toMatch(/^research: true$/m);
    expect(buildYaml('screen', { ...defaultsFor('screen'), research: false }, null)).toMatch(/^research: false$/m);
  });

  it('keeps the families in the server order however they were ticked', () => {
    const form = { ...defaultsFor('start'), families: ['lighting', 'blur', 'jpeg'] };
    expect(buildYaml('start', form, BACKEND)).toContain('families: [blur, jpeg, lighting]');
    expect(sortFamilies(['lighting', 'nope', 'blur'])).toEqual(['blur', 'lighting', 'nope']);
  });

  it('builds a range search and an import spec with no probe block', () => {
    const screen = buildYaml('screen', defaultsFor('screen'), BACKEND);
    expect(screen).toContain('mode: diagnose');
    expect(screen).toContain('screen: {starts: "10-49", confirm: 4}');
    expect(screen).not.toContain('probes:');
    const form = { ...defaultsFor('import'), importFile: { name: 'mine.json', content: '{}' } };
    const imported = buildYaml('import', form, BACKEND);
    expect(imported).toContain('  import: mine.json');
    expect(imported).not.toContain('probes:');
    expect(imported).not.toContain('families');
  });

  it('quotes things that are not numbers so the server can name them', () => {
    const yaml = buildYaml('start', { ...defaultsFor('start'), spend: 'lots', rewordings: 'many' }, BACKEND);
    expect(yaml).toContain('max_spend_usd: "lots"');
    expect(yaml).toContain('rewordings: "many"');
  });

  it('quotes an unusual name instead of letting it change the YAML', () => {
    const yaml = buildYaml('start', { ...defaultsFor('start'), name: 'a: b' }, BACKEND);
    expect(yaml).toContain('name: "a: b"');
  });

  it('leaves out the backend block when the template has none', () => {
    expect(buildYaml('start', defaultsFor('start'), null)).not.toContain('backend:');
  });
});

describe('what a spec asks of Nemotron', () => {
  it('asks for rewordings only for a single start with probes on and a count above zero', () => {
    const ten = { ...defaultsFor('start'), rewordings: '10' };
    expect(asksForRewordings(buildYaml('start', defaultsFor('start'), null))).toBe(false);
    expect(asksForRewordings(buildYaml('start', ten, null))).toBe(true);
    expect(asksForRewordings(buildYaml('start', { ...ten, probes: false }, null))).toBe(false);
    expect(asksForRewordings(buildYaml('start', { ...ten, rewordings: '0' }, null))).toBe(false);
    expect(asksForRewordings(buildYaml('screen', defaultsFor('screen'), null))).toBe(false);
    expect(asksForRewordings('mode: paraphrase\n')).toBe(true);
    expect(asksForRewordings('mode: audit\n')).toBe(false);
  });

  it('uses Nemotron for a layout reading or for rewordings', () => {
    const quiet = { ...defaultsFor('start'), nemotron: false, research: false };
    expect(usesNemotron(buildYaml('start', { ...quiet, research: true }, null))).toBe(true);
    expect(usesNemotron(buildYaml('start', quiet, null))).toBe(false);
    expect(usesNemotron(buildYaml('start', { ...quiet, rewordings: '10' }, null))).toBe(true);
    expect(usesNemotron(buildYaml('screen', defaultsFor('screen'), null))).toBe(true);
    expect(usesNemotron(buildYaml('screen', { ...defaultsFor('screen'), nemotron: false }, null))).toBe(true); // research
    expect(usesNemotron(buildYaml('screen', { ...defaultsFor('screen'), nemotron: false, research: false }, null))).toBe(false);
  });
});

describe('suggestedReplayLimits', () => {
  it('rounds the worst case up to 10 cents and the time up to a quarter hour', () => {
    expect(suggestedReplayLimits({ jobs: [{ deadline_seconds: 1500 }], worst_case_total_usd: 1.08 })).toEqual({ spend: '1.1', hours: '1' });
    const two = suggestedReplayLimits({ jobs: [{ deadline_seconds: 2400 }, { deadline_seconds: 2000 }], worst_case_total_usd: 3.0 });
    expect(two).toEqual({ spend: '3', hours: '1.75' });
  });
});

describe('buildReplayYaml', () => {
  it('builds a replay spec with the template backend', () => {
    const yaml = buildReplayYaml('soup-start14', REPLAY_DEFAULTS, BACKEND);
    expect(yaml).toContain('mode: replay');
    expect(yaml).toContain('name: replay-soup-start14');
    // The replay Job's worst case is about US$1.08, so the default cap must be above it or Start is refused.
    expect(yaml).toContain('max_spend_usd: 1.2');
    expect(yaml).not.toContain('policy:');
    expect(yaml.trimEnd().endsWith('sha256:0000')).toBe(true);
  });

  it('adds a checkpoint override only when one is given', () => {
    const yaml = buildReplayYaml('x y', { ...REPLAY_DEFAULTS, checkpointId: 'org/ckpt', checkpointRevision: 'abc123' }, null);
    expect(yaml).toContain('name: replay-x-y');
    expect(yaml).toContain('checkpoint: {id: "org/ckpt", revision: "abc123"}');
  });
});

describe('helpers', () => {
  it('extracts the backend block from a template', () => {
    expect(extractBackend(`faultline: 1\n${BACKEND}\n`)).toBe(BACKEND);
    expect(extractBackend('faultline: 1\n')).toBeNull();
  });

  it('reads values from the spec text', () => {
    const yaml = buildYaml('start', defaultsFor('start'), null);
    expect(yamlValue(yaml, 'mode')).toBe('diagnose');
    expect(yamlValue(yaml, 'name')).toBe('soup-start14');
    expect(yamlValue(yaml, 'nothing')).toBeNull();
  });

  it('maps error paths to fields', () => {
    expect(fieldForPath('budget.max_spend_usd')).toBe('spend');
    expect(fieldForPath('budget.max_hours')).toBe('hours');
    expect(fieldForPath('scenario.start')).toBe('start');
    expect(fieldForPath('audit.task')).toBe('task');
    expect(fieldForPath('scenario.screen.starts')).toBe('range');
    expect(fieldForPath('audit.families')).toBe('families');
    expect(fieldForPath('diagnose.start')).toBe('start');
    expect(fieldForPath('diagnose.screen.starts')).toBe('range');
    expect(fieldForPath('diagnose.probes.families')).toBe('families');
    expect(fieldForPath('diagnose.probes.rewordings')).toBe('rewordings');
    expect(fieldForPath('diagnose.probes')).toBeNull();
    expect(fieldForPath('backend.image')).toBeNull();
    const { byField, other } = errorsByField([
      { path: 'budget.max_spend_usd', message: 'bad' },
      { path: 'backend.image', message: 'missing' },
    ]);
    expect(byField.spend).toEqual(['bad']);
    expect(other).toHaveLength(1);
  });
});
