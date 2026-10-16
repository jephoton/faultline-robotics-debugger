import { render, screen } from '@testing-library/react';
import { Markdown, renderMarkdown } from './Markdown';

describe('Markdown', () => {
  it('renders headings (shifted below the page headings), lists, tables and code', () => {
    render(
      <Markdown
        source={'# Title\n\n## Part\n\n- one\n- two\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n`code` and **bold**\n'}
      />,
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Title' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 4, name: 'Part' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('code').tagName).toBe('CODE');
  });

  it('never lets raw HTML, scripts, event handlers or javascript links through', () => {
    const hostile = [
      '<script>window.__pwned = 1</script>',
      '<img src=x onerror="window.__pwned = 2">',
      '<iframe src="https://example.org"></iframe>',
      '[click me](javascript:window.__pwned=3)',
      '[data](data:text/html;base64,PHNjcmlwdD4=)',
      '<a href="https://example.org" onclick="window.__pwned=4">x</a>',
      '<style>body{display:none}</style>',
      '<b>raw bold</b>',
    ].join('\n\n');
    const html = renderMarkdown(hostile);
    const doc = new DOMParser().parseFromString(html, 'text/html');
    expect(doc.querySelectorAll('script, img, iframe, style, b, object, embed, form').length).toBe(0);
    expect(doc.querySelectorAll('[onerror], [onclick], [onload], [style]').length).toBe(0);
    for (const anchor of Array.from(doc.querySelectorAll('a'))) {
      expect(anchor.getAttribute('href') ?? '').not.toMatch(/^(javascript|data):/i);
    }
    // Raw HTML is shown as text, not interpreted.
    expect(doc.body.textContent).toContain('<b>raw bold</b>');
    render(<Markdown source={hostile} />);
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it('keeps ordinary https links', () => {
    expect(renderMarkdown('[docs](https://example.org/docs)')).toContain('href="https://example.org/docs"');
  });
});
