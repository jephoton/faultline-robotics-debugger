import type { Plugin } from 'vite';

// Replaced in the API-client task by a middleware that serves web/src/mocks/.
export function mockApi(): Plugin {
  return { name: 'faultline-mock-api' };
}
