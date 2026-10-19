import { useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
// The single source of truth is docs/reference.md in the repository; the build bundles it, so the page and the
// document can never drift apart (CI fails if the committed bundle is stale).
import referenceSource from '../../../docs/reference.md?raw';
import { Markdown, headingSlug } from '../components/Markdown';
import { useDocumentTitle } from '../lib/useDocumentTitle';

const REPOSITORY_DOCS = 'https://github.com/jephoton/faultline-robotics-debugger/blob/main/docs/';

/**
 * The page body: the document without its own title (the page has the h1), and with links to other repository
 * documents pointing at GitHub, because the control panel and the gallery do not serve the docs folder.
 */
export function prepareReference(source: string): string {
  const withoutTitle = source.replace(/^# .*\n+/, '');
  return withoutTitle.replace(/\]\((?!https?:|#|mailto:)([^)\s]+\.(?:md|png))(#[^)]*)?\)/g, (_match, path: string, hash = '') => {
    return `](${REPOSITORY_DOCS}${path}${hash})`;
  });
}

/** The table of contents: the `##` sections, with ids as the Markdown renderer assigns them. */
export function referenceSections(source: string): { id: string; title: string }[] {
  return Array.from(source.matchAll(/^## (.+)$/gm), (match) => {
    const title = (match[1] as string).trim();
    return { id: `md-${headingSlug(title)}`, title };
  });
}

export function ReferencePage() {
  useDocumentTitle('Reference');
  const { hash } = useLocation();
  const body = useMemo(() => prepareReference(referenceSource), []);
  const sections = useMemo(() => referenceSections(body), [body]);

  useEffect(() => {
    if (!hash) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [hash]);

  return (
    <article className="reference">
      <h1>Reference</h1>
      <p className="lede">
        What Faultline does and what everything it shows means: the diagnosis and its routes, the repeatability gate, how a reduction works,
        every severity level, every report column and abbreviation, the verdicts and stop reasons, and the spend cap.
      </p>
      <nav aria-label="On this page" className="panel guide-toc">
        <p className="section-label">On this page</p>
        <ol>
          {sections.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>{section.title.replace(/^\d+\.\s*/, '')}</a>
            </li>
          ))}
        </ol>
      </nav>
      <Markdown source={body} headingOffset={0} />
    </article>
  );
}
