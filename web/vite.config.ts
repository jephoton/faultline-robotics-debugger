/// <reference types="vitest" />
import { defineConfig, type PluginOption } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// The production build is written into the Python package and committed, so
// `pip install` needs no Node. CI rebuilds it and fails when it differs.
const OUT_DIR = fileURLToPath(new URL('../src/robot_debug/viewer/app', import.meta.url));

export default defineConfig(async ({ command }) => {
  const plugins: PluginOption[] = [react()];
  if (command === 'serve' && process.env.VITE_MOCK === '1') {
    // Serves fixtures for /api and /media so the app runs without the Python server.
    const { mockApi } = await import('./mock-plugin');
    plugins.push(mockApi());
  }
  return {
    base: '/',
    plugins,
    build: {
      outDir: OUT_DIR,
      emptyOutDir: true,
      assetsDir: 'assets',
      sourcemap: false,
      // Fonts stay as files (hashed, cached immutably); nothing is inlined as a data URI.
      assetsInlineLimit: 0,
    },
    server: {
      port: 5173,
      proxy:
        process.env.VITE_MOCK === '1'
          ? undefined
          : {
              '/api': 'http://127.0.0.1:8765',
              '/media': 'http://127.0.0.1:8765',
            },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  };
});
