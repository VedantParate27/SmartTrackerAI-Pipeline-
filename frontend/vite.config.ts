import { defineConfig } from 'vite'
import { devtools } from '@tanstack/devtools-vite'

import { tanstackStart } from '@tanstack/react-start/plugin/vite'
// Nitro turns the Start server bundle into a deployable target. Vercel detects
// it and builds .vercel/output; without it the build only emits dist/client +
// dist/server and Vercel serves nothing from dist/, which returns 404.
import { nitro } from 'nitro/vite'

import viteReact from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const config = defineConfig(({ command }) => ({
  resolve: { tsconfigPaths: true },
  plugins: [
    devtools(),
    tailwindcss(),
    tanstackStart(),
    // shortcut: nitro only on build, because in dev it bypasses the /api proxy
    ...(command === 'build' ? [nitro()] : []),
    viteReact(),
  ],
  server: {
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
}))

export default config