import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/*
 * WCAG 2.2 AA contrast, measured from the tokens in tokens.css (both themes).
 *   text on surfaces: 4.5:1     control borders and focus ring: 3:1
 * Measured at the time of writing (light / dark), the lowest ratio on the three surfaces:
 *   --text 10.1 / 11.7        --text-2 5.2 / 6.2
 *   --alarm-text 4.8 / 5.3    --attention-text 4.9 / 7.9
 *   white on --alarm-fill 5.9 / 5.9    dark on --attention 8.2 / 8.2
 *   --line-strong 3.2 / 4.4   readout text 12.9, dim text 6.3
 * The 5px sidebar status bars are redundant with the icon and the word beside them, so they are
 * not required to reach 3:1 on their own (the amber bar does not on light grey).
 */

const css = readFileSync(join(process.cwd(), 'src', 'styles', 'tokens.css'), 'utf8');

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`Missing ${selector}`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close);
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[match[1] as string] = (match[2] as string).toLowerCase();
  }
  return out;
}

const light = block(':root {');
const darkMedia = block(":root:not([data-theme='light'])");
const darkAttr = block(":root[data-theme='dark']");

function luminance(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const themes: [string, Record<string, string>][] = [
  ['light', light],
  ['dark (system)', { ...light, ...darkMedia }],
  ['dark (toggle)', { ...light, ...darkAttr }],
];
const surfaces = ['bg-page', 'bg-panel', 'bg-raised'];

describe.each(themes)('contrast, %s theme', (_name, t) => {
  it.each(['text', 'text-2', 'alarm-text', 'attention-text'])('%s reads at 4.5:1 on every surface', (token) => {
    for (const surface of surfaces) {
      expect(ratio(t[token] as string, t[surface] as string), `${token} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('button, alarm and attention fills carry readable text', () => {
    expect(ratio(t['on-button'] as string, t['button-bg'] as string)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t['on-alarm'] as string, t['alarm-fill'] as string)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t['on-attention'] as string, t['attention'] as string)).toBeGreaterThanOrEqual(4.5);
  });

  it('control borders and the focus ring reach 3:1', () => {
    for (const surface of surfaces) {
      expect(ratio(t['line-strong'] as string, t[surface] as string), `border on ${surface}`).toBeGreaterThanOrEqual(3);
      expect(ratio(t['focus'] as string, t[surface] as string), `focus on ${surface}`).toBeGreaterThanOrEqual(3);
    }
  });

  it('the readout panel text reads at 4.5:1', () => {
    expect(ratio(t['readout-text'] as string, t['readout-bg'] as string)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t['readout-dim'] as string, t['readout-bg'] as string)).toBeGreaterThanOrEqual(4.5);
    for (const tone of ['readout-alarm', 'readout-attention', 'readout-neutral']) {
      expect(ratio(t[tone] as string, t['readout-bg'] as string)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

it('the two dark theme blocks (system and toggle) define the same tokens', () => {
  expect(darkAttr).toEqual(darkMedia);
});
