import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Development only: the Vite server proxies /api to the one FastAPI process.
// Production has no Vite server; FastAPI serves the built files from the same origin.
const backend = process.env.REPAIRSHOP_API ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': { target: backend, changeOrigin: false } } },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
});
