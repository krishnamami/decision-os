import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Fallback proxy for relative /api calls (the client uses VITE_API_URL
    // or http://localhost:8000 directly; CORS is enabled on the backend).
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
