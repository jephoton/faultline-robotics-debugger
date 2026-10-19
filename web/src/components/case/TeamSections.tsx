import type { Detail, HypothesisEntity, NextSteps } from '../../api/types';
import type { ReportParts } from '../../lib/reportSections';
import { Icon, type IconName } from '../Icon';
import { LONG_TABLE_ROWS, Markdown } from '../Markdown';
import { Section } from '../Section';
import { entityLabel } from './CaseResult';
import { ExplanationBody, RESEARCH_HINT, ResearchBody } from './CommonSections';
import { trustClaims, type TrustTone } from './trust';

/** The report page for a team: summary, why to trust it, Nemotron's suggestions, then the rest folded away. */

const TONE_ICON: Record<TrustTone, IconName> = { alarm: 'alarm', pass: 'tick', attention: 'attention' };

export function TrustSection({ detail }: { detail: Detail }) {
  const claims = trustClaims(detail);
  if (claims.length === 0) return null;
  return (
    <Section title="Why it's trustworthy" hint={
        detail.kind === 'scenario'
          ? 'Each line is a count from the saved reruns. The row numbers are the # column of the Candidates table under Full evidence.'
          : 'Each line is a count from the saved attempts.'
      }>
      <ul className="trust">
        {claims.map((claim) => (
          <li key={claim.key} className={`trust__item trust__item--${claim.tone}`}>
            <span className={`badge badge--${claim.tone}`}>
              <Icon name={TONE_ICON[claim.tone]} />
              {claim.word}
            </span>
            <div className="trust__body">
              <p className="trust__title">{claim.title}</p>
              {claim.lines.length > 0 && (
                <ul className="trust__lines">
                  {claim.lines.map((line) => (
                    <li key={line.text}>{line.text}</li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** What the reruns measured for an entity, in plain words. */
export function measuredWords(entity: HypothesisEntity | undefined): { icon: IconName; text: string } {
  if (!entity) return { icon: 'minus', text: 'not measured' };
  const { necessary, sufficient } = entity;
  if (necessary === true && sufficient === true) return { icon: 'tick', text: 'needed and enough alone' };
  if (sufficient === true) return { icon: 'tick', text: 'enough alone' };
  if (necessary === true) return { icon: 'tick', text: sufficient === false ? 'needed but not enough alone' : 'needed' };
  if (necessary === false) return { icon: 'close', text: 'not needed' };
  if (sufficient === false) return { icon: 'close', text: 'not enough alone' };
  return { icon: 'minus', text: 'not measured' };
}

const TOP_GUESSES = 3;

function GuessVsReruns({ detail }: { detail: Detail }) {
  const hypothesis = detail.kind === 'scenario' ? detail.scenario?.hypothesis : null;
  if (!hypothesis || hypothesis.ranked.length === 0) return null;
  return (
    <>
      <h3>Its guess vs the reruns</h3>
      <p className="muted">The entities Nemotron ranked as most likely to matter, before any rerun, and what the reruns then showed.</p>
      <ol className="ranked ranked--measured">
        {hypothesis.ranked.slice(0, TOP_GUESSES).map((entity) => {
          const entry = hypothesis.entities.find((item) => item.entity === entity);
          const words = measuredWords(entry);
          return (
            <li key={entity}>
              <span className="ranked__name">{entry?.label || entityLabel(entity)}</span>
              <span className="ranked__result">
                <Icon name={words.icon} /> {words.text}
              </span>
            </li>
          );
        })}
      </ol>
    </>
  );
}

function Cites({ cites, sources }: { cites: string[]; sources: NextSteps['sources'] }) {
  if (cites.length === 0) return null;
  return (
    <span className="cites">
      {cites.map((cite) => {
        const id = cite.replace(/^\[|\]$/g, '');
        const source = sources.find((item) => item.id === id);
        return source && /^https?:\/\//i.test(source.url) ? (
          <a key={cite} className="cite" href={source.url} rel="noopener noreferrer" target="_blank" title={source.title}>
            [{id}]
          </a>
        ) : (
          <code key={cite} className="cite">
            {id}
          </code>
        );
      })}
    </span>
  );
}

/** True when the case has suggested next steps to show. */
export function hasNextSteps(detail: Detail): boolean {
  return Boolean(detail.next_steps && detail.next_steps.items.length > 0);
}

function NextStepsList({ steps }: { steps: NextSteps }) {
  const linked = steps.sources.filter((source) => /^https?:\/\//i.test(source.url));
  return (
    <>
      <h3>Suggested next steps</h3>
      <p className="muted">Suggestions from {steps.model ? <span className="mono">{steps.model}</span> : 'Nemotron'}, not evidence.</p>
      <ol className="steps">
        {steps.items.map((item) => (
          <li key={item.text}>
            <span>{item.text}</span> <Cites cites={item.cites} sources={steps.sources} />
          </li>
        ))}
      </ol>
      {linked.length > 0 && (
        <>
          <h4>Sources</h4>
          <ul className="sources">
            {linked.map((source) => (
              <li key={source.id}>
                <span className="cite">[{source.id}]</span>{' '}
                <a href={source.url} rel="noopener noreferrer" target="_blank">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/** One compact Nemotron box: its guess against the reruns (scenario cases) and its suggested next steps. */
export function NemotronBox({ detail }: { detail: Detail }) {
  const hypothesis = detail.kind === 'scenario' ? detail.scenario?.hypothesis : null;
  const guess = Boolean(hypothesis && hypothesis.ranked.length > 0);
  const steps = hasNextSteps(detail) ? (detail.next_steps as NextSteps) : null;
  if (!guess && !steps) return null;
  return (
    <Section title="Nemotron">
      <div className="panel nemotron">
        <GuessVsReruns detail={detail} />
        {steps && <NextStepsList steps={steps} />}
      </div>
    </Section>
  );
}

/** The rest of the report and Nemotron's full reading, folded; older research context lives here too. */
export function FullEvidence({ detail, parts }: { detail: Detail; parts: ReportParts }) {
  const reading = Boolean(detail.explanation);
  const research = Boolean(detail.research) && !hasNextSteps(detail);
  if (!parts.rest && !reading && !research) return null;
  const what = [parts.rest ? 'the rest of the report' : null, reading ? "Nemotron's full reading" : null, research ? 'the research context' : null].filter(Boolean);
  const label = `Show ${what.join(', ').replace(/, ([^,]*)$/, ' and $1')}`;
  return (
    <Section title="Full evidence">
      <details className="fold fold--evidence">
        <summary>{label}</summary>
        {parts.rest && <Markdown source={parts.rest} collapseAbove={LONG_TABLE_ROWS} headingOffset={1} />}
        {reading && (
          <>
            <h3>Nemotron's full reading</h3>
            <p className="muted">An interpretation written by a language model from the results. It is not evidence and needs human review.</p>
            <ExplanationBody detail={detail} level={4} />
          </>
        )}
        {research && (
          <>
            <h3>Research context</h3>
            <p className="muted">{RESEARCH_HINT}</p>
            <ResearchBody detail={detail} />
          </>
        )}
      </details>
    </Section>
  );
}
