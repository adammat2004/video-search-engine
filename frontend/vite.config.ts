import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend runs on :8000; everything except the UI itself is proxied to it.
const backend = process.env.VBS_BACKEND ?? 'http://127.0.0.1:8000'  // override to run a second (test) stack

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/search': backend,
      '/video': backend,
      '/thumb': backend,
      '/dres': backend,
    },
  },
})
