# i18n: localizing the ConceptBook UI, graph and TOC

**Status:** All five phases implemented (2026-09-25), prototyped here and ported to concept-book-base and conceptbook-app. D1 and D3 confirmed by review.

**Done so far:**
- **Phase 2:** `concept_graph.py` keeps `labels` and emits them into `graph.html`, with a
  `wrapLabel()` that handles CJK; all 9 `graph.html` files are re-rendered. `GraphViewer` relabels
  nodes in place on `cb:localeChanged` (no iframe reload) and searches all languages; its
  toolbar is localized. graph.html files rendered before this change still load, just without
  relabeling.
- **Phase 1:**
  - `locales/ui.yaml` plus `@rollup/plugin-yaml`, and a rewritten `i18n.js` (`t` with `{vars}`,
    `tl`, `i18n()`/`applyI18n()` in-place binding, `UI_LOCALES` from `_meta.languages`).
  - `cb:localeChanged` handling in `main.js`: the domain page relabels in place, other pages
    re-render (`router.refresh()`).
  - Localized: Header, Home filters, DomainCard, and the domain page's picker bar and source
    line.
  - `spl/tools.py` reads `book.*` from `ui.yaml`.
- **Verified:** headless Playwright on `#/domain/meta_health_ch01`. en→zh relabels header,
  toolbar and graph (`blood_xue` → 血); `liver` finds 肝脾关系 in zh; the zoom level is kept; Home
  re-renders both ways; no console errors.
- **Phase 3:**
  - All `ContentPanel` strings are in `ui.yaml` (`panel.*`, `level.*`, `langname.*`).
  - The top-bar language overwrites the panel's Language dropdown and re-resolves content; the
    dropdown can still override it afterwards.
  - The TOC relabels and re-sorts in place (`localeCompare` with the locale, so zh is in pinyin
    order).
  - Content resolves in order: the requested language, then `en`, then any language generated
    for that node. A fallback page is shown automatically under a notice ("日文版尚未生成，正在显示英文版
    [生成日文版]", i.e. "Japanese not yet generated, showing English [Generate Japanese]"), and
    Export PDF exports the language actually shown.
  - Initial content language is the UI locale again.
  - Also: relabeling now saves and restores node positions. A vis.js label update re-runs the
    hierarchical layout and threw away graph.html's compact layout, so the graph jumped. The
    Notes drawer's strings and selected-node label are localized from the parent.
- **Verified (Phase 3):** Playwright, 7 scenarios with no console errors:
  1. EN
  2. top bar → zh
  3. panel override → en
  4. panel → ja (EN fallback with a zh notice)
  5. top bar → en
  6. panel → ja (English notice)
  7. `research` level (the "missing" message in every language)
- **Phase 4:**
  - `locales/content.yaml` has chapter `name`/`description` (en + zh) for 9 domains and the 168
    concept labels. `docs/gemini/concept_labels.yaml` moved here and was removed.
  - `build_graphs_v1.py` reads the file. It writes `graph.yaml` labels (byte-identical output) and
    catalog `name`/`description` (en) plus `i18n.zh`.
  - English chapter names drop the redundant "元健康 Meta-Health " prefix; the app title already
    says it.
  - `catalogText()` drives the Home cards, domain picker and breadcrumb; `tagLabel()` and `tag.*`
    keys in `ui.yaml` translate tags.
  - About's body is `about.body.{en,zh}` HTML in `ui.yaml` (it also fixes the stale "left sidebar
    learning path" line).
  - Settings is fully keyed (`settings.*`) via the new declarative `data-t`/`bindI18n()`, and
    relabels in place so unsaved input survives.
- **Verified (Phase 4):** Playwright checks of Home, the ch04 breadcrumb/picker, About and Settings
  (a typed API key survived the switch), en↔zh, no console errors. The Phase 3 suite still
  passes.
- **Phase 5, tooling:**
  - `scripts/check_i18n.py`:
    - **Errors:** undefined keys used in `src/`, placeholder mismatches, a leaf missing the
      source language, non-string keys (`no:` → `False`), unquoted `{…}` values, and YAML parse
      errors (reported with the line number).
    - **Warnings:** missing translations, and `content.yaml` out of sync with
      `graph.yaml`/`catalog.json`. Domains or catalog entries with *no* translations at all are
      summarized in one line.
    - Verified by injecting each failure.
  - `scripts/translate_locale.py --file ui|content --lang xx [--name …]`:
    - LLM-drafts missing keys (`claude` CLI by default, or the Anthropic SDK), sending the source
      text, other languages and, for concepts, `defines` as context.
    - Validates placeholders, then writes in place with ruamel. Both locale files round-trip
      byte-identically, so the diff is one `xx:` line per key.
    - Registers the language with `status: machine`; `i18n.js` hides machine locales from the
      picker unless `appConfig.showMachineLocales` is set.
    - Trial runs into scratch copies (`card.*`, `about.body`, 4 concept labels → ja) produced
      correct diffs; nothing was committed to the real files.
  - `scripts/apply_content_locale.py`, the generic replacement for `build_graphs_v1.py`'s
    label and chapter-name merge:
    - Makes **line-level** edits of only the `labels:` blocks (ruamel supplies positions),
      because re-dumping would reformat `defines` wrapping in most existing graph files.
    - Stress test: 798 `graph.yaml` files across all local repos, 22,195 nodes relabeled
      (replace + insert), 0 changes outside `labels:`.
    - Catalog writes go through `catalog_lock.update_catalog()`. `--dry-run` supported.
  - The scripts find `graph.yaml` recursively, which also covers conceptbook-app's
    `public/domains/<publisher>/<id>/` layout.
- **Phase 5, port:**
  - **concept-book-base:** the frontend and scripts copied directly (its code matched this repo's
    pre-i18n code). It keeps its own defaults (gemma4 model, `intro` level) and branding
    (ConceptBook / 概念书), has an empty `tag` block, and ships a documented starter
    `content.yaml`. Verified: build, `check_i18n` clean, browser smoke test en↔zh.
  - **conceptbook-app:** a targeted merge (heavily diverged):
    - Shared `i18n.js`, `LanguagePicker`, `router`, `config`, `DomainCard` and scripts.
    - Hand-merged `main.js` (in-place relabel for the domain page plus Settings, Manage,
      Profile and Login), `Header` (Sign in/out), `Domain.js`, `catalog.js`, `GraphViewer`
      (PDF button, Save-button notes drawer, position-preserving relabel) and `ContentPanel`
      (fallback resolution merged with its pending-book, publisher and feedback-bar logic).
    - `spl/tools.py` and `concept_graph.py` updated too.
    - Verified live on `linalg`: en↔zh shell, zh content, `eigen` search, ja → EN fallback
      notice, no console errors.
- **Follow-ups (not blocking):**
  - conceptbook-app: Manage, Profile, Login, the chat panel and the content panel's
    gating/editor messages are still English literals. Its own Home, About and Settings aren't
    keyed yet, so 34 base keys show as unused there.
  - conceptbook-app: none of its 177 domains have labels or zh chapter text yet
    (`translate_locale.py --file content` + `apply_content_locale.py` would do it).
  - conceptbook-app's **running dev server needs a restart**. It reloaded `vite.config.js`
    before `@rollup/plugin-yaml` was installed, so it 500s on `locales/ui.yaml` until
    restarted.
  - `app.tagline` is defined but not shown anywhere.
  - graph.html's own "Cleared!" → "Clear" reset is English. Known nit: graph.html's own
  `clearNote()` briefly shows "Cleared!" and then resets to English "Clear". Prototype in `cb-meta-health`, then port to `concept-book-base` and
`conceptbook-app`.

**Goal:** when the user picks a language on the top bar, the whole app switches to it:

1. **UI labels:** header, buttons, hints, Home cards, Settings.
2. **Graph node labels:** the vis.js graph in the left pane.
3. **Content TOC:** the right pane's TOC entries, plus the concept content itself when that
   language has been generated.

Generated book and concept pages are already localized. They are produced per language
(`output/core.zh/...`), and since the §5 fix in `docs/readme-todo.md`, their headings and book
TOC use `labels.zh`. This plan covers the **app shell** around them.

---

## 1. Current state (what's missing)

| Area | Today | Gap |
|---|---|---|
| Top-bar picker (`LanguagePicker.js`) | Lists 10 languages; `setLocale()` writes `localStorage['cb-lang']` | **Nothing re-renders.** The change only shows after a reload. It offers 8 languages with no UI translations. |
| UI strings (`i18n.js`) | ~17 keys; `zh` overrides only 2 | About 60 strings are hard-coded English in `ContentPanel.js`, `GraphViewer.js`, `Domain.js`, `Settings.js`, `Home.js`, `DomainCard.js`, `About.js` |
| Graph labels (`concept_graph.py`) | `label = node.replace("_", " ")` | It ignores `graph.yaml`'s `labels`, so even English shows `blood`, not `Blood (Xue, 血)` |
| TOC (`ContentPanel.renderToc`) | Uses `n.label` from graph.html's `nodeIndex` | Inherits the graph's ID-derived label, in English only |
| Content language | Panel's Language dropdown, default `'en'` (decoupled from the UI locale on 2026-09-25) | Needs a defined relationship with the top-bar picker (see §3.3) |
| Catalog (`catalog.json`) | `name` and `description` in one language | No per-language domain name or description for Home cards or the domain picker |
| graph.html's own UI | Notes drawer strings ("no node selected", etc.) | English only |

**Data we already have:** all 214 meta-health nodes carry `labels: {en, zh}` in `graph.yaml`,
merged from `docs/gemini/concept_labels.yaml`. The SPL `tools.py` fallback chain,
`_label_for(data, concept, language)`, is: the label for the language, then the `en` label,
then the title-cased ID. The frontend should use the **same chain** so the graph, the TOC and the
generated pages always agree.

---

## 2. Design principles

- **One locale, one source of truth.** `i18n.js` owns `_locale`. Everything reads `getLocale()`
  and listens for a single `cb:localeChanged` event on `window`. No component keeps its own copy.
- **Change in place; don't reload the graph.** A language switch must not reload the graph
  iframe or lose the selected node, zoom, TOC scroll or displayed concept. Graph labels are
  swapped with vis.js `DataSet.update()`. `graph.html` stays **level- and language-invariant**:
  one file per domain carrying all labels, as `CLAUDE.md` already promises.
- **UI text always follows the top bar; graph and content fall back to what exists.** Picking
  中文 switches *every* UI string to Chinese immediately. Graph labels and content show Chinese
  where it exists and otherwise **fall back to what's available**, instead of showing an empty
  or error state.
- **Same fallback chain everywhere:** the requested language, then `en`, then *any* available
  language, then the `id` title-cased. It applies both to labels (`labels[lang]`) and to content
  (`concept_{node}.html` per language). A missing translation degrades gracefully and never
  breaks anything.
- **UI locales and content languages are different lists.** The top bar offers only locales that
  have UI translations (`en`, `zh` for now). The panel's Language dropdown keeps the full list,
  since the backend can *generate* content in any of them.
- **Translations live in YAML, not code** (see §2a). Two files: `locales/ui.yaml` for app strings
  and `locales/content.yaml` for domain content. JS and Python only *load* them. This replaces
  `CLAUDE.md`'s "keys inline in `i18n.js`" rule; update `CLAUDE.md` when Phase 1 lands.

---

## 2a. Translation storage: two YAML files

**Why YAML:**
1. **LLMs can translate it.** A script can add a new language by filling in missing keys, with no
   code edits.
2. **It's declarative.** Adding a language means editing data: the language list, the display
   names and the review status all live in the files, not in JS or Python constants.

It also keeps one source of truth for strings that both the frontend and the Python book renderer
need.

**Two files, split by *what* is translated:**

| File | Holds | Read by | Changes when |
|---|---|---|---|
| `locales/ui.yaml` | App-chrome strings: header, buttons, hints, Settings, plus the fixed strings in generated book pages (`book.contents` = Contents/目录, `book.payoff` = Payoff/学以致用) | `src/i18n.js` (bundled at build time); `spl/tools.py` (the `book.*` keys, replacing `_BOOK_UI`) | The app's code changes (new button, new message) |
| `locales/content.yaml` | Domain content: concept labels, domain (chapter) names and descriptions | Build scripts only. They merge it into `graph.yaml` `labels:` and the `catalog.json` `i18n` block, which the frontend and SPL already read | The *book* changes (new concept, new chapter) |

The split follows ownership. `ui.yaml` ships with the base and is the same for every derived
app. `content.yaml` is per book, and in `cb-meta-health` it replaces
`docs/gemini/concept_labels.yaml`.

**Shape.** Both files use the same `key → {lang: text}` shape that `concept_labels.yaml` and
`graph.yaml` `labels:` already use. All languages for a key sit side by side, so a gap is easy to
spot in review, and translating means adding a `ja:` line under each key.

```yaml
# locales/ui.yaml
_meta:
  source: en
  languages:                  # declarative UI_LOCALES + picker display names
    en: {name: English, status: source}
    zh: {name: 中文,    status: reviewed}
    ja: {name: 日本語,  status: machine}   # LLM-drafted, not yet reviewed
panel:
  generate:     {en: Generate,          zh: 生成}
  export_pdf:   {en: Export PDF,        zh: 导出 PDF}
  showing_fallback:
    en: "{requested} not yet generated, showing {shown}"
    zh: "{requested}版尚未生成，正在显示{shown}版"
book:
  contents:     {en: Contents,          zh: 目录}
  payoff:       {en: Payoff,            zh: 学以致用}

# locales/content.yaml
_meta: {source: en}
domains:
  meta_health_ch01:
    name:        {en: "TCM Foundations: Yin-Yang, Qi-Blood, and the Five Phases", zh: "中医基础：阴阳、气血与五行"}
    description: {en: "…", zh: "…"}
concepts:                     # one entry per concept id, shared across chapters
  blood_xue:   {en: "Blood (Xue, 血)", zh: 血}
```

- **Write block style, one language per line** (`blood_xue:` then `en: …` / `zh: …` indented
  under it), not one-line flow maps (`{en: …, zh: …}`). Lines stay short however many languages
  are added, and a new language is one added line per key, which diffs cleanly. Use `|` only for
  genuinely multi-line text (`about.body`); on a one-line label it would add a trailing newline.
  The examples above use flow style only for brevity.
- Nested keys are flattened to dotted keys on load (`panel.generate`), so `t('panel.generate')`
  works exactly as today.
- **Concept-ID collisions:** in `cb-meta-health` the same ID always means the same concept, which
  is why the 168 unique concepts share one label each. A base repo with unrelated domains may
  reuse an ID with a different meaning (`field` in physics vs. algebra). Allow a domain-scoped
  override, `domains.<id>.concepts.<concept>`, which takes precedence.

**Loading:**
- **Frontend:** import at build time with `@rollup/plugin-yaml` (one devDependency).
  `import ui from '../locales/ui.yaml'` is bundled as a JS object, so there's no runtime fetch or
  YAML parser in the browser, and `t()` stays synchronous. `UI_LOCALES` and the top-bar picker
  names come from `_meta.languages`.
- **Python:** `spl/tools.py` loads `ui.yaml`'s `book.*` keys with `yaml.safe_load`. The path is
  `Path(__file__).parent.parent / "locales"`, overridable with `CB_LOCALES_DIR`. If the file is
  missing it falls back to built-in English defaults, so an `spl/` copied elsewhere still runs.
- **content.yaml is never read at runtime.** The build step (`build_graphs_v1.py`, generalized
  as `scripts/apply_content_locale.py`) writes it into `graph.yaml` and `catalog.json`. SPL
  (`_label_for`) and `graph.html` keep reading the labels where they already are. `graph.yaml`
  stays self-contained, so it still works with plain `spl3 run`.

**LLM translation (the "dynamic" part):** `scripts/translate_locale.py --file ui|content --lang ja`
- It finds keys missing `ja`, sends them in batches with the `en` source (plus `zh` as a second
  reference), and writes the results back.
- It sets `_meta.languages.ja.status: machine`; a human flips it to `reviewed`.
- It runs **offline, at authoring time**, not in the browser: the site is static (GitHub Pages)
  with no API key, and translations need review before readers see them. Later, the local backend
  could expose it as an "Add language" button on the Settings page.
- For `content.yaml`, the prompt includes each concept's `defines` so terms like 气 and 津液 are
  translated in context, not word by word.

**YAML pitfalls to guard against** (checked by `check_i18n.py`, Phase 5):
- **Quote values that start with `{`, `[`, `:` or `@`.** `{n} nodes` unquoted parses as a mapping.
- **Language codes as keys:** PyYAML is YAML 1.1, where `no`/`yes`/`on`/`off` are booleans.
  `yaml.safe_load('no: x')` returns `{False: 'x'}`, so Norwegian (`no`) would silently break.
  Quote such keys, or use `nb`.
- **Placeholder parity:** every translation must keep the same `{placeholders}` as `en`.

---

## 3. Plan by phase

### Phase 1: locale plumbing and re-render (small)

- `i18n.js`
  - `setLocale(lang)`: set `_locale`, persist it, set `document.documentElement.lang`, and
    dispatch `cb:localeChanged` with `{detail: {lang}}`.
  - Load `locales/ui.yaml` (build-time import, §2a) and flatten it to dotted keys. Remove the
    inline `translations` object.
  - Export `UI_LOCALES`, derived from `ui.yaml` `_meta.languages`; nothing is hard-coded.
    Whether a `machine`-status language appears in the picker is a config flag (default: no).
  - Add `tl(labels, fallbackId)`, the label-picker helper implementing the fallback chain (requested → `en` → any → `id`),
    shared by the graph and the TOC.
  - Interpolation: `t('toc.empty', {n: 3})` with `{n}` placeholders, needed for strings like
    "Current: {llm}".
- `LanguagePicker.js`: ~~list only `UI_LOCALES`~~ lists every content language plus any
  extra UI locale (revised by review, see D2). The full generatable-language list moves to a `CONTENT_LANGUAGES` export for
  `ContentPanel`. That list could also move to `_meta` later.
- `vite.config.js`: add `@rollup/plugin-yaml`.
- `spl/tools.py`: replace `_BOOK_UI` with the `book.*` keys from `ui.yaml`, keeping built-in
  English defaults.
- `router.js`: on `cb:localeChanged`, **re-render the current route**, except on `#/domain/:id`,
  which updates in place (Phases 2–3). Home, About and Settings are stateless enough that a full
  re-render is simplest. Settings must keep unsaved form input; re-render it only if it's clean,
  otherwise relabel in place.

### Phase 2: localized graph labels

- `scripts/concept_graph.py`: emit per-node `labels` into `RAW.nodes`:
  ```python
  "label":  (attrs.get("labels") or {}).get("en") or node.replace("_", " "),
  "labels": attrs.get("labels") or {},
  ```
  The YAML loader (`_add_nodes`, ~line 920) currently **drops** `labels`, since it copies a fixed
  set of attributes. Add `labels=attrs.get("labels") or {}` there too. Then
  re-render all 9 `graph.html` files (`bash scripts/sync_from_spl.sh` or `concept_graph.py`
  directly). This alone fixes the English graph (`Blood (Xue, 血)`).
- `graph.html` template: expose the DataSet the same way `RAW`/`nodeIndex` already are. Add
  `visNodes` to the existing `GraphViewer` `eval()` line (`window.__cb_visNodes = visNodes`).
- `GraphViewer.js`
  - `el.setLang(lang)`:
    ```js
    visNodes.update(RAW.nodes.map(n => ({ id: n.id, label: wrap(tl(n.labels, n.id)) })))
    ```
    Also set `nodeIndex[id].label` to match, so `getPath()`, the notes drawer and search
    return localized labels.
  - `wrap()`: the template splits on spaces (`replace(/ /g,'\n')`), which does nothing for CJK.
    Use a per-script rule: break Latin on spaces, and break CJK every ~6 characters (or use vis.js
    `widthConstraint.maximum`). Check that labels like `五脏操` and `肝主疏泄` stay readable at
    the default zoom.
  - Apply the current locale once on `cb:graphLoaded` (the initial render), and again on each
    `cb:localeChanged`.
  - Search: match the query against `id`, **every** language's label and the current one, so
    typing `肝` or `liver` both work.
  - Localize the toolbar strings (`Search node…`, `Zoom −/+`, `Re-Center`) and the visible
    graph.html notes-drawer strings, by setting their `textContent` from the parent. The
    iframe's JS stays untouched.

### Phase 3: content panel (TOC and content)

- **TOC:** `renderToc()` uses `tl(n.labels, n.id)`. Sorting uses
  `localeCompare(b, getLocale())` so zh sorts by the Chinese collation (pinyin order in modern
  ICU). On `cb:localeChanged`, re-run `renderToc(anchorNode)`. Keep `anchorNodeId` and
  `displayNodeId`; only the text changes.
- **Content language follows the top bar (D1, confirmed):** on `cb:localeChanged`, the top-bar
  language **overwrites** the panel's Language dropdown and content re-resolves. The user can
  still change the panel dropdown afterwards, e.g. keep the UI in English and flip the content
  between EN and ZH to compare. That override lasts until the next top-bar change.
  - This partly reverses the 2026-09-25 "always English" default. The initial content language
    becomes the UI locale again, and a first-time visitor with no `cb-lang` still gets `en`.
  - No in-page side-by-side view (an earlier prototype had one and it was dropped). To compare,
    open two browser windows. That needs windows to stay **independent**: don't listen for
    `storage` events to sync `cb-lang` across windows, and keep the panel override per window
    (not persisted, D4).
- **Missing-language fallback (confirmed):** resolve content with the same chain: the requested
  language, then `en`, then any language that has the page. When it falls back, **display the
  fallback page automatically**, with a slim notice above it:
  "中文版尚未生成，正在显示英文版 · [生成中文版]" ("Chinese not yet generated, showing English ·
  [Generate Chinese]"). The notice text follows the UI locale.
  - The panel's Language dropdown keeps showing the *requested* language (zh), so Generate
    targets zh. The notice makes clear which language is actually shown.
  - Only when no language has the page does the panel show the existing "not generated yet"
    prompt.
  - Implementation: probe candidates in order with the existing `contentExists.js` check (it
    caches, so the cost is one extra probe per fallback). The catalog's `generated_concepts`
    file paths can short-circuit the probe.
- **Example (the confirmed scenario):** a domain has only EN content and the user picks 中文 on
  the top bar. All UI labels switch to Chinese. Graph nodes without `labels.zh` show their EN
  label, and nodes that have one show Chinese. The TOC matches the graph. Content shows the EN
  page with the "showing English" notice.
- **Strings:** move the ~20 hard-coded panel strings into `t()` keys: `Generate`, `Export PDF`,
  `Skip cache`, `Copy`/`Copied!`, the TOC hints, level names (`Intro/Core/College/Research`),
  generation log messages and errors.

### Phase 4: domain names, Home, About

- `catalog.json`: add an optional `i18n` block per entry; the base `name`/`description` remain
  the English fallback:
  ```json
  "i18n": { "zh": { "name": "第一章 中医基础：阴阳、气血与五行", "description": "…" } }
  ```
  Add a `catalogText(entry, field)` helper in `data/catalog.js` with the same fallback chain.
  Use it in `DomainCard`, the `Domain.js` domain picker, `Header` (breadcrumb) and the
  `source` attribution line.
  - The meta-health chapter titles are currently bilingual strings. Split them into a clean en
    `name` plus `i18n.zh.name` so each language shows one title.
  - Source of truth: `locales/content.yaml` `domains.<id>.name/description` (§2a). The build
    step writes them into `catalog.json`'s `i18n` block, and `build_graphs_v1.py` already
    preserves non-graph catalog keys.
  - Move `docs/gemini/concept_labels.yaml` into `locales/content.yaml` `concepts:`, and point
    `build_graphs_v1.py` at it.
- `About.js`: long prose, so it gets one `about.body` key per language in `ui.yaml`, holding
  Markdown or HTML as a YAML block scalar (`|`), not per-sentence keys.
- `Settings.js`: labels, hints, statuses (`Saved`, `API not reachable`, …). Model and adapter
  names stay untranslated.

### Phase 5: tooling and port

- `scripts/check_i18n.py`:
  - **UI coverage:** every `t('key')` used in `src/` exists in `en`, and it lists keys that
    each `UI_LOCALES` block is missing.
  - **Label coverage:** per domain and language, it reports nodes that have no `labels[lang]`.
    Chinese labels should contain CJK characters, and an `en` label shouldn't be just the ID.
  - **Catalog coverage:** `i18n.<lang>.name` for every entry.

  Run it in CI later; for now run it by hand before `npm run deploy`.
  - **YAML hygiene** (§2a): unquoted `{…}` values, boolean-looking language keys, and
    placeholder parity with `en`.
- `scripts/translate_locale.py --file ui|content --lang <code>` (§2a): LLM-drafts missing keys
  into the YAML with `status: machine`. It writes only to `locales/*.yaml`, never straight into
  `graph.yaml`; the build step propagates the result after review.
- **Port to concept-book-base:**
  - Everything above is domain-agnostic except the meta-health catalog text.
  - Base ships `locales/ui.yaml` with `en` + `zh` and an example `content.yaml`, and documents
    "add a language = run `translate_locale.py`, review, rebuild" in `CLAUDE.md` (i18n section).
  - `conceptbook-app` already has CJK content; check its `LanguagePicker` usage before merging.

---

## 4. Decisions to confirm

| # | Question | Recommendation |
|---|---|---|
| D1 | Should the top-bar language also switch the **content** language? | ✅ **Confirmed (2026-09-25):** yes. The top bar overwrites the panel dropdown; the user can still change the dropdown afterwards (e.g. EN UI, compare EN vs ZH content). |
| D2 | Which languages appear in the top bar? | ✅ **Revised (2026-09-25, review):** *all* content languages (the 10 generatable ones, plus any extra UI locale), not only those with UI translations — some books are generated in fr/es/ja/… For a language without UI strings (or whose UI strings are still `status: machine`), the UI falls back to English per string while content, node labels and catalog text use that language wherever they exist. The locale is any language code; `i18n.js` separates *UI language* (`_uiLang()`: a reviewed UI locale, else `en`) from *content language* (the locale itself). |
| D3 | What drives graph labels, and what happens when a translation is missing? | ✅ **Confirmed (2026-09-25):** the top-bar language drives graph labels (full relabel, not bilingual). Missing translations fall back to whatever is available (requested, then en, then any). The same rule applies to content, which is shown automatically with a "showing English" notice. UI labels always switch fully. |
| D4 | Persist the panel's content-language override? | No, keep it per session. The top-bar choice is the persisted preference (`cb-lang`). |
| D5 | Localize the URL (`#/domain/x?lang=zh`)? | Yes, **later**: it makes shared links open in the right language. Not needed for the prototype. |
| D6 | Where do translations live? | **YAML, two files** (proposed in review, 2026-09-25): `locales/ui.yaml` (app strings, bundled into JS and read by `tools.py`) and `locales/content.yaml` (labels and chapter names, merged into `graph.yaml`/`catalog.json` at build time). Shape: `key → {lang: text}`. Details in §2a. |

---

## 5. Test checklist (manual, prototype)

- [ ] Switch en↔zh on `#/domain/meta_health_ch01` with a node selected:
  - [ ] graph labels change without the iframe reloading (zoom and selection are kept)
  - [ ] TOC relabels and re-sorts, and the displayed concept stays selected
  - [ ] content switches to the zh page
  - [ ] header, buttons and hints are all Chinese
- [ ] Only EN generated and 中文 picked on the top bar → UI is fully Chinese, the graph shows EN
      labels (or zh where `labels.zh` exists), and content shows the EN page with the
      "showing English" notice and a working [生成中文版] button.
- [ ] Top bar EN, then panel dropdown flipped to ZH → content switches to zh while the UI and
      graph stay EN; changing the top bar again overwrites the dropdown.
- [ ] A concept with no page in any language → the existing "not generated yet" prompt.
- [ ] Search `肝`, `liver` and `liver_` all find the liver node in both locales.
- [ ] Reload → the locale persists; a first visit with empty `localStorage` → English.
- [ ] Home cards and the domain picker show zh chapter names; unknown keys fall back to en,
      never to a raw `key.name`.
- [ ] A domain **without** `labels` (e.g. an old base domain) renders exactly as before.
- [ ] `npx vite build` passes; `scripts/check_i18n.py` reports 0 missing for en/zh.

## 6. Effort estimate

| Phase | Size | Notes |
|---|---|---|
| 1 plumbing | ~1 day | Event, re-render, picker split, `ui.yaml` + Vite YAML plugin + `tools.py` loader |
| 2 graph | ~0.5–1 day | Includes the CJK wrap tuning and re-rendering 9 graph.html files |
| 3 content panel | ~0.5 day | TOC, following the top bar, automatic content fallback with notice, strings |
| 4 catalog/Home/About | ~0.5 day | Plus writing 9 zh chapter names and descriptions |
| 5 tooling + port | ~0.5–1 day | check_i18n.py, base/app ports |

Suggested order: **2 → 1 → 3** gives the visible win first (the localized graph and TOC); then 4
and 5.
