import { CONTENT_LANGUAGES } from './LanguagePicker.js'
import { conceptUrl, parseLevelLangModel } from '../lib/paths.js'
import { checkExists, clearExistsCache } from '../lib/contentExists.js'
import { loadCatalog, clearCatalogCache } from '../data/catalog.js'
import { getLocale, i18n, t } from '../i18n.js'

const LEVELS = ['intro', 'core', 'college', 'research']

// TOC entry prefix by node kind — applications (🌸 capstone/payoff targets)
// and primitives (🌱 indivisible, foundational — assumed background
// knowledge) are the minority worth flagging; plain concept nodes (the
// majority) get no tag.
const _TOC_KIND_TAG = {
  application: '🌸',
  primitive: '🌱',
}

const MODELS = [
  { value: 'gemma3', label: 'gemma3 (Ollama)' },
  { value: 'gemma4', label: 'gemma4 (Ollama)' },
  { value: 'sonnet', label: 'sonnet (Claude)' },
  { value: 'haiku', label: 'haiku (Claude)' },
  { value: 'opus', label: 'opus (Claude)' },
]

function makeSelect(options, current, cls, titleKey) {
  const sel = document.createElement('select')
  sel.className = cls
  if (titleKey) i18n(sel, titleKey, { attr: 'title' })
  options.forEach(({ value, label }) => {
    const opt = document.createElement('option')
    opt.value = value
    opt.textContent = label
    if (value === current) opt.selected = true
    sel.appendChild(opt)
  })
  return sel
}

// Catalog's generated_concepts entries only carry {name, label, file, model} —
// level/lang live inside the file path — so index them by node id with
// level/lang/model parsed out, for a same-node/level/lang lookup that isn't
// pinned to whichever model happens to be selected in the UI right now.
function _fillConceptIndex(index, domain) {
  index.clear()
  ;(domain.generated_concepts || []).forEach(c => {
    if (!c.name || !c.file) return
    const { level, lang, model } = parseLevelLangModel(c.file)
    const list = index.get(c.name) || []
    list.push({ file: c.file, level, lang, model: c.model ?? model })
    index.set(c.name, list)
  })
}

// A language's name inside a UI sentence ("Chinese" / "中文"), falling back to
// the content-language dropdown's label for languages ui.yaml doesn't name.
function _langName(code) {
  const name = t(`langname.${code}`)
  return name !== `langname.${code}` ? name : (CONTENT_LANGUAGES.find(l => l.code === code)?.label || code)
}

export function ContentPanel(domain, { level = 'intro', lang = 'en', graphViewer, signal } = {}) {
  const el = document.createElement('aside')
  el.className = 'cb-content-panel'

  const conceptIndex = new Map()
  _fillConceptIndex(conceptIndex, domain)
  // 'sonnet' matches api/config.py's default_model — the dropdown always
  // reflects a real, generatable model, never an empty '' that displays as
  // "— default —" but isn't a value the backend/catalog actually recognizes.
  const state = { model: 'sonnet', level, lang }
  // anchorNode: the node clicked in the *graph* — defines the TOC's scope
  // (its prerequisite path) and stays fixed while browsing the TOC.
  // displayNode: whichever node's content is currently shown — starts equal
  // to the anchor, but moves independently as the user clicks TOC entries,
  // without recomputing the TOC itself.
  let anchorNodeId = null
  let anchorNode = null
  let displayNodeId = null
  let displayNode = null
  // Bumped on every resolveContent() call; a call whose token no longer
  // matches after its await(s) return was superseded by a newer selection
  // and must not touch the DOM — otherwise a slow lookup for a node the user
  // has since clicked away from can resolve after the fast one and clobber
  // the currently-displayed (correct) content with stale content.
  let _resolveToken = 0
  // True once the user has explicitly changed the Model select — from then
  // on, findCatalogEntry() stops silently substituting whatever model *is*
  // generated in place of the one requested (see modelSel's listener below).
  let modelPinned = false

  // Language actually displayed — differs from state.lang when the requested
  // language isn't generated and resolveContent() fell back (see below).
  let shownLang = state.lang
  let shownModel = state.model

  // Finds a catalog-known file for this node at the current level and the
  // given language (default: the selected one), preferring an entry matching
  // the selected model, else a model-less one, else whatever's first —
  // mirrors GraphViewer's old _buildConceptUrlMap preference order. Returns
  // null if nothing at this level/lang is known.
  function findCatalogEntry(nodeId, lang = state.lang) {
    const candidates = (conceptIndex.get(nodeId) || [])
      .filter(e => e.level === state.level && e.lang === lang)
    if (!candidates.length) return null
    const exact = candidates.find(e => e.model === state.model)
    // Once the user has explicitly picked a model, respect it even when
    // nothing's been generated under it yet — falling back to whatever
    // *is* generated (below) would silently snap the dropdown back and
    // make it look like the selection had no effect (see resolveContent()).
    if (exact || modelPinned) return exact || null
    return candidates.find(e => !e.model) || candidates[0]
  }

  // ── Controls row ─────────────────────────────────────────────────────────
  const controls = document.createElement('div')
  controls.className = 'cb-book-pane__controls'

  const modelSel = makeSelect(MODELS, state.model, 'cb-book-pane__select', 'panel.model')
  const levelSel = makeSelect(LEVELS.map(v => ({ value: v, label: v })), state.level, 'cb-book-pane__select', 'panel.level')
  levelSel.querySelectorAll('option').forEach(o => i18n(o, `level.${o.value}`))
  const langSel = makeSelect(CONTENT_LANGUAGES.map(l => ({ value: l.code, label: l.label })), state.lang, 'cb-book-pane__select', 'panel.language')

  const refreshBtn = document.createElement('button')
  refreshBtn.type = 'button'
  refreshBtn.className = 'cb-book-pane__refresh'
  i18n(refreshBtn, 'panel.refresh', { attr: 'title' })
  refreshBtn.textContent = '🔄'

  const genBtn = document.createElement('button')
  genBtn.type = 'button'
  genBtn.className = 'cb-btn cb-btn--primary cb-ide-gen-btn'
  i18n(genBtn, 'panel.generate')
  genBtn.disabled = true

  const pdfBtn = document.createElement('button')
  pdfBtn.type = 'button'
  pdfBtn.className = 'cb-btn cb-ide-pdf-btn'
  i18n(pdfBtn, 'panel.export_pdf')
  pdfBtn.disabled = true

  const skipCacheLbl = document.createElement('label')
  skipCacheLbl.className = 'cb-ide-skip-cache'
  const skipCacheChk = document.createElement('input')
  skipCacheChk.type = 'checkbox'
  skipCacheLbl.appendChild(skipCacheChk)
  skipCacheLbl.appendChild(i18n(document.createElement('span'), 'panel.skip_cache'))

  controls.append(modelSel, levelSel, langSel, refreshBtn, genBtn, skipCacheLbl, pdfBtn)
  el.appendChild(controls)

  // ── Body row: TOC + content ─────────────────────────────────────────────
  const body = document.createElement('div')
  body.className = 'cb-ide-body'

  const toc = document.createElement('nav')
  toc.className = 'cb-ide-toc'
  toc.innerHTML = `<p class="cb-panel__hint">${t('panel.hint_click')}</p>`

  const contentArea = document.createElement('div')
  contentArea.className = 'cb-ide-content'
  contentArea.innerHTML = `<p class="cb-panel__hint">${t('panel.hint_click')}</p>`

  body.append(toc, contentArea)
  el.appendChild(body)

  // ── Generate log panel ───────────────────────────────────────────────────
  const logWrap = document.createElement('div')
  logWrap.className = 'cb-ide-log-wrap'
  logWrap.style.display = 'none'
  const log = document.createElement('pre')
  log.className = 'cb-ide-log'
  const copyLogBtn = document.createElement('button')
  copyLogBtn.type = 'button'
  copyLogBtn.className = 'cb-ide-log-copy'
  i18n(copyLogBtn, 'panel.copy')
  copyLogBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(log.textContent).then(() => {
      i18n(copyLogBtn, 'panel.copied')
      setTimeout(() => { i18n(copyLogBtn, 'panel.copy') }, 1500)
    })
  })
  logWrap.append(log, copyLogBtn)
  el.appendChild(logWrap)

  // ── State sync ───────────────────────────────────────────────────────────
  function onControlsChange() {
    state.model = modelSel.value
    state.level = levelSel.value
    state.lang = langSel.value
    resolveContent()
  }
  modelSel.addEventListener('change', () => { modelPinned = true; onControlsChange() })
  levelSel.addEventListener('change', onControlsChange)
  langSel.addEventListener('change', onControlsChange)
  refreshBtn.addEventListener('click', () => { clearExistsCache(); resolveContent() })

  // The top-bar language overwrites the content language; the Language
  // dropdown can still override it afterwards (e.g. compare EN vs ZH) until
  // the next top-bar change. GraphViewer's listener (registered first) has
  // already relabeled the nodes, so the TOC re-renders with the new labels.
  window.addEventListener('cb:localeChanged', e => {
    const { lang } = e.detail
    if (CONTENT_LANGUAGES.some(l => l.code === lang)) {
      langSel.value = lang
      state.lang = lang
    }
    renderToc(anchorNode)
    resolveContent()
  }, { signal })

  // ── TOC ──────────────────────────────────────────────────────────────────
  // Rebuilt only when the *anchor* (graph-clicked) node changes — clicking
  // an entry inside the TOC never recomputes it, it only changes which
  // node's content is displayed (see the click handler below).
  function renderToc(anchorNode) {
    if (!anchorNodeId) {
      toc.innerHTML = `<p class="cb-panel__hint">${t('panel.hint_click')}</p>`
      return
    }
    const pathInfo = graphViewer?.getPath?.(anchorNodeId)
    const candidates = [...(pathInfo?.path || []), anchorNode].filter(Boolean)
    const seen = new Set()
    const entries = candidates
      .filter(n => !seen.has(n.id) && seen.add(n.id))
      .sort((a, b) => a.label.localeCompare(b.label, getLocale()))

    if (!entries.length) {
      toc.innerHTML = `<p class="cb-panel__hint">${t('panel.no_path')}</p>`
      return
    }

    toc.innerHTML = ''
    const list = document.createElement('ul')
    list.className = 'cb-ide-toc__list'
    entries.forEach(n => {
      const li = document.createElement('li')
      const a = document.createElement('a')
      a.href = '#'
      // Tag only the minority kinds — application (the capstone/payoff
      // target) and primitive (assumed background/foundational knowledge)
      // — since plain concept nodes are the majority and a tag on every
      // entry would just be visual noise.
      const tag = _TOC_KIND_TAG[n.kind]
      a.textContent = tag ? `${tag} ${n.label}` : n.label
      a.dataset.nodeId = n.id
      if (n.id === displayNodeId) a.className = 'cb-ide-toc__current'
      a.addEventListener('click', (e) => {
        e.preventDefault()
        displayNodeId = n.id
        displayNode = n
        logWrap.style.display = 'none'
        _highlightTocCurrent()
        resolveContent()
      })
      li.appendChild(a)
      list.appendChild(li)
    })
    toc.appendChild(list)
  }

  function _highlightTocCurrent() {
    toc.querySelectorAll('.cb-ide-toc__list a').forEach(a => {
      a.classList.toggle('cb-ide-toc__current', a.dataset.nodeId === displayNodeId)
    })
  }

  // ── Content resolution ───────────────────────────────────────────────────
  // Primitives get the same full generate/display treatment as concepts and
  // applications — the backend's write_section() is kind-agnostic and
  // already produces a full section (definition/worked example/theorem/lab
  // cell) for a primitive target (e.g. "atom"), it's just that primitives
  // are usually only *seen* as someone else's prerequisite. Clicking one
  // directly used to show only its one-line `defines` blurb with Generate
  // disabled, even though the backend could always generate real content
  // for it — that was a frontend-only restriction, not a backend one.
  // Finds a displayable page for the current node in `lang`: the catalog's
  // record first (it knows the exact model a file was generated with, so a
  // node generated only under e.g. "sonnet" is found whatever the Model
  // dropdown says), else the conventional path (content generated this
  // session, not yet in catalog.json). Returns {url, model} or null.
  async function locate(lang) {
    const known = findCatalogEntry(displayNodeId, lang)
    if (known) return { url: `${import.meta.env.BASE_URL}domains/${domain.id}/${known.file}`, model: known.model }
    const url = conceptUrl(domain.id, state.level, lang, state.model, displayNodeId)
    return (await checkExists(url)) ? { url, model: state.model } : null
  }

  // Resolves content in the requested language, else falls back to English,
  // else to any language this node has at this level — and *shows* the
  // fallback (with a notice) rather than an empty state. The Language
  // dropdown keeps the requested language, so Generate still targets it.
  async function resolveContent() {
    if (!displayNodeId || !displayNode) return
    const token = ++_resolveToken

    contentArea.innerHTML = `<p class="cb-panel__hint">${t('loading')}</p>`

    const otherLangs = (conceptIndex.get(displayNodeId) || [])
      .filter(e => e.level === state.level).map(e => e.lang)
    const order = [...new Set([state.lang, 'en', ...otherLangs])]
    let found = null
    let lang = null
    for (lang of order) {
      found = await locate(lang)
      if (token !== _resolveToken) return
      if (found) break
    }

    genBtn.disabled = false
    i18n(genBtn, 'panel.generate')

    if (found) {
      shownLang = lang
      shownModel = found.model || state.model
      // Only auto-follow the catalog's model for the requested language, and
      // only when the user hasn't pinned one — see findCatalogEntry()/modelPinned.
      if (lang === state.lang && !modelPinned && found.model && found.model !== state.model) {
        state.model = found.model
        modelSel.value = found.model
      }
      pdfBtn.disabled = false
      contentArea.innerHTML = ''
      if (lang !== state.lang) {
        const notice = document.createElement('div')
        notice.className = 'cb-ide-fallback-notice'
        const text = document.createElement('span')
        text.textContent = t('panel.fallback_notice', { requested: _langName(state.lang), shown: _langName(lang) })
        const btn = document.createElement('button')
        btn.type = 'button'
        btn.className = 'cb-btn cb-ide-fallback-notice__gen'
        btn.textContent = t('panel.generate_in', { lang: _langName(state.lang) })
        btn.addEventListener('click', () => genBtn.click())
        notice.append(text, btn)
        contentArea.appendChild(notice)
      }
      const iframe = document.createElement('iframe')
      iframe.className = 'cb-ide-content__frame'
      iframe.src = found.url
      // Generated pages ship their own `nav.toc` sidebar (a "← back to
      // domain" link + a per-page chapter TOC) baked into the static HTML
      // by spl/tools.py — useful when opening a page standalone, but pure
      // duplication here since our own TOC (left of this iframe) already
      // covers the same ground, plus it's not same-origin-in-purpose (its
      // "back" link and page-local anchors don't match this app's routing).
      // Same-origin, so we can reach in and hide it once the page loads.
      iframe.addEventListener('load', () => {
        try {
          const doc = iframe.contentDocument
          if (!doc) return
          const style = doc.createElement('style')
          style.textContent = 'nav.toc{display:none!important} .page{display:block!important}'
          doc.head.appendChild(style)
        } catch (_) { /* cross-origin or not yet ready — leave as-is */ }
      })
      contentArea.appendChild(iframe)
    } else {
      shownLang = state.lang
      pdfBtn.disabled = true
      contentArea.innerHTML = `
        <div class="cb-ide-empty">
          <h3>${displayNode.label}</h3>
          ${displayNode.defines ? `<p>${displayNode.defines}</p>` : ''}
          <p>${t('panel.missing', { model: state.model, level: state.level, lang: state.lang })}</p>
        </div>
      `
    }
  }

  // ── Generate (SSE) ───────────────────────────────────────────────────────
  genBtn.addEventListener('click', () => {
    if (!displayNodeId) return
    const target = displayNodeId
    const model = state.model
    const lvl = state.level
    const lng = state.lang
    const skipCache = skipCacheChk.checked

    genBtn.disabled = true
    i18n(genBtn, 'panel.generating')
    logWrap.style.display = 'block'
    log.textContent = `▶ target: ${target}  model: ${model || 'default'}  level: ${lvl}  language: ${lng}\n`

    const url = `/api/generate?domain=${encodeURIComponent(domain.id)}&target=${encodeURIComponent(target)}&level=${encodeURIComponent(lvl)}&language=${encodeURIComponent(lng)}&model=${encodeURIComponent(model)}${skipCache ? '&skip_cache=true' : ''}`
    const es = new EventSource(url)

    es.addEventListener('log', e => {
      const { message } = JSON.parse(e.data)
      log.textContent += message + '\n'
      log.scrollTop = log.scrollHeight
    })

    es.addEventListener('done', async () => {
      es.close()
      log.textContent += '\n' + t('panel.log_done')
      clearExistsCache()
      genBtn.disabled = false
      i18n(genBtn, 'panel.generate')
      // The catalog snapshot this panel was built with predates whatever
      // was just generated — without refreshing it, findCatalogEntry()
      // can't see the new file and resolveContent() falls back to guessing
      // a path, which used to be flat-out wrong for non-English content
      // (see lib/paths.js's language-suffix fix) and even once correct is
      // one extra round-trip checkExists() has to make instead of just
      // knowing. Re-pull the catalog and rebuild the index in place so the
      // fast, catalog-known path works immediately, same as for content
      // that was already generated when the page first loaded.
      try {
        clearCatalogCache()
        const fresh = (await loadCatalog()).find(d => d.id === domain.id)
        if (fresh) {
          domain.generated_concepts = fresh.generated_concepts
          domain.books = fresh.books
          domain.has_book = fresh.has_book
          _fillConceptIndex(conceptIndex, domain)
        }
      } catch (_) { /* stale index is a soft failure — checkExists() fallback still applies */ }
      resolveContent()
    })

    es.addEventListener('gen_error', e => {
      es.close()
      log.textContent += `\n✗ ${JSON.parse(e.data).message}`
      genBtn.disabled = false
      i18n(genBtn, 'panel.retry')
    })

    es.onerror = () => {
      // Always treat this as terminal — EventSource auto-reconnects by
      // default, and if the backend died mid-stream (e.g. crashed before
      // sending a gen_error event), that retry loop runs silently forever
      // and leaves the button stuck on "Generating…" with no feedback.
      es.close()
      log.textContent += '\n' + t('panel.log_dropped')
      genBtn.disabled = false
      i18n(genBtn, 'panel.retry')
    }
  })

  // ── Export PDF ───────────────────────────────────────────────────────────
  pdfBtn.addEventListener('click', async () => {
    if (!displayNodeId) return
    const target = displayNodeId
    pdfBtn.disabled = true
    i18n(pdfBtn, 'panel.exporting')

    try {
      const url = `/api/pdf?domain=${encodeURIComponent(domain.id)}&target=${encodeURIComponent(target)}&level=${encodeURIComponent(state.level)}&language=${encodeURIComponent(shownLang)}&model=${encodeURIComponent(shownModel)}`
      const res = await fetch(url)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'PDF generation failed')

      const pdfUrl = `${import.meta.env.BASE_URL}domains/${domain.id}/${data.file}`
      i18n(pdfBtn, 'panel.exported')
      pdfBtn.disabled = false
      window.open(pdfUrl, '_blank', 'noopener')
    } catch (err) {
      i18n(pdfBtn, 'panel.export_error')
      pdfBtn.title = err.message
      setTimeout(() => { i18n(pdfBtn, 'panel.export_pdf'); pdfBtn.disabled = false }, 3000)
    }
  })

  // ── Node selection (from the graph) ─────────────────────────────────────
  // A real graph click re-anchors the TOC to this node's own prerequisite
  // path *and* displays this node's content. Clicking within the TOC
  // afterwards (see renderToc's click handler) only ever changes what's
  // displayed, never re-anchors.
  window.addEventListener('cb:nodeSelected', e => {
    anchorNodeId = e.detail.nodeId
    anchorNode = e.detail.node
    displayNodeId = e.detail.nodeId
    displayNode = e.detail.node
    logWrap.style.display = 'none'
    renderToc(e.detail.node)
    resolveContent()
  }, { signal })

  return el
}
