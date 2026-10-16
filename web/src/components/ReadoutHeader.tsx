import type { ReactNode } from 'react';

export interface ReadoutField {
  label: string;
  value: ReactNode;
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
 * Scan-tool style readout: a near-black panel in DM Mono with phosphor green text.
 * It is the only decorative use of colour in the interface.
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
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {foot ? <p className="readout__foot">{foot}</p> : null}
    </section>
  );
}
