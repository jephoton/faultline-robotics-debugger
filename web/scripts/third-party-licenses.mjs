// Writes public/THIRD-PARTY-LICENSES.txt: the licence texts of every package compiled into the bundle and of
// the bundled fonts, so the built app (and a static export of it) carries the notices their licences require.
// Deterministic for a given package-lock.json, so the committed bundle stays reproducible. Run by `npm run build`.
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

// Runtime packages that end up in the JavaScript bundle (dependencies and their runtime dependencies).
const PACKAGES = ['react', 'react-dom', 'scheduler', 'react-router', 'react-router-dom', '@remix-run/router', 'marked', 'dompurify'];

const FONTS = [
  ['Barlow', 'OFL-Barlow.txt'],
  ['Barlow Condensed', 'OFL-Barlow-Condensed.txt'],
  ['DM Mono', 'OFL-DM-Mono.txt'],
];

const rule = '='.repeat(78);
const sections = [];

for (const name of PACKAGES) {
  const dir = join(root, 'node_modules', name);
  const manifest = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
  const files = readdirSync(dir)
    .filter((file) => /^(licen[cs]e|copying)/i.test(file))
    .sort();
  if (files.length === 0) throw new Error(`no licence file found for ${name}`);
  const texts = files.map((file) => readFileSync(join(dir, file), 'utf8').replace(/\r\n/g, '\n').trim());
  sections.push(`${manifest.name} ${manifest.version} (${manifest.license})\n\n${texts.join('\n\n')}`);
}

for (const [family, file] of FONTS) {
  const text = readFileSync(join(root, 'src', 'assets', 'fonts', file), 'utf8').replace(/\r\n/g, '\n').trim();
  sections.push(`${family} font (SIL Open Font License 1.1)\n\n${text}`);
}

const header =
  'Third-party software and fonts included in the Faultline control panel bundle.\n' +
  'Faultline itself is MIT-licensed; these components keep their own licences.';
writeFileSync(join(root, 'public', 'THIRD-PARTY-LICENSES.txt'), `${header}\n\n${rule}\n\n${sections.join(`\n\n${rule}\n\n`)}\n`);
