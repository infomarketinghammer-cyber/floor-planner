import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // All API traffic goes through the Express gateway, same as production.
    proxy: {
      '/api': 'http://localhost:4000',
    },
  },
})
