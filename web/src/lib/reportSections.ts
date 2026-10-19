/** A stored report cut into the part a team reads first and the rest. */
export interface ReportParts {
  /** The body of the `## Summary` section, without its heading; null when the report has none. */
  summary: string | null;
  /** Every other `## ` section, each with its heading, in report order. The `# ` title is left out. */
  rest: string;
  /** How many `## ` sections are in `rest`. */
  restSections: number;
}

const FENCE = /^\s{0,3}(```|~~~)/;

/** Split a report on its `## ` headings (outside code fences) and pull out the Summary. */
export function splitReport(markdown: string): ReportParts {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const sections: { heading: string | null; lines: string[] }[] = [{ heading: null, lines: [] }];
  let fenced = false;
  for (const line of lines) {
    if (FENCE.test(line)) fenced = !fenced;
    const heading = !fenced ? /^## +(.*?)\s*#*\s*$/.exec(line) : null;
    if (heading) sections.push({ heading: heading[1] as string, lines: [line] });
    else (sections[sections.length - 1] as { lines: string[] }).lines.push(line);
  }
  const [preamble, ...named] = sections as [(typeof sections)[number], ...typeof sections];
  const isSummary = (heading: string | null) => heading !== null && heading.trim().toLowerCase() === 'summary';
  const summarySection = named.find((section) => isSummary(section.heading));
  const summary = summarySection ? summarySection.lines.slice(1).join('\n').trim() : '';

  // Anything in the preamble other than the `# ` title line itself stays with the rest.
  const preambleText = preamble.lines.filter((line) => !/^# /.test(line)).join('\n').trim();
  const others = named.filter((section) => !isSummary(section.heading));
  const rest = [preambleText, ...others.map((section) => section.lines.join('\n').trim())].filter(Boolean).join('\n\n');
  return { summary: summary || null, rest, restSections: others.length };
}
