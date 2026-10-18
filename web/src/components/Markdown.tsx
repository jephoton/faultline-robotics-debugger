import DOMPurify from 'dompurify';
import { Marked, type Tokens } from 'marked';
import { useMemo } from 'react';

/** A report table with more body rows than this is folded behind a "Show all n rows" toggle. */
export const LONG_TABLE_ROWS = 12;

// Anchor ids for the headings of the document being parsed. `renderMarkdown` resets it for every document.
let usedIds = new Map<string, number>();
// How many levels a Markdown heading is pushed down: reports start at h3 (`#` -> h3) under the case page's h2s;
// the Reference page uses 0 so its `##` sections are h2 under the page's h1.
let headingOffset = 2;

/** The anchor slug of a heading's text (the part after `md-`), shared with tables of contents. */
export function headingSlug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[`*_~]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'section'
  );
}

function headingId(text: string): string {
  const base = headingSlug(text);
  const seen = usedIds.get(base) ?? 0;
  usedIds.set(base, seen + 1);
  return seen === 0 ? `md-${base}` : `md-${base}-${seen + 1}`;
}

// Report headings start at h3 so the page keeps one h1 and the section h2s.
const parser = new Marked({
  gfm: true,
  breaks: false,
  async: false,
  renderer: {
    heading(this: { parser: { parseInline: (tokens: Tokens.Generic[]) => string } }, token: Tokens.Heading) {
      const level = Math.max(2, Math.min(token.depth + headingOffset, 6));
      return `<h${level} id="${headingId(token.text)}">${this.parser.parseInline(token.tokens as Tokens.Generic[])}</h${level}>\n`;
    },
    // Raw HTML in a report is shown as text, never interpreted.
    html(token: Tokens.HTML | Tokens.Tag) {
      return escapeHtml(token.text);
    },
  },
});

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const ALLOWED_TAGS = [
  'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'ul', 'ol', 'li', 'strong', 'em', 'del', 'code', 'pre', 'blockquote',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'span',
];
const ALLOWED_ATTR = ['href', 'title', 'align', 'class', 'id'];

export function renderMarkdown(markdown: string, offset = 2): string {
  usedIds = new Map();
  headingOffset = offset;
  const html = parser.parse(markdown) as string;
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#|\/(?!\/))/i,
    RETURN_TRUSTED_TYPE: false,
  });
  return clean;
}

type Block = { kind: 'html'; html: string } | { kind: 'table'; html: string; rows: number };

/** Cut sanitised report HTML into runs of ordinary blocks and the tables that are longer than `limit` body rows. */
export function splitLongTables(html: string, limit: number): Block[] {
  const template = document.createElement('template');
  template.innerHTML = html;
  const blocks: Block[] = [];
  let pending = '';
  const holder = document.createElement('div');
  const serialise = (node: Node): string => {
    holder.replaceChildren(node.cloneNode(true));
    return holder.innerHTML;
  };
  for (const node of Array.from(template.content.childNodes)) {
    if (node instanceof Element && node.tagName === 'TABLE') {
      const rows = node.querySelectorAll('tbody > tr').length;
      if (rows > limit) {
        if (pending.trim()) blocks.push({ kind: 'html', html: pending });
        pending = '';
        blocks.push({ kind: 'table', html: serialise(node), rows });
        continue;
      }
    }
    pending += serialise(node);
  }
  if (pending.trim()) blocks.push({ kind: 'html', html: pending });
  return blocks;
}

/**
 * Report Markdown, parsed with marked and sanitised with DOMPurify before it reaches the page.
 * With `collapseAbove`, a table with more body rows than that is folded behind a native "Show all n rows" toggle.
 */
export function Markdown({
  source,
  collapseAbove,
  headingOffset: offset = 2,
}: {
  source: string;
  collapseAbove?: number;
  headingOffset?: number;
}) {
  const html = useMemo(() => renderMarkdown(source, offset), [source, offset]);
  const blocks = useMemo(() => (collapseAbove === undefined ? [] : splitLongTables(html, collapseAbove)), [html, collapseAbove]);
  // The HTML is sanitised above; nothing else is injected.
  if (!blocks.some((block) => block.kind === 'table')) {
    return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
  }
  return (
    <div className="md">
      {blocks.map((block, index) =>
        block.kind === 'html' ? (
          <div key={index} className="md__chunk" dangerouslySetInnerHTML={{ __html: block.html }} />
        ) : (
          <details key={index} className="md__more">
            <summary>Show all {block.rows} rows</summary>
            <div className="md__chunk" dangerouslySetInnerHTML={{ __html: block.html }} />
          </details>
        ),
      )}
    </div>
  );
}
