import type { Detail } from '../../api/types';
import { Icon } from '../Icon';
import { Outcomes } from '../Outcomes';
import { Empty, Section } from '../Section';

export function ParaphraseSection({ detail }: { detail: Detail }) {
  const p = detail.paraphrase;
  if (!p) return null;
  return (
    <>
      <Section
        title="Wordings tried"
        hint="Every wording is run from the same start. A rewording that changes the task's meaning is discarded, not counted as a policy failure."
      >
        {p.paraphrases.length === 0 ? (
          <Empty>No rewordings were run.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Wording</th>
                  <th scope="col">Attempts</th>
                  <th scope="col">Meaning check</th>
                </tr>
              </thead>
              <tbody>
                <tr className="row--control">
                  <td>
                    <span className="tag">Original</span> {p.original ?? 'not recorded'}
                  </td>
                  <td>
                    <Outcomes outcomes={p.control} label="Original wording" />
                  </td>
                  <td className="muted">Control</td>
                </tr>
                {p.paraphrases.map((row) => (
                  <tr key={row.text}>
                    <td>{row.text}</td>
                    <td>
                      <Outcomes outcomes={row.outcomes} label={row.text} />
                    </td>
                    <td>{row.meaning ?? <span className="muted">not checked</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Smallest word change that still fails">
        {p.minimal_edit ? (
          <div className="panel">
            <p className="lede lede--tight">
              <Icon name="alarm" /> {p.minimal_edit.text}
            </p>
            <p className="section-label">Edits from the original</p>
            <ul className="edits">
              {p.minimal_edit.edits.map((edit) => (
                <li key={edit}>{edit}</li>
              ))}
            </ul>
          </div>
        ) : (
          <Empty>No wording failed reliably, so there was nothing to reduce.</Empty>
        )}
      </Section>
    </>
  );
}
