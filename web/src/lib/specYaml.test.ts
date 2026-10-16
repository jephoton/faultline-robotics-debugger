import { buildYaml, defaultsFor, errorsByField, extractBackend, fieldForPath, yamlValue } from './specYaml';

const BACKEND = `backend:
  kind: nebius
  project: from-cli-profile
  image: cr.example.test/fake@sha256:0000`;

describe('buildYaml', () => {
  it('builds a scenario spec for a known failing start', () => {
    const yaml = buildYaml('scenario-start', defaultsFor('scenario-start'), BACKEND);
    expect(yaml).toContain('faultline: 1');
    expect(yaml).toContain('mode: scenario');
    expect(yaml).toContain('  start: 14');
    expect(yaml).toContain('max_spend_usd: 3.5');
    expect(yaml).toContain('nemotron: {hypothesis: true, explain: true}');
    expect(yaml.trimEnd().endsWith('image: cr.example.test/fake@sha256:0000')).toBe(true);
  });

  it('builds a range search and an import spec', () => {
    const screen = buildYaml('scenario-screen', defaultsFor('scenario-screen'), BACKEND);
    expect(screen).toContain('screen: {starts: "10-49", confirm: 4}');
    const form = { ...defaultsFor('scenario-import'), importFile: { name: 'mine.json', content: '{}' } };
    expect(buildYaml('scenario-import', form, BACKEND)).toContain('  import: mine.json');
  });

  it('builds an audit with the chosen families and Nemotron off', () => {
    const form = { ...defaultsFor('audit'), families: ['blur', 'lighting'] };
    const yaml = buildYaml('audit', form, BACKEND);
    expect(yaml).toContain('mode: audit');
    expect(yaml).toContain('families: [blur, lighting]');
    expect(yaml).toContain('nemotron: {hypothesis: false, explain: false}');
  });

  it('builds a paraphrase spec that names the task instruction', () => {
    const yaml = buildYaml('paraphrase', defaultsFor('paraphrase'), BACKEND);
    expect(yaml).toContain('mode: paraphrase');
    expect(yaml).toContain('count: 10');
    expect(yaml).toContain('instruction: "pick up the alphabet soup and place it in the basket"');
  });

  it('quotes things that are not numbers so the server can name them', () => {
    const yaml = buildYaml('audit', { ...defaultsFor('audit'), spend: 'lots' }, BACKEND);
    expect(yaml).toContain('max_spend_usd: "lots"');
  });

  it('quotes an unusual name instead of letting it change the YAML', () => {
    const yaml = buildYaml('audit', { ...defaultsFor('audit'), name: 'a: b' }, BACKEND);
    expect(yaml).toContain('name: "a: b"');
  });

  it('leaves out the backend block when the template has none', () => {
    expect(buildYaml('audit', defaultsFor('audit'), null)).not.toContain('backend:');
  });
});

describe('helpers', () => {
  it('extracts the backend block from a template', () => {
    expect(extractBackend(`faultline: 1\n${BACKEND}\n`)).toBe(BACKEND);
    expect(extractBackend('faultline: 1\n')).toBeNull();
  });

  it('reads values from the spec text', () => {
    const yaml = buildYaml('audit', defaultsFor('audit'), null);
    expect(yamlValue(yaml, 'mode')).toBe('audit');
    expect(yamlValue(yaml, 'name')).toBe('audit-task0');
    expect(yamlValue(yaml, 'nothing')).toBeNull();
  });

  it('maps error paths to fields', () => {
    expect(fieldForPath('budget.max_spend_usd')).toBe('spend');
    expect(fieldForPath('budget.max_hours')).toBe('hours');
    expect(fieldForPath('scenario.start')).toBe('start');
    expect(fieldForPath('audit.task')).toBe('task');
    expect(fieldForPath('scenario.screen.starts')).toBe('range');
    expect(fieldForPath('audit.families')).toBe('families');
    expect(fieldForPath('backend.image')).toBeNull();
    const { byField, other } = errorsByField([
      { path: 'budget.max_spend_usd', message: 'bad' },
      { path: 'backend.image', message: 'missing' },
    ]);
    expect(byField.spend).toEqual(['bad']);
    expect(other).toHaveLength(1);
  });
});
