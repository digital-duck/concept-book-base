// UI strings live in locales/ui.yaml (key → {lang: text}); this module only
// loads them. See docs/DEV/readme-i18n.md.
import ui from '../locales/ui.yaml'
import { appConfig } from './config.js'

const SOURCE = ui._meta?.source || 'en'

// Flatten nested keys to dotted keys: {panel: {generate: {en, zh}}} →
// {'panel.generate': {en, zh}}. A leaf is an object whose values are strings.
function _flatten(node, prefix, out) {
  for (const [k, v] of Object.entries(node)) {
    const key = prefix ? `${prefix}.${k}` : k
    const isLeaf = Object.values(v).every(x => typeof x === 'string')
    if (isLeaf) out[key] = v
    else _flatten(v, key, out)
  }
  return out
}

// Locales whose UI strings are shown, in ui.yaml `_meta.languages` order.
// Unreviewed ones — `machine` (LLM-drafted by scripts/translate_locale.py) and
// `draft` (started by hand on the Manage → i18n tab) — are excluded unless
// appConfig opts in; for such a locale the UI stays in the source language.
const _UNREVIEWED = new Set(['machine', 'draft'])
const strings = {}
export const UI_LOCALES = []

// (Re)build `strings` and UI_LOCALES in place from a parsed ui.yaml — in place
// so importers' references stay valid across a dev hot update (see below).
function _load(data) {
  const { _meta: meta = {}, ...tree } = data
  for (const k of Object.keys(strings)) delete strings[k]
  _flatten(tree, '', strings)
  UI_LOCALES.splice(0, UI_LOCALES.length, ...Object.entries(meta.languages || { en: { name: 'English' } })
    .filter(([, { status }]) => !_UNREVIEWED.has(status) || appConfig.showMachineLocales)
    .map(([code, { name }]) => ({ code, label: name })))
}
_load(ui)

// The locale is any language code, not just a UI locale: the top-bar picker
// also offers content-only languages (books generated in fr, ja, …). For those,
// UI strings fall back to the source language while content, node labels and
// catalog text use the locale wherever they exist.
function _stored() {
  try { return localStorage.getItem('cb-lang') } catch { return null }
}
let _locale = /^[a-z]{2,3}(-[A-Za-z0-9]+)?$/.test(_stored() || '') ? _stored() : SOURCE
document.documentElement.lang = _locale

// The language UI strings come from: the locale if it's a UI locale, else source.
function _uiLang() {
  return UI_LOCALES.some(l => l.code === _locale) ? _locale : SOURCE
}

// t('card.stats', {nodes: 3}) — the current UI language's text, falling back to
// the source language, then the key itself; {name} placeholders filled from vars.
export function t(key, vars) {
  const entry = strings[key]
  const text = entry?.[_uiLang()] ?? entry?.[SOURCE] ?? key
  return vars ? text.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : text
}

// Pick a display label from a {lang: text} map: the current locale, then the
// source language, then any language present, then the fallback (e.g. a node id).
// Same chain as spl/tools.py _label_for, so graph, TOC and generated pages agree.
export function tl(labels, fallback = '') {
  if (labels) {
    const hit = labels[_locale] || labels[SOURCE] || Object.values(labels).find(Boolean)
    if (hit) return hit
  }
  return fallback
}

export function setLocale(lang) {
  if (lang === _locale) return
  _locale = lang
  try { localStorage.setItem('cb-lang', lang) } catch { /* private mode */ }
  document.documentElement.lang = lang
  window.dispatchEvent(new CustomEvent('cb:localeChanged', { detail: { lang } }))
}

export function getLocale() {
  return _locale
}

// A tag's display label, or the tag itself when ui.yaml has no `tag.<name>`.
export function tagLabel(tag) {
  return strings[`tag.${tag}`] ? t(`tag.${tag}`) : tag
}

// Set el's text (or an attribute such as 'title'/'placeholder') to t(key, vars)
// — or, when `key` is a function, to its return value (for data-driven text
// such as catalogText()) — and remember it, so applyI18n() can relabel it in place after a locale
// change — used on pages that update in place instead of re-rendering (the
// domain page keeps its graph iframe and selection across a switch).
export function i18n(el, key, { attr = 'textContent', vars } = {}) {
  const bound = el._i18n || (el._i18n = {})
  bound[attr] = { key, vars }
  el.setAttribute('data-i18n', '')  // an attribute, not a class: callers often reassign className
  _apply(el, attr, key, vars)
  return el
}

function _apply(el, attr, key, vars) {
  const text = typeof key === 'function' ? key() : t(key, vars)
  if (attr === 'textContent') el.textContent = text
  else if (attr === 'innerHTML') el.innerHTML = text
  else el.setAttribute(attr, text)
}

// Bind every element under `root` that declares its key in markup —
// data-t="key" (text), data-t-title, data-t-placeholder — so innerHTML
// templates stay declarative and still relabel in place.
export function bindI18n(root) {
  for (const attr of ['', 'title', 'placeholder']) {
    const data = attr ? `data-t-${attr}` : 'data-t'
    root.querySelectorAll(`[${data}]`).forEach(el =>
      i18n(el, el.getAttribute(data), attr ? { attr } : {}))
  }
  return root
}

export function applyI18n(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    for (const [attr, { key, vars }] of Object.entries(el._i18n || {})) _apply(el, attr, key, vars)
  })
}

// Dev only: take ui.yaml edits (e.g. saved from the Manage → i18n tab) in
// place, instead of Vite's default full-page reload on every save.
if (import.meta.hot) {
  import.meta.hot.accept('../locales/ui.yaml', mod => {
    if (!mod) return
    _load(mod.default)
    applyI18n(document)
  })
}
