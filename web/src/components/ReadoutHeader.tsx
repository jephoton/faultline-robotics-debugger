import type { ReactNode } from 'react';
import { Icon, type IconName } from './Icon';
import type { Tone } from '../lib/status';

export interface ReadoutField {
  label: string;
  value: ReactNode;
  /** A status field (verdict, run status) keeps the outcome colours inside the readout (red, green, amber); others stay phosphor green. */
  tone?: Tone;
  icon?: IconName;
}

interface Props {
  /** Fault code such as FL-S-AFB5, or a run label. */
  code: string;
  /** Small caption above or beside the code, for example "Fault code". */
  tag?: string;
  fields: ReadoutField[];
  /** One line under the fields, for example the task instruction. */
  foot?: ReactNode;
}

/**
 * Scan-tool style readout: a near-black panel in DM Mono with phosphor green text, the only decorative use of
 * colour in the interface. A status field is the exception: red for a reproducing failure, bright green for a
 * pass, amber for attention, off-white for a normal result, each with an icon, so the verdict stands out from the descriptive fields.
 */
export function ReadoutHeader({ code, tag = 'Fault code', fields, foot }: Props) {
  return (
    <section className="readout" aria-label="Readout">
      <div className="readout__top">
        <div className="readout__code">
          <span className="sr-only">{tag}: </span>
          {code}
        </div>
        <span className="readout__tag" aria-hidden="true">
          {tag}
        </span>
      </div>
      {fields.length > 0 && (
        <dl className="readout__fields">
          {fields.map((field) => (
            <div className="readout__field" key={field.label}>
              <dt>{field.label}</dt>
              <dd className={field.tone ? `readout__value readout__value--${field.tone}` : undefined}>
                {field.icon && <Icon name={field.icon} />}
                {field.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {foot ? <p className="readout__foot">{foot}</p> : null}
    </section>
  );
}
