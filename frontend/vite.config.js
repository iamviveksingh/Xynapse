import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

import { reticle } from '@reticlehq/vite-plugin';
export default defineConfig({
  plugins: [reticle(), react()],
  server: {
    host: '0.0.0.0',
    port: 5175,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/evidence': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true
      }
    }
  }
});
