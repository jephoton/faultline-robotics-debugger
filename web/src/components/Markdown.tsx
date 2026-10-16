import DOMPurify from 'dompurify';
import { Marked, type Tokens } from 'marked';
import { useMemo } from 'react';

// Report headings start at h3 so the page keeps one h1 and the section h2s.
const parser = new Marked({
  gfm: true,
  breaks: false,
  async: false,
  renderer: {
    heading(this: { parser: { parseInline: (tokens: Tokens.Generic[]) => string } }, token: Tokens.Heading) {
      const level = Math.min(token.depth + 2, 6);
      return `<h${level}>${this.parser.parseInline(token.tokens as Tokens.Generic[])}</h${level}>\n`;
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
  'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'ul', 'ol', 'li', 'strong', 'em', 'del', 'code', 'pre', 'blockquote',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'span',
];
const ALLOWED_ATTR = ['href', 'title', 'align', 'class'];

export function renderMarkdown(markdown: string): string {
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

/** Report Markdown, parsed with marked and sanitised with DOMPurify before it reaches the page. */
export function Markdown({ source }: { source: string }) {
  const html = useMemo(() => renderMarkdown(source), [source]);
  // The HTML is sanitised above; nothing else is injected.
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
