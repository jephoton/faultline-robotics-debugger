import type { DiagnosisChoice } from '../../lib/specYaml';

type Group = 'scenario' | 'audit' | 'paraphrase';

export function groupOf(choice: DiagnosisChoice): Group {
  return choice.startsWith('scenario') ? 'scenario' : (choice as Group);
}

const GROUPS: { group: Group; title: string; text: string; first: DiagnosisChoice }[] = [
  {
    group: 'scenario',
    title: 'Find why a start fails',
    text: 'Compare a failing start with the nearest passing start and reduce the difference to the shifts that cause the failure.',
    first: 'scenario-start',
  },
  {
    group: 'audit',
    title: 'Stress-test a passing start',
    text: 'Find the smallest image or scene disturbance (blur, noise, lighting and so on) that makes a passing start fail.',
    first: 'audit',
  },
  {
    group: 'paraphrase',
    title: 'Test rewordings',
    text: 'Have Nemotron reword the task instruction, find a wording that breaks the policy, and reduce it to the smallest word change.',
    first: 'paraphrase',
  },
];

const SCENARIO_OPTIONS: { choice: DiagnosisChoice; label: string; text: string }[] = [
  { choice: 'scenario-start', label: 'A benchmark start I know fails', text: 'Give the start number (0 to 49).' },
  { choice: 'scenario-screen', label: 'Search a range of starts', text: 'Faultline looks for a start that fails reliably.' },
  { choice: 'scenario-import', label: 'A start file of my own', text: 'Upload a start-state JSON file for one suite and task.' },
];

export function StepChoose({ choice, onChoose }: { choice: DiagnosisChoice; onChoose: (choice: DiagnosisChoice) => void }) {
  const current = groupOf(choice);
  return (
    <fieldset className="choices">
      <legend>What do you want to diagnose?</legend>
      <div className="choices__grid">
        {GROUPS.map((entry) => (
          <label key={entry.group} className={current === entry.group ? 'choice choice--selected' : 'choice'}>
            <input
              type="radio"
              name="diagnosis-kind"
              value={entry.group}
              checked={current === entry.group}
              onChange={() => onChoose(entry.first)}
            />
            <span className="choice__title">{entry.title}</span>
            <span className="choice__text">{entry.text}</span>
          </label>
        ))}
      </div>
      {current === 'scenario' && (
        <fieldset className="choices__sub">
          <legend>How will you name the failing start?</legend>
          {SCENARIO_OPTIONS.map((option) => (
            <label key={option.choice} className="check check--block">
              <input
                type="radio"
                name="scenario-source"
                value={option.choice}
                checked={choice === option.choice}
                onChange={() => onChoose(option.choice)}
              />
              <span>
                <span className="check__label">{option.label}</span>
                <span className="muted"> {option.text}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
    </fieldset>
  );
}
