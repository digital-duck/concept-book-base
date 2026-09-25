# ConceptBook Generation Guide

## Prerequisites

```bash
conda activate spl123
cd ~/projects/digital-duck/concept-book/
```

The backend API must be running for the UI Generate/PDF buttons:
```bash
bash scripts/start-api.sh   # uvicorn on :8200
npm run dev                 # Vite on :5174 (separate terminal)
```

---

## Scripts

### `scripts/test_gen.sh` — interactive / per-domain runs

```bash
bash scripts/test_gen.sh                    # all domains
bash scripts/test_gen.sh linalg             # one domain
bash scripts/test_gen.sh sql linalg         # two domains
```

Key flags inside the script (edit before running):
| Line | Flag | Effect |
|------|------|--------|
| `--skip-cache` | force fresh LLM calls | use when re-generating with new prompts or a new model |
| `--skip-existing` | skip targets already in catalog | use for incremental runs |

Logs are written to `logs/batch_gen_YYYYMMDD_HHMMSS.log`.

### `scripts/batch_generate.py` — CLI with full options

```bash
python scripts/batch_generate.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--domain` | all | Domain ID (repeatable: `--domain sql --domain linalg`) |
| `--n-targets` | 2 | Number of application nodes per domain |
| `--level` | domain default | Override level: `intro / core / college / research` |
| `--language` | `en` | Output language ISO code (`en`, `zh`, `fr`, …) |
| `--llm` | `claude_cli:claude-sonnet-5` | LLM backend (env: `CB_LLM`) |
| `--spl-dir` | `~/projects/digital-duck/SPL.py` | SPL.py root (env: `CB_SPL_DIR`) |
| `--skip-cache` | off | Bypass spl3 LLM cache — force fresh generation |
| `--skip-existing` | off | Skip targets already listed in `catalog.json` books |
| `--dry-run` | off | Print planned jobs without running |
| `--stop-on-error` | off | Abort batch on first failure |

### `scripts/batch_gen_domains.py` — file-driven batch runs, one book per domain

For generating a whole list of domains unattended (e.g. all 34 OpenStax
College Physics chapters synced via `sync_from_press.py`). Reads a plain-text
domain list instead of repeated `--domain` flags, picks each domain's
capstone target automatically (first application node, else the
highest-tier concept — same rule `sync_from_press.py` uses), and is safe to
interrupt and re-run: a progress file tracks what's already `done`, and it
stops the whole batch (instead of burning through the rest of the list) the
moment it sees a Claude CLI session/rate-limit signature.

```bash
python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt [OPTIONS]
```

Domain list format — one id per line, `#` starts a comment, blank lines ignored:
```
# OpenStax College Physics 2e
college_physics_ch3
college_physics_ch4
# college_physics_ch5   # temporarily excluded
```

| Option | Default | Description |
|--------|---------|-------------|
| `--domains-file` / `-f` | — | Required. Path to the domain list `.txt` |
| `--model` | `sonnet` | Shorthand (`sonnet`/`haiku`/`opus`/`gemma3`/`gemma4`) or a raw spl3 `--llm` string |
| `--level` | `college` | `intro / core / college / research` |
| `--language` / `-l` | `en` | ISO code or friendly name |
| `--skip-cache` | off | Bypass spl3 LLM cache |
| `--force` | off | Regenerate even if the book already exists on disk |
| `--limit` | all | Only process the first N domains — use for a test run before a full unattended pass |
| `--progress-file` | `scripts/batch_gen_domains_progress.json` | Resume tracking, keyed `domain\|model\|level\|lang` |
| `--log-file` | none | Also write output to this file (in addition to stdout) |

Behavior worth knowing (fixed 2026-09-24, ported from cb-meta-health):
- **Level → style.** `--level` is mapped to the workflow's `@style` through
  `level_style.resolve_style(level, catalog tags)`, the same as the web UI and
  `batch_generate.py`. Previously only `lvl=` was passed, which `build_concept_book.spl`
  ignores, so every book was generated at the default `textbook` style. Check that the
  `Queue` line shows the expected `style=`.
- **spl3 safety caps.** spl3's built-in limits (15 loop iterations, 25 LLM calls, 100k tokens)
  are too small for a normal chapter. The subprocess now defaults to `SPL_WHILE_MAX_ITER=60`,
  `SPL_MAX_LLM_CALLS=120` and `SPL_MAX_TOTAL_TOKENS=600000`; values exported in the shell win.
- **Non-English output.** The script looks for `book_{target}_{lang}.html` for non-English
  languages (English stays unsuffixed), matching `spl/tools.py`. Previously every non-English
  run was reported as failed even though the book had been written.
- **Existing output isn't registered.** When a book already exists on disk, the script marks
  it `done` in the progress file but does not update `catalog.json`; use `--force` to
  regenerate (fast from the cache) and register it.

**Test one domain first, then run the full list:**
```bash
conda activate spl123

# Test — 1 domain, current defaults (sonnet / college / en)
python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt --limit 1

# Full run (resumable — re-running skips anything already marked done)
python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt \
    --log-file scripts/batch_gen_domains.log
```

Expect ~6–7 min per domain with Sonnet (dozens of LLM calls each) — a 31-domain
run will likely hit a Claude CLI rate limit partway through and stop; just
re-run the same command once the limit resets.

**Later passes** (different model/level/language — e.g. down-scoping to high
school): rerun against the same domains file with different flags; each
`(domain, model, level, lang)` combination gets its own progress-file key and
output directory, so passes don't collide:
```bash
python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt \
    --model gemma4 --level core --language zh
```

---

## Cache behaviour

The spl3 content cache key is `(concept, language, style, llm)`, so the same concept at a different level (style) is a separate cache entry. The style *name* is in the key, not the prompt text, so after a prompt or style-profile change, add `--skip-cache` to regenerate.

Since 2026-09-24 the key also includes a hash of the concept's `defines` text (`ctx`, via
`spl/tools.py`'s `section_params`). Before that, a concept declared in several chapters (e.g. a
later chapter re-declaring an earlier concept as a primitive) shared one cache slot. A later
chapter silently reused the earlier chapter's section, and with `--skip-cache` the last chapter
to run overwrote it for all of them. Editing a node's `defines` now invalidates its cached
section automatically. **After upgrading, existing cache entries no longer match, so the first
run of each domain regenerates everything once.**

**Localized labels (optional):** a node may carry `labels: {en: "...", zh: "..."}` in
`graph.yaml`. `localized_label()` uses it for section headings, page titles and the book TOC, with
a fallback to the title-cased id. When a node has a label for the page's language, the section's
leading `##` heading is normalized to it (even for cached sections); without one, the LLM's own
heading is kept. The book index's fixed strings ("Contents", "Payoff", "Concept Book") are
localized via `_BOOK_UI` in `spl/tools.py` (en and zh so far).

- Same concept in **different languages** → separate cache entries (independent)
- Same concept with **different LLM** → separate cache entries (good for quality comparison)
- Re-running without `--skip-cache` reuses the cached version → fast (0 LLM calls)
- Re-running with `--skip-cache` regenerates everything fresh → slow but picks up prompt changes

**Rule of thumb:**
- First run for a new domain/language/model → always add `--skip-cache`
- Subsequent runs to fill missing concepts → omit `--skip-cache` (reuse hits, generate misses)

---

## Generating in multiple languages

```bash
# English (default)
python scripts/batch_generate.py --domain chinese_characters --skip-cache

# Chinese
python scripts/batch_generate.py --domain chinese_characters --language zh --skip-cache

# Both via test_gen.sh: edit the python call to add --language zh, then run
bash scripts/test_gen.sh chinese_characters
```

Output lands in separate directories:
```
public/domains/chinese_characters/output/intro.en/html/
public/domains/chinese_characters/output/intro.zh/html/
```

---

## Comparing LLM quality

```bash
# Generate with Sonnet (default)
python scripts/batch_generate.py --domain linalg --skip-cache

# Generate same domain with Haiku for comparison
python scripts/batch_generate.py --domain linalg --skip-cache \
    --llm claude_cli:claude-haiku-4-5-20251001
```

Both outputs are cached independently. Compare the HTML files in:
```
public/domains/linalg/output/college.en/html/
```

---

## Output locations

| Artifact | Path |
|----------|------|
| Concept book HTML (TOC index) | `public/domains/{id}/output/{level}.{lang}/html/book_{target}.html` |
| Individual concept HTML | `public/domains/{id}/output/{level}.{lang}/html/concept_{name}.html` |
| PDF | `public/domains/{id}/output/{level}.{lang}/pdf/book_{target}.pdf` |
| Concept graph | `public/domains/{id}/output/graph.html` |
| Generation logs | `logs/batch_gen_YYYYMMDD_HHMMSS.log` |
| SPL run logs | `~/.spl/logs/build_concept_book-*.md` |

---

## Regenerating graph.html (after color/structure changes)

```bash
bash scripts/sync_from_spl.sh
```

This copies `*_graph.yaml` from SPL.py and regenerates all `graph.html` files.
Then hard-refresh the browser (`Ctrl+Shift+R`).

---

## Completed runs

### College Physics ch3-34 synced from concept-book-press (2026-07-21)
```bash
python scripts/sync_from_press.py --book college-physics-2e --prefix college_physics_ch
```
Registered 32 new catalog entries (`has_book: false`, graph-only) for ch3-34;
ch1/ch2 already had generated books and were refreshed in place without
touching their `books`/`generated_concepts`.

Test run of `batch_gen_domains.py` (sonnet / college / en), 1 domain:
```bash
python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt --limit 1
```
```
Queue  college_physics_ch3  target=river_crossing_relative_velocity
       LLM calls: 22  Latency: 339248ms
       ✓ done (339s)
Batch complete — 1 generated, 0 skipped, 0 failed.
```
Full ch3-34 run (sonnet/college/en) still pending — resumable via the same
command without `--limit`.

### Path A: sql (2026-06-26)
```bash
./scripts/test_gen.sh sql
```
```
LLM calls: 5  Latency: 89103ms
[ok] sql/web_application_backend — catalog updated
Batch complete: 2 succeeded, 0 failed.
```

### Path B: college_physics_ch1 (2026-06-26)
```bash
cd ~/projects/digital-duck/concept-book-press
python -B -m pipeline.cli pipeline --source pdf --pdf input/college-physics-2e.pdf --chapter 6-15 --check-yaml

python -B -m pipeline.cli pipeline --source pdf --pdf input/college-physics-2e.pdf --chapter 16-25 --timeout 900
python -B -m pipeline.cli pipeline --source pdf --pdf input/college-physics-2e.pdf --chapter 26-34 --timeout 900
python -B -m pipeline.cli pipeline --source pdf --pdf input/college-physics-2e.pdf --chapter 31-34 --timeout 900
```


```
LLM calls: 8  Latency: 146406ms
[ok] college_physics_ch1/approximation — catalog updated
Batch complete: 1 succeeded, 0 failed.
```

### chinese_characters EN + ZH (2026-06-26)
```bash
python scripts/batch_generate.py --domain chinese_characters --language en --skip-cache
python scripts/batch_generate.py --domain chinese_characters --language zh --skip-cache

```

### --llm ollama:gemma3 geometry

```bash
SPL_WHILE_MAX_ITER=30 python scripts/batch_generate.py --domain geometry --llm ollama:gemma3
```


### --llm ollama:gemma4 english_morphology
see `~/projects/digital-duck/SPL.py/example.env` for global env variable settings

```bash
SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain english_morphology --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain english_morphology --llm claude_cli:claude-sonnet-5


SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain calculus --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain mechanics --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain linalg --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain sage_learning --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain cs_data_structures --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain cs_algorithms --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain quantum_physics --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain chemistry_elements --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain biology --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain molecular_biology --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain medicine --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain lean_proving --llm ollama:gemma4

SPL_WHILE_MAX_ITER=50 SPL_MAX_LLM_CALLS=50 \
python scripts/batch_generate.py --domain music_theory --llm ollama:gemma4


```