import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const resolveSrc = (path: string) => fileURLToPath(new URL(path, import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The studio is served at the root of the Delaxis API server, but the
  // GitHub Pages demo lives under /<repo>/ — the workflow sets VITE_BASE_PATH.
  base: process.env.VITE_BASE_PATH ?? '/',
  resolve: {
    alias: {
      // The Pages demo swaps the backend for an in-browser stub. Resolving the
      // switch here rather than branching at runtime guarantees the stub and its
      // fixtures are absent from the bundle the API server serves.
      '#demo': resolveSrc(
        process.env.VITE_DEMO_MODE === 'true' ? './src/demo/index.ts' : './src/demo/stub.ts',
      ),
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    // Generate sourcemaps for debugging
    sourcemap: false,
    // Chunk splitting for better caching
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          xyflow: ['@xyflow/react'],
        }
      }
    }
  },
  server: {
    // Development server settings
    port: 5173,
    // Proxy API requests to backend during development
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // ws is required for /api/v1/voice/ws (live voice) and also makes the
        // pre-existing /api/v1/chat/ws endpoint usable in dev.
        ws: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/d': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
