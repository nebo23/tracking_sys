/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const here = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

// The development server keeps the address the API already trusts (docs/engineering/authentication.md).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': here('./src'),
      // The reference styles and brand files stay in docs/design, their single source.
      '@design': here('../docs/design'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    fs: { allow: [here('..')] },
  },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: { target: 'es2022', sourcemap: false },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/unit/setup.ts'],
    css: false,
    restoreMocks: true,
    unstubGlobals: true,
  },
});
