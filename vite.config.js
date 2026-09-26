import { defineConfig } from 'vite'
import yaml from '@rollup/plugin-yaml'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

// GitHub Pages serves each repo at https://<org>.github.io/<repo-name>/, so
// `base` must equal the repo's own folder name. Deriving it from this file's
// own directory (not cwd) makes it correct for any clone automatically —
// forks never need to remember to edit this, unlike a hardcoded string that
// silently keeps the template's name (see scripts/init-app.sh, which fixes
// the one thing that CAN'T be auto-derived: package.json's "name" field).
const repoName = path.basename(path.dirname(fileURLToPath(import.meta.url)))

function readDotEnv() {
  try {
    const env = {}
    fs.readFileSync(new URL('.env', import.meta.url).pathname, 'utf8')
      .split('\n')
      .filter(l => l.trim() && !l.startsWith('#'))
      .map(l => l.split('=', 2))
      .filter(p => p.length === 2)
      .forEach(([k, v]) => {
        // expand ${VAR} references using already-seen keys, then process.env as fallback
        env[k.trim()] = v.trim().replace(/\$\{(\w+)\}/g, (_, name) => env[name] ?? process.env[name] ?? '')
      })
    return env
  } catch { return {} }
}

const localEnv = readDotEnv()
const API_PORT = localEnv.API_PORT || process.env.API_PORT || '8200'
const DEV_PORT = parseInt(localEnv.DEV_PORT || process.env.DEV_PORT || '5173', 10)

export default defineConfig({
  base: `/${repoName}/`,
  // locales/*.yaml → bundled JS objects (see src/i18n.js)
  plugins: [yaml()],
  server: {
    port: DEV_PORT,
    proxy: {
      '/api': `http://localhost:${API_PORT}`,
    },
  },
})
