import type { DiagnosisChoice } from '../../lib/specYaml';

/** The promise of the one diagnosis flow, as shown to the person (ADR 0035). */
export const PIPELINE_PROMISE =
  'Faultline runs your start untouched. If it fails, it finds the smallest change that triggers it. ' +
  'If it passes, it looks for the smallest disturbance or rewording that breaks it.';

/** What a "start" is, said once where the person first meets the word. */
export const START_DEFINITION =
  'A start is one of the benchmark’s 50 fixed starting layouts for a task: where the objects and the arm begin.';

interface Option {
  choice: DiagnosisChoice;
  title: string;
  text: string;
  /** The steps the run will take, in one line. */
  route: string;
}

/** Named by what the person wants, not by the kind of input (October 19, 2026). */
const OPTIONS: Option[] = [
  {
    choice: 'start',
    title: 'Check a start I name',
    text:
      'The usual choice. To diagnose a failure from your own LIBERO evaluation, give its task and start. In the standard LIBERO evaluation, episode n (counted from 0) begins from start n; some tools count from 1 or across tasks.',
    route: 'check it untouched → if it fails, shrink the layout to the trigger; if it passes, probe it',
  },
  {
    choice: 'screen',
    title: 'Find a failing start for me',
    text: 'You have no failure yet. Faultline tries a range of starts and takes one that fails reliably.',
    route: 'run each start in the range once → confirm one that fails → shrink the layout (no probes)',
  },
  {
    choice: 'import',
    title: 'A failure from my own scene (file)',
    text: 'For a failure outside the 50 benchmark starts, such as your own randomised scene: upload its saved start-state JSON file for one suite and task.',
    route: 'confirm it fails 4 of 5 → shrink the layout (no probes)',
  },
];



function Choice({ option, choice, onChoose }: { option: Option; choice: DiagnosisChoice; onChoose: (choice: DiagnosisChoice) => void }) {
  return (
    <label className={choice === option.choice ? 'choice choice--selected' : 'choice'}>
      <input
        type="radio"
        name="diagnosis-source"
        value={option.choice}
        checked={choice === option.choice}
        onChange={() => onChoose(option.choice)}
      />
      <span className="choice__title">{option.title}</span>
      <span className="choice__text">{option.text}</span>
      <span className="choice__text muted">{option.route}</span>
    </label>
  );
}

export function StepChoose({ choice, onChoose }: { choice: DiagnosisChoice; onChoose: (choice: DiagnosisChoice) => void }) {
  return (
    <>
      <p className="lede">{PIPELINE_PROMISE}</p>
      <fieldset className="choices">
        <legend>What do you want to do?</legend>
        <p className="muted">{START_DEFINITION}</p>
        <div className="choices__grid">
          {OPTIONS.map((option) => (
            <Choice key={option.choice} option={option} choice={choice} onChoose={onChoose} />
          ))}
        </div>
      </fieldset>
    </>
  );
}
