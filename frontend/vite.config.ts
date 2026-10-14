import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The app calls /api/*; FastAPI serves it under /api/v1/*, same as the Vercel rewrite in
    // production (vercel.json). Same origin, so the session cookie just works.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, '/api/v1'),
      },
    },
  },
})
