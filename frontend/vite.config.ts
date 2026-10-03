import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],
  server: {
    // the RAG backend (backend/server.py); run it from the project folder: python -m uvicorn backend.server:app --port 8000
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
