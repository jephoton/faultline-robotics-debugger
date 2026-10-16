import { createReadStream, existsSync } from 'node:fs';
import { join } from 'node:path';
import type { IncomingMessage } from 'node:http';
import type { Plugin } from 'vite';
import { createMockServer } from './src/mocks/handlers';

/*
 * Dev-only: serves the fixtures in src/mocks/ for /api, /data and /media so the app runs without the
 * Python server.  Start it with `npm run dev:mock`.
 *   VITE_MOCK_STATIC=1  behave like the deployed gallery (no /api; data/*.json only)
 *   VITE_MOCK_ACTIVE=0  start with no active run, so New diagnosis can be walked through
 * Starting a run in the mock never touches anything outside the browser tab.
 */

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  if (chunks.length === 0) return undefined;
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return undefined;
  }
}

export function mockApi(): Plugin {
  const server = createMockServer({
    mode: process.env.VITE_MOCK_STATIC === '1' ? 'static' : 'local',
    activeDemo: process.env.VITE_MOCK_ACTIVE !== '0',
  });
  const mediaDir = join(process.cwd(), 'src', 'mocks', 'media');
  return {
    name: 'faultline-mock-api',
    configureServer(dev) {
      dev.middlewares.use(async (req, res, next) => {
        const url = req.url ?? '/';
        if (url.startsWith('/media/')) {
          const file = join(mediaDir, url.slice('/media/'.length).split('?')[0] as string);
          if (file.startsWith(mediaDir) && existsSync(file)) {
            res.setHeader('Content-Type', 'video/webm');
            createReadStream(file).pipe(res);
            return;
          }
          res.statusCode = 404;
          res.end('Not found');
          return;
        }
        if (!url.startsWith('/api/') && !url.startsWith('/data/')) {
          next();
          return;
        }
        const headers: Record<string, string> = {};
        for (const [key, value] of Object.entries(req.headers)) {
          if (typeof value === 'string') headers[key.toLowerCase()] = value;
        }
        const body = req.method === 'POST' ? await readBody(req) : undefined;
        const result = server.handle({ method: req.method ?? 'GET', url, headers, body });
        if (!result) {
          next();
          return;
        }
        res.statusCode = result.status;
        res.setHeader('Cache-Control', 'no-store');
        if (typeof result.body === 'string') {
          res.setHeader('Content-Type', result.contentType ?? 'text/plain');
          res.end(result.body);
        } else {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(result.body));
        }
      });
    },
  };
}
