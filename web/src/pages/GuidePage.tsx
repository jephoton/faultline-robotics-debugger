import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { GUIDE } from '../content/guide';
import { useDocumentTitle } from '../lib/useDocumentTitle';

export function GuidePage() {
  useDocumentTitle('Run your own');
  const { hash } = useLocation();

  // A link such as /guide#image should land on that section.
  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    if (target) {
      target.scrollIntoView();
      target.focus({ preventScroll: true });
    }
  }, [hash]);

  return (
    <article>
      <h1>Run your own</h1>
      <p className="lede">Run a diagnosis on your own Nebius account, from the control panel or a terminal.</p>
      <nav aria-label="On this page" className="panel guide-toc">
        <p className="section-label">On this page</p>
        <ol>
          {GUIDE.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>{section.title.replace(/^\d+\.\s*/, '')}</a>
            </li>
          ))}
        </ol>
      </nav>
      {GUIDE.map((section) => (
        <section className="section guide" key={section.id} aria-labelledby={`${section.id}-title`}>
          <h2 id={section.id} tabIndex={-1}>
            <span id={`${section.id}-title`}>{section.title}</span>
          </h2>
          {section.body}
        </section>
      ))}
    </article>
  );
}
