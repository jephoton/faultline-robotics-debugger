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
          ? 'Counts from the saved reruns; row numbers match the # column of the Candidates table under Full evidence.'
          : undefined
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
      <p className="muted">Ranked by Nemotron before any rerun.</p>
      <ol className="ranked ranked--measured">
        {hypothesis.ranked.slice(0, TOP_GUESSES).map((entity) => {
          const entry = hypothesis.entities.find((item) => item.entity === entity);
          const words = measuredWords(entry);
          return (
            <li key={entity}>
              <span className="ranked__name">{entityLabel(entity)}</span>
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

const isLink = (url: string) => /^https?:\/\//i.test(url);

/** How an evidence id reads: a rerun `c37` is "row 37", a stress-test level `blur@0.4625` is "blur s=0.4625". */
export function evidenceTag(id: string): { text: string; title: string } | null {
  const row = /^c([0-9]+)$/.exec(id);
  if (row) return { text: `row ${row[1]}`, title: `Rerun ${row[1]}: the # column of the Candidates table under Full evidence` };
  const level = /^([a-z][a-z_]*)@([0-9]+(?:\.[0-9]+)?)$/.exec(id);
  if (level) {
    const family = (level[1] as string).replace(/_/g, ' ');
    return { text: `${family} s=${level[2]}`, title: `The ${family} level at severity ${level[2]}, as counted in the stress test` };
  }
  return null;
}

function Cites({ cites, sources }: { cites: string[]; sources: NextSteps['sources'] }) {
  if (cites.length === 0) return null;
  return (
    <span className="cites">
      {cites.map((cite) => {
        const id = cite.replace(/^\[|\]$/g, '');
        const source = sources.find((item) => item.id === id);
        if (source && isLink(source.url)) {
          return (
            <a key={cite} className="cite" href={source.url} rel="noopener noreferrer" target="_blank" title={source.title}>
              [{id}]
            </a>
          );
        }
        const tag = evidenceTag(id);
        return (
          <code key={cite} className="cite" title={tag?.title}>
            {tag ? tag.text : id}
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

/** The linked sources the items cite, in order of first citation, and the other retrieved ones. */
export function splitSources(steps: NextSteps): { cited: NextSteps['sources']; others: NextSteps['sources'] } {
  const linked = steps.sources.filter((source) => isLink(source.url));
  const order: string[] = [];
  for (const item of steps.items) {
    for (const cite of item.cites) {
      const id = cite.replace(/^\[|\]$/g, '');
      if (!order.includes(id)) order.push(id);
    }
  }
  const cited = order.flatMap((id) => linked.filter((source) => source.id === id));
  return { cited, others: linked.filter((source) => !cited.includes(source)) };
}

function SourceList({ sources }: { sources: NextSteps['sources'] }) {
  return (
    <ul className="sources">
      {sources.map((source) => (
        <li key={source.id}>
          <span className="cite">[{source.id}]</span>{' '}
          <a href={source.url} rel="noopener noreferrer" target="_blank">
            {source.title}
          </a>
        </li>
      ))}
    </ul>
  );
}

function NextStepsList({ steps }: { steps: NextSteps }) {
  const { cited, others } = splitSources(steps);
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
      {cited.length > 0 && (
        <>
          <h4>Sources</h4>
          <SourceList sources={cited} />
        </>
      )}
      {others.length > 0 && (
        <details className="fold fold--sources">
          <summary>
            {others.length} {cited.length > 0 ? 'other ' : ''}
            {others.length === 1 ? 'source' : 'sources'} retrieved{cited.length > 0 ? '' : ', none cited'}
          </summary>
          <SourceList sources={others} />
        </details>
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
