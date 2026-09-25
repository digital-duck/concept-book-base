import { tl } from '../i18n.js'

let _cache = null

export function clearCatalogCache() {
  _cache = null
}

export async function loadCatalog() {
  if (_cache) return _cache
  const res = await fetch(`${import.meta.env.BASE_URL}domains/catalog.json`)
  if (!res.ok) throw new Error(`Failed to load catalog: ${res.status}`)
  _cache = await res.json()
  return _cache
}

// A catalog entry's `name`/`description` in the current locale. The entry's own
// field is the source-language (en) text; other languages sit under
// `i18n.<lang>.<field>` (written from locales/content.yaml by the build).
export function catalogText(entry, field) {
  const byLang = { en: entry?.[field] }
  for (const [lang, fields] of Object.entries(entry?.i18n || {})) {
    if (fields?.[field]) byLang[lang] = fields[field]
  }
  return tl(byLang, entry?.[field] || entry?.id || '')
}
