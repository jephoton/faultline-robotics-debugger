import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LONG_TABLE_ROWS, Markdown, renderMarkdown } from './Markdown';

function table(rows: number): string {
  const body = Array.from({ length: rows }, (_, index) => `| ${index} | row ${index} |`).join('\n');
  return `| n | label |\n| - | - |\n${body}\n`;
}

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

  it('gives every heading an anchor id, unique within the report', () => {
    const html = renderMarkdown('# Summary\n\n## Result\n\n## Result\n\n### Minimal `cause` (a/b)\n');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const ids = Array.from(doc.querySelectorAll('h3, h4, h5')).map((heading) => heading.id);
    expect(ids).toEqual(['md-summary', 'md-result', 'md-result-2', 'md-minimal-cause-a-b']);
    // A second document starts again, so the ids do not depend on what was rendered before.
    expect(new DOMParser().parseFromString(renderMarkdown('# Summary'), 'text/html').querySelector('h3')?.id).toBe('md-summary');
  });

  it('folds a table of more than 12 body rows behind a Show all toggle and leaves short ones open', async () => {
    const user = userEvent.setup();
    const source = `# Report\n\nbefore\n\n${table(LONG_TABLE_ROWS + 1)}\nafter\n\n${table(3)}`;
    const { container } = render(<Markdown source={source} collapseAbove={LONG_TABLE_ROWS} />);
    const more = container.querySelector('details.md__more') as HTMLDetailsElement;
    expect(more).not.toBeNull();
    expect(more.open).toBe(false);
    expect(within(more).getByText('Show all 13 rows')).toBeInTheDocument();
    expect(container.querySelectorAll('details')).toHaveLength(1);
    expect(screen.getByText('before')).toBeInTheDocument();
    expect(screen.getByText('after')).toBeInTheDocument();
    // The long table is inside the fold; the short one (3 rows) is outside it.
    expect(more.querySelectorAll('tbody tr')).toHaveLength(13);
    expect(container.querySelectorAll('table')).toHaveLength(2);
    await user.click(screen.getByText('Show all 13 rows'));
    expect(more.open).toBe(true);
  });

  it('does not fold a table of exactly 12 rows, or any table without the option', () => {
    const { container, rerender } = render(<Markdown source={table(LONG_TABLE_ROWS)} collapseAbove={LONG_TABLE_ROWS} />);
    expect(container.querySelector('details')).toBeNull();
    rerender(<Markdown source={table(40)} />);
    expect(container.querySelector('details')).toBeNull();
  });
});
