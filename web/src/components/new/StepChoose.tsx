import type { DiagnosisChoice } from '../../lib/specYaml';

/** The promise of the one diagnosis flow, as shown to the person (ADR 0035). */
export const PIPELINE_PROMISE =
  'Faultline runs your start untouched. If it fails, it finds the smallest change that triggers it. ' +
  'If it passes, it looks for the smallest disturbance or rewording that breaks it.';

const OPTIONS: { choice: DiagnosisChoice; title: string; text: string }[] = [
  {
    choice: 'start',
    title: 'A benchmark start',
    text: 'Give the start number (0 to 49). Faultline checks it untouched, then diagnoses the layout if it fails or probes it if it passes.',
  },
  {
    choice: 'screen',
    title: 'Search a range of starts',
    text: 'Faultline looks for a start that fails reliably, then finds the smallest layout change that triggers it. It looks for a failure and does not probe.',
  },
  {
    choice: 'import',
    title: 'A start file of my own',
    text: 'Upload a start-state JSON file for one suite and task. Faultline checks it fails, then finds the smallest layout change. It looks for a failure and does not probe.',
  },
];

export function StepChoose({ choice, onChoose }: { choice: DiagnosisChoice; onChoose: (choice: DiagnosisChoice) => void }) {
  return (
    <>
      <p className="lede">{PIPELINE_PROMISE}</p>
      <fieldset className="choices">
        <legend>What do you want to check?</legend>
        <div className="choices__grid">
          {OPTIONS.map((option) => (
            <label key={option.choice} className={choice === option.choice ? 'choice choice--selected' : 'choice'}>
              <input
                type="radio"
                name="diagnosis-source"
                value={option.choice}
                checked={choice === option.choice}
                onChange={() => onChoose(option.choice)}
              />
              <span className="choice__title">{option.title}</span>
              <span className="choice__text">{option.text}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </>
  );
}
