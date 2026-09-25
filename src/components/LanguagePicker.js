import { getLocale, setLocale, i18n, UI_LOCALES } from '../i18n.js'

// Languages the backend can *generate* content in — the content panel's
// Language dropdown, and (with any extra UI locales) the top-bar picker.
const CONTENT_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文 (Chinese)' },
  { code: 'es', label: 'Español (Spanish)' },
  { code: 'fr', label: 'Français (French)' },
  { code: 'de', label: 'Deutsch (German)' },
  { code: 'ja', label: '日本語 (Japanese)' },
  { code: 'ko', label: '한국어 (Korean)' },
  { code: 'pt', label: 'Português (Portuguese)' },
  { code: 'ru', label: 'Русский (Russian)' },
  { code: 'ar', label: 'العربية (Arabic)' },
  { code: 'hi', label: 'हिन्दी (Hindi)' },
]

export { CONTENT_LANGUAGES }

// Top-bar picker: every content language (some books are generated in
// languages the UI itself isn't translated into), plus any UI locale not in
// that list. Picking a language without UI strings keeps the UI in English but
// still switches content, node labels and catalog text to that language.
function _pickerLanguages() {
  const extra = UI_LOCALES.filter(u => !CONTENT_LANGUAGES.some(c => c.code === u.code))
  return [...CONTENT_LANGUAGES, ...extra]
}

export function LanguagePicker() {
  const sel = document.createElement('select')
  sel.className = 'cb-lang-picker'
  i18n(sel, 'nav.language', { attr: 'title' })

  const current = getLocale()
  _pickerLanguages().forEach(({ code, label }) => {
    const opt = document.createElement('option')
    opt.value = code
    opt.textContent = label
    if (code === current) opt.selected = true
    sel.appendChild(opt)
  })

  sel.addEventListener('change', () => setLocale(sel.value))

  return sel
}
