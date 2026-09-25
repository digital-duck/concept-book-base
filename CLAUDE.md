# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in
this repository. This is the **base template** — a derived app should keep this file's
skeleton and fill in domain-specific facts (domain list, level defaults, branding).

## Commands

```bash
# Frontend dev (read-only, no book generation)
npm run dev          # http://localhost:5174/<base>/

# Full stack (book generation requires spl123 conda env)
conda activate spl123
pip install -r requirements-api.txt
bash scripts/start-api.sh          # uvicorn, separate terminal
npm run dev                         # Vite proxies /api → the backend

# Sync domain content from SPL.py after regenerating graphs
bash scripts/sync_from_spl.sh

# Deploy to GitHub Pages
npm run deploy       # builds dist/ and pushes to gh-pages branch
```

## Architecture

**Content pipeline:** graphs are authored (or generated) as `input/graph.yaml` per
domain, then `scripts/concept_graph.py` renders `output/graph.html` (a vis.js
navigator) locally. Concept book HTML is generated on demand by the backend, which
shells out to an SPL.py `spl3 run` pipeline.

**Domain directory layout:**
```
public/domains/{id}/
  input/graph.yaml                        # concept graph definition
  output/graph.html                       # vis.js navigator (level/lang invariant)
  output/{level}.{lang}/{model}/html/     # e.g. core.en/gemma4/html/
    book_{target}.html                    # TOC-index concept books
    concept_{name}.html                   # individual concept component books
```

`graph.yaml` node fields used by the frontend: `id`, `label`, `kind` (`primitive` nodes
are excluded from the Generate dropdown), `tier`, `composed_of` (edges to prerequisite
nodes).

**Content levels** (learner progression, not tied to any specific school system):
`intro` (basic) → `core` (expanded) → `college` (extensive) → `research` (advanced). A
domain can have books at multiple levels — level is a content property, not a domain
property.

**Frontend** (`src/`): Vite + Vanilla JS with zero frameworks. `/domain/:id` is a single
consolidated Graph-IDE page — graph on the left, generated content + TOC on the right —
not split across separate Graph/Content pages.
- `router.js` — hash-based router (`#/`, `#/domain/:id`, plus any `path?query` route).
- `config.js` — branding overrides (`appConfig.logoImage`, etc.) for derived apps.
- `data/catalog.js` — fetches/caches `public/domains/catalog.json`, the domain
  registry (source of truth for the domain list).
- `lib/paths.js` — the `output/{level}.{lang}/{model}/html/{kind}_{name}.html` path
  schema in one place; build/parse variant paths only through this module.
- `lib/contentExists.js` — shared "does this generated page exist?" check (sniffs
  generated-page markers since dev servers 200 the SPA shell for unknown paths).
- `pages/Domain.js` — the consolidated IDE page: top domain picker, `GraphViewer` (left,
  iframe) and `ContentPanel` (right, TOC + content + Generate/Export PDF), all sharing
  one Model/Level/Language state.
- `components/GraphViewer.js` — the graph iframe integration point. Loads `graph.html`
  in an iframe, then uses `contentWindow.eval()` to expose `RAW`/`nodeIndex`/
  `__cb_network`, patches `handleSelect` to emit `cb:nodeSelected` custom events, and
  exposes `getPath(nodeId)`/`selectNode(nodeId)` for `ContentPanel.js` to drive the TOC
  and stay in sync with graph clicks. A CSS-only relayout (same
  `insertAdjacentElement`/injected-`<style>` technique as before) hides `graph.html`'s
  own learning-path/explanation panels and turns its Notes sidebar into a collapsible
  bottom drawer under the graph — that panel's own `localStorage` note-taking JS is
  untouched. Same-origin, not cross-origin — both `graph.html` and the shell are served
  from the same Vite dev server.
- `components/ContentPanel.js` — the right panel: Model / Level / Language / Refresh /
  **Generate** / **Export PDF** controls, a flattened alphabetical TOC (concept/
  application/primitive nodes on the selected node's prerequisite path, via
  `graphViewer.getPath()`), and content resolution — loads `concept_{node}.html` in an
  iframe when it exists, else shows a "not generated yet" prompt with Generate enabled.
  Primitives get the same full Generate/content treatment as concepts and applications
  (the backend's `write_section()` is kind-agnostic); only the *payoff* capstone section
  is application-kind-gated (see `spl/build_concept_book.spl`). A resolve-token guard
  prevents a slow lookup for a node the user has since clicked away from from
  overwriting the currently-displayed content.

**Backend** (`api/`): FastAPI, bound to `127.0.0.1` only (see `scripts/start-api.sh`) —
it holds user-supplied LLM API keys (Settings page) and has side-effecting GET
endpoints, so it must never be reachable from the LAN or by an arbitrary website via
CORS (`api/app.py`'s CORS origin list is derived from `DEV_PORT`).
- `GET /api/generate` (SSE) — params: `domain`, `target`, `level`, `language`, `model`,
  `skip_cache`. Streams `spl3 run` subprocess output as `log`/`done`/`gen_error` events.
- `GET /api/pdf` — params: `domain`, `target`, `level`, `language`, `model`. Renders
  whichever of `concept_{target}.html`/`book_{target}.html` exists to PDF.
- `GET /api/domains` / `/api/domains/{id}/status` — reads `catalog.json`.
- `GET`/`PUT /api/settings` — LLM adapter/model, execution limits, and per-adapter API
  keys (Anthropic/OpenAI/Gemini/OpenRouter — Claude CLI and Ollama need none). Settings
  are in-memory only; a `--reload` or process restart wipes them back to `.env`
  defaults — pre-seed a key durably via `.env`'s `CB_*_API_KEY` vars instead.
- `api/services/adapters.py` — the single adapter-name ↔ env-var ↔ Settings-field table;
  `executor.py`'s subprocess env injection and `settings.py`'s "is a key set" check both
  read from it rather than each keeping their own copy.
- `api/services/path_safety.py` — `safe_segment`/`safe_optional_segment` validate every
  `domain`/`target`/`level`/`language`/`model` query param (letters/digits/`_`/`-` only)
  before it touches a filesystem path; `assert_within` is a belt-and-suspenders check
  that a resolved path is still inside `public_domains`. Every router building a path
  from a query param must validate through this module first.
- `api/config.py` — `Settings` reads env vars prefixed `CB_`; `spl_dir`/`public_domains`
  are anchored to the repo root if given as a relative path, since `stream_generate`
  runs the spl3 subprocess with a different `cwd`.
- `api/services/catalog_lock.py` — the single write-path for `catalog.json`
  (`read_catalog`/`update_catalog`). Every writer must go through `update_catalog()` —
  it serializes concurrent writers with an fcntl lock and publishes atomically, so a
  generation task and a batch script running at the same time can't silently drop each
  other's updates.

**Level → style:** `scripts/level_style.py` is the single level→style map
(`intro`→`feynman`, `core`→`core`, `college`→`college`, `research`→`research`, with a
`research`→`research_applied` fallback for domains not tagged `math`/`physics`/
`engineering`) — `build_concept_book.spl`'s `@style` input is what actually controls
generated content depth/rigor (`@lvl`/`@level` is not a workflow input and is silently
ignored). Both `api/services/executor.py` (the web UI) and `scripts/batch_generate.py`
(CLI batch runs) import this one module so they can't drift apart.

**Deployment:** GitHub Pages (static). The backend is a local-only tool; generated
book/concept HTML files are committed into `public/domains/` and included in the
`dist/` build.

## Iframe ↔ parent event protocol

`GraphViewer.js` bridges the iframe (`graph.html`) and the parent app via custom events
on `window`:
- `cb:graphLoaded` — dispatched after iframe loads. `detail.concepts` is an array of
  `{id, label, kind, tier}`.
- `cb:nodeSelected` — dispatched when a user clicks a node. `detail.nodeId` and
  `detail.node` (full node object from `nodeIndex`).

## Key data shapes

`catalog.json` entry:
```json
{
  "id": "domain-id",
  "name": "Human-Readable Domain Name",
  "capstone": "some_concept_id",
  "default_level": "core",
  "has_navigator": true,
  "has_book": true,
  "books": [{"target": "some_concept", "file": "output/core.en/html/book_some_concept.html"}],
  "generated_concepts": [{"name": "some_concept", "label": "Some Concept", "file": "output/core.en/html/concept_some_concept.html"}],
  "tags": ["math"],
  "i18n": {"zh": {"name": "…", "description": "…"}},
  "source": {"title": "...", "authors": "...", "license": "...", "url": "...", "attribution": "..."}
}
```

`books` = full concept books (TOC index). `generated_concepts` = individual concept
component books. `source` is optional — when present, it renders as an attribution
line on the domain page (see `src/pages/Domain.js`); use it when a domain is derived
from a specific external text (textbook, paper, corpus).

## Vite base path

`vite.config.js` sets `base`. All asset and domain URLs must use
`import.meta.env.BASE_URL` as prefix (see `GraphViewer.js` iframe `src`).

## Adding a new domain

1. Add the domain ID and its default level to the `LEVEL_MAP` in
   `scripts/sync_from_spl.sh`.
2. Add an entry to `public/domains/catalog.json`.
3. Run `bash scripts/sync_from_spl.sh` to copy files into `input/` and generate
   `output/graph.html`.

## i18n

UI strings live in `locales/ui.yaml` (`key → {lang: text}`, nested keys flattened to dotted
keys); `src/i18n.js` imports it at build time (`@rollup/plugin-yaml`) and provides `t(key,
vars)`, `tl(labels, fallback)` (pick a node label: locale → `en` → any → fallback) and
`i18n(el, key, {attr, vars})`, which binds an element so `applyI18n()` can relabel it in
place. The top-bar picker lists `_meta.languages`; switching dispatches `cb:localeChanged`
— non-domain pages re-render, the domain page relabels in place and `GraphViewer` relabels
graph nodes from each node's `labels` (emitted into `graph.html` by `concept_graph.py`).
`spl/tools.py` reads the `book:` block for generated book pages. Markup can declare keys
with `data-t` / `data-t-title` / `data-t-placeholder` and call `bindI18n(root)`. The domain
page and Settings relabel in place (no re-render, so graph state and unsaved form input
survive); other pages re-render.

Content translations (chapter names/descriptions, concept labels) live in
`locales/content.yaml` and are **build-time only**: `scripts/apply_content_locale.py` writes
concept labels into each node's `labels:` in `graph.yaml` (line-level edits — nothing else in
the file changes) and chapter text into `catalog.json` (`name`/`description` = en,
`i18n.<lang>.{name,description}` = the rest), which `data/catalog.js`'s
`catalogText(entry, field)` reads. Write both YAML files in block style, one language per
line.

Adding a language (e.g. `ja`):
1. `python scripts/translate_locale.py --file ui --lang ja --name 日本語` — LLM-drafts every
   missing key in place (ruamel keeps comments/layout) and registers `ja` with
   `status: machine`, which the top-bar picker hides until a reviewer sets `reviewed`
   (or `appConfig.showMachineLocales` is true).
2. `python scripts/translate_locale.py --file content --lang ja`, then
   `python scripts/apply_content_locale.py` and re-render `graph.html`.
3. `python scripts/check_i18n.py` — errors on undefined keys, placeholder mismatches and
   YAML pitfalls (unquoted `{…}` values, `no`/`yes` read as booleans); warns on gaps.

Design and history: `docs/DEV/readme-i18n.md`.

## Extension points

The base intentionally ships a minimal feature set. These are known, deliberate
extension points for a derived app rather than gaps to "fix" in the base — treat them
as things to build in your fork, not to upstream unless a second app needs the same
thing:

- **Branding** — `src/config.js` (`appConfig.logoImage`) and `src/i18n.js`'s
  `app.title` key. Header.js reads both; no other file should need editing to rebrand.
- **Auth / multi-user hosting** — `main.js` registers routes unguarded. An app that
  needs login-gated routes should wrap `register()` calls in its own guard rather than
  modifying `router.js`.
- **Content panel layout** — `components/ContentPanel.js` is currently a single file. A
  derived app with heavier reading needs (compare view, chat sidebar, richer TOC) should
  factor it into `components/content/*.js` submodules rather than growing the one file
  indefinitely.
- **Search** — `data/catalog.js`'s domain/concept search is plain substring matching.
  A domain with non-Latin-script or phonetic search needs (e.g. pinyin) should layer a
  matcher on top rather than special-casing catalog.js.
- **Settings page** — ships a single flat form (SPL adapter/model, execution limits,
  per-adapter API keys). Multi-tab layouts or per-user API-key management belong in the
  fork, not the base.
