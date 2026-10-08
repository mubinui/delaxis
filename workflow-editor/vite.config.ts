import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const resolveSrc = (path: string) => fileURLToPath(new URL(path, import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Unit tests live beside the code; e2e/ belongs to Playwright.
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
  },
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
        // Long-lived libraries get their own chunks so a Studio release does
        // not invalidate them. (The old object form produced an empty
        // "vendor" chunk: React was pulled into the main bundle regardless.)
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('/@xyflow/') || id.includes('/d3-')) return 'canvas';
          if (/\/(react|react-dom|scheduler)\//.test(id)) return 'react';
          if (/\/(react-markdown|remark-[^/]+|micromark[^/]*|mdast-[^/]+|hast-[^/]+|unified|unist-[^/]+|vfile[^/]*|property-information|space-separated-tokens|comma-separated-tokens|decode-named-character-reference|character-entities[^/]*|trim-lines|zwitch|bail|devlop|ccount|markdown-table|longest-streak|html-url-attributes|estree-util-is-identifier-name|style-to-js|style-to-object|inline-style-parser|is-plain-obj|trough|extend)\//.test(id)) return 'markdown';
          if (id.includes('/lucide-react/')) return 'icons';
          return 'vendor';
        },
      },
    },
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
