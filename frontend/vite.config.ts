import { defineConfig } from 'vite'
import { devtools } from '@tanstack/devtools-vite'

import { tanstackStart } from '@tanstack/react-start/plugin/vite'
// Nitro turns the Start server bundle into a deployable target. Vercel detects
// it and builds .vercel/output; without it the build only emits dist/client +
// dist/server and Vercel serves nothing from dist/, which returns 404.
import { nitro } from 'nitro/vite'

import viteReact from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const certCandidates = [
  path.resolve(__dirname, '../local-cert.pem'),
  path.resolve(process.cwd(), 'local-cert.pem'),
  path.resolve(__dirname, '../certs/cert.pem'),
  path.resolve(process.cwd(), 'certs/cert.pem'),
]
const certPath = certCandidates.find((p) => fs.existsSync(p))

const keyCandidates = [
  path.resolve(__dirname, '../local-key.pem'),
  path.resolve(process.cwd(), 'local-key.pem'),
  path.resolve(__dirname, '../certs/key.pem'),
  path.resolve(process.cwd(), 'certs/key.pem'),
]
const keyPath = keyCandidates.find((p) => fs.existsSync(p))

const hasHttps = Boolean(certPath && keyPath)
if (hasHttps) {
  console.log(`[Vite HTTPS] Active: loaded certificate from ${certPath}`)
} else {
  console.warn('[Vite HTTPS] Warning: certificates not found, running on HTTP.')
}

const backendTarget = process.env.VITE_BACKEND_HTTPS === 'true'
  ? 'https://127.0.0.1:8000'
  : 'http://127.0.0.1:8000'

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
    port: 3000,
    allowedHosts: true,
    https: hasHttps
      ? {
          cert: fs.readFileSync(certPath!),
          key: fs.readFileSync(keyPath!),
        }
      : undefined,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  preview: {
    host: true,
    port: 3000,
    allowedHosts: true,
    https: hasHttps
      ? {
          cert: fs.readFileSync(certPath!),
          key: fs.readFileSync(keyPath!),
        }
      : undefined,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
}))

export default config
