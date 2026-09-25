// Renders graph.html in an iframe with its own chrome (learning-path
// sidebar, explanation panel, in-iframe recenter button) suppressed — the
// parent app supplies its own top bar (search + Re-Center) and the Notes
// drawer is relaid out as a resizable pane (not a collapsible one) below
// the graph — while keeping the click → cb:nodeSelected bridge.

import { i18n, t, tl } from '../i18n.js'

export function GraphViewer(domain, { level = 'intro', lang = 'en', signal } = {}) {
  const { id: domainId } = domain

  const el = document.createElement('div')
  el.className = 'cb-graph-viewer'

  // ── Top bar: search (left) + Re-Center (right) ──────────────────────────
  const topBar = document.createElement('div')
  topBar.className = 'cb-graph-topbar'

  const searchWrap = document.createElement('div')
  searchWrap.className = 'cb-graph-topbar__search'
  const searchInput = document.createElement('input')
  searchInput.type = 'text'
  i18n(searchInput, 'graph.search_placeholder', { attr: 'placeholder' })
  searchInput.className = 'cb-graph-topbar__input'
  const searchBtn = document.createElement('button')
  searchBtn.type = 'button'
  i18n(searchBtn, 'graph.search')
  searchBtn.className = 'cb-btn cb-graph-topbar__search-btn'
  searchWrap.append(searchInput, searchBtn)

  const viewControls = document.createElement('div')
  viewControls.className = 'cb-graph-topbar__view-controls'

  const zoomOutBtn = document.createElement('button')
  zoomOutBtn.type = 'button'
  i18n(zoomOutBtn, 'graph.zoom_out')
  i18n(zoomOutBtn, 'graph.zoom_out_title', { attr: 'title' })
  zoomOutBtn.className = 'cb-btn cb-graph-topbar__zoom'

  const zoomInBtn = document.createElement('button')
  zoomInBtn.type = 'button'
  i18n(zoomInBtn, 'graph.zoom_in')
  i18n(zoomInBtn, 'graph.zoom_in_title', { attr: 'title' })
  zoomInBtn.className = 'cb-btn cb-graph-topbar__zoom'

  const recenterBtn = document.createElement('button')
  recenterBtn.type = 'button'
  i18n(recenterBtn, 'graph.recenter')
  recenterBtn.className = 'cb-btn cb-graph-topbar__recenter'

  viewControls.append(zoomOutBtn, zoomInBtn, recenterBtn)
  topBar.append(searchWrap, viewControls)
  el.appendChild(topBar)

  const frame = document.createElement('iframe')
  frame.className = 'cb-graph-viewer__frame'
  frame.src = `${import.meta.env.BASE_URL}domains/${domainId}/output/graph.html`
  i18n(frame, 'graph.frame_title', { attr: 'title', vars: { domain: domainId } })
  frame.setAttribute('allowfullscreen', '')

  function _doSearch() {
    const q = searchInput.value.trim().toLowerCase()
    if (!q) return
    const win = frame.contentWindow
    const nodes = win?.__cb_RAW?.nodes || []
    // Match the id and every language's label, so `肝` and `liver` both work
    // whatever the current locale.
    const match = nodes.find(n =>
      [n.id, n.label, ...Object.values(n.labels || {})].some(s => s.toLowerCase().includes(q)))
    searchInput.classList.remove('cb-graph-topbar__input--notfound')
    if (match) {
      win.selectNode?.(match.id)
      win.__cb_network?.focus?.(match.id, { scale: 1, animation: { duration: 400, easingFunction: 'easeInOutQuad' } })
    } else {
      searchInput.classList.add('cb-graph-topbar__input--notfound')
      setTimeout(() => searchInput.classList.remove('cb-graph-topbar__input--notfound'), 1200)
    }
  }
  searchBtn.addEventListener('click', _doSearch)
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _doSearch() }
  })
  recenterBtn.addEventListener('click', () => {
    try { frame.contentWindow?.reCenterGraph?.() } catch (_) {}
  })
  const _ZOOM_MIN = 0.1
  const _ZOOM_MAX = 4
  function _zoom(factor) {
    try {
      const net = frame.contentWindow?.__cb_network
      if (!net) return
      const scale = Math.min(_ZOOM_MAX, Math.max(_ZOOM_MIN, net.getScale() * factor))
      net.moveTo({
        scale,
        animation: { duration: 150, easingFunction: 'easeInOutQuad' },
      })
    } catch (_) {}
  }
  zoomInBtn.addEventListener('click', () => _zoom(1.25))

  // Relabel graph nodes in the current locale, in place (no iframe reload, so
  // zoom and selection survive). graph.html carries every language in each
  // node's `labels`; nodes without a translation keep their original label.
  // Mutating RAW's node objects also relabels nodeIndex (same objects), so
  // getPath() — and the TOC built from it — sees localized labels too.
  function _relabel() {
    try {
      const win = frame.contentWindow
      const nodes = win?.__cb_RAW?.nodes
      if (!nodes) return
      nodes.forEach(n => {
        n._label0 ??= n.label
        n.label = tl(n.labels, n._label0)
      })
      const wrap = win.wrapLabel || (x => x.replace(/ /g, '\n'))
      // A label update makes vis.js re-run its hierarchical layout, which
      // discards graph.html's compact (tier-grouped) node positions — save
      // and restore them so the graph doesn't jump on a language switch.
      const net = win.__cb_network
      const pos = net?.getPositions()
      win.__cb_visNodes?.update(nodes.map(n => ({ id: n.id, label: wrap(n.label) })))
      if (pos) Object.entries(pos).forEach(([id, { x, y }]) => net.moveNode(id, x, y))

      _localizeNotes(frame.contentDocument, win.__cb_nodeIndex?.[net?.getSelectedNodes?.()[0]])
    } catch (_) { /* graph not loaded yet */ }
  }
  window.addEventListener('cb:localeChanged', _relabel, { signal })
  zoomOutBtn.addEventListener('click', () => _zoom(0.8))

  frame.addEventListener('load', () => {
    try {
      const win = frame.contentWindow
      if (!win) return

      // visNodes is absent from graph.html files rendered before i18n support.
      win.eval('window.__cb_RAW = RAW; window.__cb_nodeIndex = nodeIndex; window.__cb_network = network; ' +
        "window.__cb_visNodes = typeof visNodes !== 'undefined' ? visNodes : null")
      _relabel()

      // ── 1. Broadcast concept list to parent ──
      const concepts = (win.__cb_RAW?.nodes || []).map(n => ({
        id: n.id, label: n.label, kind: n.kind, tier: n.tier ?? 0,
      }))
      window.dispatchEvent(new CustomEvent('cb:graphLoaded', { detail: { concepts } }))

      // ── 2. Patch handleSelect → emit cb:nodeSelected ──
      const _orig = win.handleSelect
      win.handleSelect = function (nodeId) {
        _orig.call(win, nodeId)
        const node = win.__cb_nodeIndex?.[nodeId]
        if (node) {
          window.dispatchEvent(new CustomEvent('cb:nodeSelected', { detail: { nodeId, node } }))
        }
      }

      // ── 3. Hide the learning-path/explanation chrome, relay out Notes ──
      _injectLayout(frame.contentDocument)
    } catch (_) { /* cross-origin safety */ }
  })

  el.appendChild(frame)

  el.selectNode = (nodeId) => {
    try { frame.contentWindow?.selectNode?.(nodeId) } catch (_) {}
  }

  // Returns { nodeId, node, path: [{id,label,kind}, ...] } for the given
  // node, reusing graph.html's own getAncestors()/nodeIndex (same-origin)
  // instead of reimplementing prerequisite-walking in the parent app.
  el.getPath = (nodeId) => {
    try {
      const win = frame.contentWindow
      // graph.html's `nodeIndex` is a top-level `const`, so it's never a
      // property of `contentWindow` — only `window.__cb_nodeIndex` (set via
      // eval above) is reachable from here. `getAncestors` is a top-level
      // `function` declaration, which *does* attach to window, so it's
      // called directly.
      const node = win?.__cb_nodeIndex?.[nodeId]
      if (!node) return null
      const ancestorIds = win.getAncestors ? [...win.getAncestors(nodeId)] : []
      const path = ancestorIds.map(id => win.__cb_nodeIndex[id]).filter(Boolean)
      return { nodeId, node, path }
    } catch (_) { return null }
  }

  return el
}

// graph.html's Notes drawer is static English markup; relabel it from the
// parent (its own JS is untouched). `selected` is the selected node, if any —
// the drawer shows its label.
function _localizeNotes(doc, selected) {
  if (!doc) return
  const q = s => doc.querySelector(s)
  const set = (el, text) => { if (el) el.textContent = text }
  set(q('#notes-header-top h2'), t('graph.notes'))
  set(q('#nb-clear-btn'), t('graph.notes_clear'))
  set(q('#nb-clear-btn + .nb-btn'), t('graph.notes_export'))
  q('#notes-textarea')?.setAttribute('placeholder', t('graph.notes_placeholder'))
  set(q('#notes-node-label'), selected ? selected.label : t('graph.notes_none'))
}

// ── Layout: hide path/explain panels + in-iframe recenter button, split
// graph/Notes as a fixed-by-default-but-resizable 80/20 pane instead of a
// collapsible drawer ──────────────────────────────────────────────────────

function _injectLayout(doc) {
  if (doc.querySelector('#cb-ide-layout')) return

  const style = doc.createElement('style')
  style.id = 'cb-ide-layout'
  style.textContent = `
    #path-sidebar, #explain-panel, .graph-recenter-btn { display: none !important; }
    .app {
      display: flex !important;
      flex-direction: column !important;
      height: 100vh !important;
    }
    #graph-panel { flex: 0 0 80%; min-height: 0; }
    #notes-sidebar {
      flex: 1;
      min-height: 0;
      width: 100% !important;
      border-left: none !important;
      border-top: 1px solid rgba(0,0,0,0.12) !important;
      overflow-y: auto !important;
      display: flex;
      flex-direction: column;
    }
    /* graph.html's own #notes-textarea is a fixed 100px tall, sized for the
       standalone page's roomy right-column layout — inside this bottom
       drawer (now a much shorter horizontal strip) that alone ate most of
       the available height, squeezing the notes history list below it down
       to one or two visible rows. Shrink the entry box to a single line so
       the history list gets the space instead. */
    #notes-textarea {
      flex: 0 0 auto !important;
      height: 32px !important;
      padding: 6px 12px !important;
    }
    .cb-notes-gutter {
      height: 6px; flex-shrink: 0; cursor: row-resize;
      background: rgba(0,0,0,0.1); touch-action: none;
      transition: background 0.15s;
    }
    .cb-notes-gutter:hover, .cb-notes-gutter:active { background: #60a5fa; }
  `
  doc.head.appendChild(style)

  const graphPanel = doc.querySelector('#graph-panel')
  const notesSidebar = doc.querySelector('#notes-sidebar')
  const app = doc.querySelector('.app')
  if (graphPanel && notesSidebar && app && !doc.querySelector('.cb-notes-gutter')) {
    const gutter = doc.createElement('div')
    gutter.className = 'cb-notes-gutter'
    i18n(gutter, 'domain.drag_resize', { attr: 'title' })
    graphPanel.insertAdjacentElement('afterend', gutter)
    _wireVerticalResize(gutter, graphPanel, app)
  }
}

// Drag the gutter to resize the graph/Notes split within the iframe's own
// document — safe to use plain pointer capture here (no cross-document
// concerns) since both panes and the gutter live in the same document.
function _wireVerticalResize(gutter, graphPanel, app) {
  const MIN = 0.3
  const MAX = 0.92

  gutter.addEventListener('pointerdown', (e) => {
    e.preventDefault()
    gutter.setPointerCapture(e.pointerId)

    const onMove = (moveEvent) => {
      const rect = app.getBoundingClientRect()
      const pct = Math.min(MAX, Math.max(MIN, (moveEvent.clientY - rect.top) / rect.height))
      graphPanel.style.flex = `0 0 ${(pct * 100).toFixed(2)}%`
    }
    const onUp = (upEvent) => {
      gutter.releasePointerCapture(upEvent.pointerId)
      gutter.removeEventListener('pointermove', onMove)
      gutter.removeEventListener('pointerup', onUp)
      gutter.removeEventListener('pointercancel', onUp)
    }
    gutter.addEventListener('pointermove', onMove)
    gutter.addEventListener('pointerup', onUp)
    gutter.addEventListener('pointercancel', onUp)
  })
}
