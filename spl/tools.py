"""Tools for recipe 74 — concept-book generator.

Component-based HTML output:
  write_concept_html  — one standalone page per concept (called inside the loop)
  build_book_index    — TOC index page linking to concept pages (called at end)

Domain wrapper tools: graph_lib and style_profiles functions are wrapped here
as @spl_tool callables so they can be used with CALL in build_concept_book.spl.
The loaded domain graph is cached in _DOMAIN_CACHE for the process lifetime.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from spl.tools import spl_tool

# ── Module-level domain cache ─────────────────────────────────────────────────
# Keyed by domain_yaml filename.  Populated by setup_domain() on first CALL.

_CB_DIR = Path(__file__).parent
_DOMAIN_CACHE: dict[str, dict] = {}
_MODULE_CACHE: dict[str, object] = {}


def _cb_module(name: str):
    """Import a module from the cookbook/74_concept_book/ directory (cached)."""
    if name not in _MODULE_CACHE:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, _CB_DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _MODULE_CACHE[name] = mod
    return _MODULE_CACHE[name]


def _domain(domain_yaml: str) -> dict:
    """Return cached domain entry; raises KeyError if setup_domain not called yet."""
    return _DOMAIN_CACHE[domain_yaml]


def _domain_id_from_yaml(domain_yaml: str) -> str:
    """Derive a clean domain_id (used in page titles and back-links) from domain_yaml.

    Handles two conventions:
    - A bare filename like 'mechanics_graph.yaml', resolved by
      graph_lib.load_domain() against SPL.py's own cookbook/74_concept_book
      directory -- domain_id is the filename with '_graph.yaml'/'.yaml' stripped.
    - An absolute path like '.../public/domains/{domain_id}/input/graph.yaml',
      used for domains synced from an external pipeline (e.g. concept-book-press)
      that never gets copied into SPL.py's cookbook dir at all -- domain_id is
      the directory two levels up from the file, not derivable from the
      filename alone (every such file is literally just named 'graph.yaml').
    Without this split, a bare regex strip on the full path string produces
    garbage like '/home/user/.../linalg ch05/input/graph' as the "domain_id".
    """
    p = Path(domain_yaml)
    if p.parent.name == "input" and p.stem == "graph":
        return p.parent.parent.name
    return re.sub(r'(_graph)?\.(ya?ml|json|py)$', '', p.name)


# ── Domain lifecycle tool ─────────────────────────────────────────────────────

@spl_tool
def setup_domain(domain_yaml: str, target: str, payoff_weight: str = "1.5") -> str:
    """Load domain, validate graph, compute teaching order.

    Caches the loaded graph, domain data, primitives, and teaching order.
    Raises ValueError if the graph is cyclic or not reducible to primitives.
    Returns the teaching order as a newline-separated list.
    """
    gl = _cb_module("graph_lib")
    data = gl.load_domain(domain_yaml)  # type: ignore[attr-defined]
    graph = gl.build(data)  # type: ignore[attr-defined]
    primitives = list(data.get("primitives", {}).keys())

    if not gl.acyclic(graph):  # type: ignore[attr-defined]
        raise ValueError(f"Domain graph '{domain_yaml}' has cycles — fix the YAML before generating")
    if not gl.reducible(graph, primitives):  # type: ignore[attr-defined]
        raise ValueError(f"Domain graph '{domain_yaml}' has concepts that don't reduce to primitives")

    needed = gl.ancestors(graph, target) | {target}  # type: ignore[attr-defined]
    restricted = gl.restrict(graph, needed)  # type: ignore[attr-defined]
    order = gl.productivity_order(restricted, weight=float(payoff_weight))  # type: ignore[attr-defined]
    apps = gl.applications_of(graph, target)  # type: ignore[attr-defined]

    _DOMAIN_CACHE[domain_yaml] = {
        "gl": gl,
        "data": data,
        "graph": graph,
        "primitives": primitives,
        "order": order,
        "target": target,
        "apps": apps,
    }
    return "\n".join(order)


# ── Order accessors ───────────────────────────────────────────────────────────

@spl_tool
def order_length(domain_yaml: str) -> str:
    """Return the number of concepts in the teaching order as a string integer."""
    return str(len(_domain(domain_yaml)["order"]))


@spl_tool
def order_item(domain_yaml: str, index: str) -> str:
    """Return the concept at position index (0-based) in the teaching order."""
    return _domain(domain_yaml)["order"][int(index)]


@spl_tool
def order_bullets(domain_yaml: str) -> str:
    """Return the teaching order as a markdown bullet list."""
    return "\n".join(f"- {c}" for c in _domain(domain_yaml)["order"])


@spl_tool
def apps_list(domain_yaml: str) -> str:
    """Return applications of the target concept as comma-separated labels ("none" if empty).

    Labels, not ids: this feeds write_payoff's prompt, and ids there get
    echoed verbatim into the generated prose.
    """
    return ", ".join(concept_label(a) for a in _domain(domain_yaml)["apps"]) or "none"


@spl_tool
def prereq_labels(domain_yaml: str, concept: str) -> str:
    """Return the concept's direct prerequisites as comma-separated labels ("none" if empty)."""
    graph = _domain(domain_yaml)["graph"]
    return ", ".join(concept_label(p) for p in sorted(graph.predecessors(concept))) or "none"


@spl_tool
def target_kind(domain_yaml: str) -> str:
    """Return the target node's kind: 'primitive', 'concept', or 'application'.

    Lets the workflow decide whether a target is an actual capstone
    (application) worth a payoff/applications wrap-up, versus an
    intermediate concept generated standalone (e.g. the user clicked a
    prerequisite node directly in the IDE) where a "why this is the natural
    endpoint" framing doesn't fit.
    """
    cache = _domain(domain_yaml)
    return cache["graph"].nodes[cache["target"]]["kind"]


@spl_tool
def normalize_bool(value: str) -> str:
    """Return "yes" if value is a truthy string ("yes"/"true"/"1", case-insensitive), else "no".

    Used to normalize @skip_cache so a caller passing "true"/"1" (e.g. a
    direct spl3 CLI invocation, not just the IDE's checkbox which always
    sends "yes"/"no") is honored the same way.
    """
    return "yes" if value.strip().lower() in ("yes", "true", "1") else "no"


# ── Content checks ────────────────────────────────────────────────────────────

@spl_tool
def count_new_primitives(section: str, domain_yaml: str) -> str:
    """Return the number of primitive names found in section text."""
    cache = _domain(domain_yaml)
    count = cache["gl"].new_primitives(section, cache["primitives"])  # type: ignore[attr-defined]
    return str(count)


@spl_tool
def verify_section(section: str, domain_yaml: str) -> str:
    """Run domain-specific content verification; returns 'ok' or a failure message."""
    cache = _domain(domain_yaml)
    return cache["gl"].verify_content(section, cache["data"])  # type: ignore[attr-defined]


# ── Style ─────────────────────────────────────────────────────────────────────

@spl_tool
def get_style_guide(style: str, domain_yaml: str = "") -> str:
    """Return the style instruction text for the given style profile name.

    When domain_yaml is given, its domain_id is classified into a subject
    rigor tier (rigorous/moderate/minimal — see style_profiles.infer_subject_rigor)
    so math/CS/physics content stays rigorous while biology/chemistry limits
    unnecessary formalism and humanities/arts/language domains skip it
    entirely.
    """
    sp = _cb_module("style_profiles")
    subject_rigor = "rigorous"
    if domain_yaml:
        domain_id = _domain_id_from_yaml(domain_yaml)
        subject_rigor = sp.infer_subject_rigor(domain_id)  # type: ignore[attr-defined]
    return sp.style_instruction(style, subject_rigor)  # type: ignore[attr-defined]


# ── Language ──────────────────────────────────────────────────────────────────

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "zh": "Chinese (中文)",
    "fr": "French (Français)",
    "es": "Spanish (Español)",
    "de": "German (Deutsch)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "pt": "Portuguese (Português)",
    "ru": "Russian (Русский)",
    "it": "Italian (Italiano)",
    "ar": "Arabic (العربية)",
    "hi": "Hindi (हिन्दी)",
}


@spl_tool
def language_name(code: str) -> str:
    """Map an ISO 639-1 code to an explicit language name (e.g. 'zh' -> 'Chinese (中文)').

    Spelling out the language name, rather than relying on the model to expand
    the bare code, makes the language instruction unambiguous for weaker/local
    models. Falls back to the code itself if unrecognised.
    """
    return _LANGUAGE_NAMES.get(code.strip().lower(), code)


# ── File utilities ───────────────────────────────────────────────────────────

@spl_tool
def dir_of_file(path: str) -> str:
    """Return the parent directory of a file path (creates it if needed)."""
    p = Path(path).parent
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


@spl_tool
def copy_file(src: str, dst: str) -> str:
    """Copy src to dst (creates parent dirs). Returns dst path."""
    import shutil
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_path)
    return str(dst_path)


# ── Timing ────────────────────────────────────────────────────────────────────

@spl_tool
def now_float() -> str:
    """Return the current monotonic time as a float string (for elapsed timing)."""
    return str(time.monotonic())


@spl_tool
def elapsed_secs(start: str) -> str:
    """Return seconds elapsed since the monotonic time stored in start."""
    return f"{time.monotonic() - float(start):.1f}"


@spl_tool
def sanitize_ts(ts: str) -> str:
    """Convert an ISO timestamp to a filename-safe string (colons and T replaced)."""
    return ts.replace(":", "-").replace("T", "_")


@spl_tool
def make_log_path(log_dir: str, ts_safe: str) -> str:
    """Construct the chain-trace log file path from directory and safe timestamp."""
    return f"{log_dir}/chain_trace-{ts_safe}.md"


@spl_tool
def needs_primitive_refinement(count: str, budget: str) -> str:
    """Return 'yes' if count exceeds budget, else 'no'."""
    return "yes" if int(count) > int(budget) else "no"


# ── HTML builder — component-based ───────────────────────────────────────────

def _render(template: str, **kwargs: str) -> str:
    """Substitute {key} placeholders; safe with CSS/JS that contain literal braces."""
    for k, v in kwargs.items():
        template = template.replace('{' + k + '}', v)
    return template


_OUTPUT_DIR_RE = re.compile(r'output[\\/]([^\\/]+)\.([^\\/]+)(?:[\\/]([^\\/]+))?[\\/]html$')

_CATALOG_CACHE: dict[str, list] = {}


def _load_catalog(catalog_path: Path) -> list:
    key = str(catalog_path)
    if key not in _CATALOG_CACHE:
        try:
            import json
            _CATALOG_CACHE[key] = json.loads(catalog_path.read_text(encoding='utf-8'))
        except Exception:
            _CATALOG_CACHE[key] = []
    return _CATALOG_CACHE[key]


def _catalog_domain_name(output_dir: str, domain_id: str) -> str:
    """This domain's full display name from public/domains/catalog.json (e.g.
    'Data Science Ch5: Time Series and Forecasting') — richer than the
    auto-titlecased domain_id ('Data Science Ch05') computed elsewhere.
    Returns '' if output_dir is unset, the domain isn't in the catalog yet,
    or catalog.json can't be found/parsed — callers fall back to the
    auto-titlecased name in that case."""
    if not output_dir:
        return ''
    p = Path(output_dir)
    for parent in p.parents:
        if parent.name == domain_id:
            for entry in _load_catalog(parent.parent / 'catalog.json'):
                if entry.get('id') == domain_id:
                    return _esc(entry.get('name') or '')
            break
    return ''


def _footer_meta(output_dir: str, language: str, domain_id: str, domain_title_fallback: str) -> str:
    """Page footer text: '{domain title} (Level: … · Language: … · Model: …)'
    — a downloaded/printed PDF loses the page's own domain-picker/breadcrumb
    context, so the footer is the only place that survives to say which
    domain and variant this page came from. Level/model parsed from
    output_dir's own output/{level}.{lang}/{model}/html convention (see
    api/services/executor.py's _get_output_dir) — no separate params needed
    for those, since output_dir already encodes them for every real
    generation call."""
    level = model = ''
    if output_dir:
        m = _OUTPUT_DIR_RE.search(str(output_dir).replace('\\', '/'))
        if m:
            level, model = m.group(1), m.group(3) or ''
    bits = []
    if level:
        bits.append(f'Level: {_esc(level.title())}')
    if language:
        bits.append(f'Language: {_esc(language.upper())}')
    if model:
        bits.append(f'Model: {_esc(model)}')
    detail = ' &middot; '.join(bits)
    title = _catalog_domain_name(output_dir, domain_id) or domain_title_fallback
    if title and detail:
        return f'{title} ({detail})'
    return title or detail


@spl_tool
def concept_label(concept: str) -> str:
    """Return the human-readable label for a concept ID (underscores → spaces, title-case)."""
    return concept.replace('_', ' ').title()


@spl_tool
def concept_context(domain_yaml: str, concept: str) -> str:
    """Return the concept's own `defines` text from the domain graph, for use
    as write_section's "surrounding context" argument.

    Looked up from the already-cached domain data (setup_domain() must have
    run first), across primitives/concepts/applications. Falls back to the
    bare concept id if the node or its `defines` field is missing, so a
    domain without rich definitions degrades gracefully rather than erroring.

    This is also the hook an external pipeline (e.g. concept-book-press's
    publish pipeline) uses for cross-chapter concept reuse: it can annotate
    a chapter's own `defines` text with "already introduced in Chapter N as:
    ..." before syncing/generating, and that annotation flows straight into
    the generation prompt through this same lookup — no separate mechanism
    needed.
    """
    data = _domain(domain_yaml)["data"]
    for section in ("primitives", "concepts", "applications"):
        node = (data.get(section) or {}).get(concept)
        if node:
            return node.get("defines") or concept
    return concept


@spl_tool
def write_concept_html(concept: str, section: str, domain_yaml: str, output_dir: str, language: str = "en") -> str:
    """Write a standalone HTML page for one concept to output_dir/concept_{concept}[_{language}].html.

    The filename is suffixed with the language code for every language except English
    (`en` stays unsuffixed for backward compatibility with existing links/bookmarks),
    so re-running the same domain in a different language does not overwrite the
    other language's pages.
    """
    if not output_dir:
        return ""
    domain_id = _domain_id_from_yaml(domain_yaml)
    domain_title = _esc(domain_id.replace('_', ' ').title())
    label = concept.replace('_', ' ').title()
    # Normalize first H2 heading: LLM may write ## concept_id; replace with ## Concept Label
    section = re.sub(
        r'^##\s+' + re.escape(concept) + r'[ \t]*$',
        f'## {label}',
        section, count=1, flags=re.MULTILINE,
    )
    lang_attr = f' lang="{language}"' if language and language != 'en' else ' lang="en"'
    html = _render(
        _CONCEPT_PAGE_TEMPLATE,
        lang_attr=lang_attr,
        concept_title=_esc(label),
        domain_title=domain_title,
        body=_md_to_html(section),
        footer_meta=_footer_meta(output_dir, language, domain_id, domain_title),
    )
    suffix = f"_{language}" if language and language != "en" else ""
    out = Path(output_dir) / f"concept_{concept}{suffix}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


@spl_tool
def build_book_index(domain_yaml: str, target: str, language: str, output_dir: str, payoff: str) -> str:
    """Build book_{target}[_{language}].html — a TOC index linking to individual concept pages.

    Filename and links carry the same language-suffix convention as
    write_concept_html: unsuffixed for English, `_{language}` otherwise.
    """
    if not output_dir:
        return ""
    cache = _domain(domain_yaml)
    order: list[str] = cache["order"]
    domain = _domain_id_from_yaml(domain_yaml)
    domain_title = _esc(domain.replace('_', ' ').title())
    lang_attr = f' lang="{language}"' if language and language != 'en' else ' lang="en"'
    suffix = f"_{language}" if language and language != "en" else ""

    toc_items = []
    for concept in order:
        label = _esc(concept.replace('_', ' ').title())
        cls = ' class="toc-target"' if concept == target else ''
        toc_items.append(f'<li{cls}><a href="concept_{concept}{suffix}.html">{label}</a></li>')
    toc_html = '<ol>\n' + '\n'.join(toc_items) + '\n</ol>'

    # Non-application targets never get a payoff (see build_concept_book.spl's
    # target_kind gating) — render no empty <section></section> for them.
    payoff_html = f'<section>\n      {_md_to_html(payoff)}\n    </section>' if payoff.strip() else ''
    html = _render(
        _BOOK_INDEX_TEMPLATE,
        lang_attr=lang_attr,
        domain_title=domain_title,
        target_title=_esc(target.replace('_', ' ').title()),
        toc=toc_html,
        payoff=payoff_html,
        footer_meta=_footer_meta(output_dir, language, domain, domain_title),
    )
    out = Path(output_dir) / f"book_{target}{suffix}.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


# ── internal helpers ──────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _inline_md(text: str) -> str:
    """Bold, italic, backtick-code.  Leaves $ LaTeX delimiters untouched."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', lambda m: f'<code>{_esc(m.group(1))}</code>', text)
    return text


def _md_to_html(md: str) -> str:
    """Minimal Markdown → HTML.  Preserves $...$ and $$...$$ for MathJax."""
    lines = md.split('\n')
    out: list[str] = []
    in_code = False
    in_dmath = False   # inside a multi-line $$ ... $$ block
    code_buf: list[str] = []
    math_buf: list[str] = []
    para_buf: list[str] = []

    def flush_para() -> None:
        if para_buf:
            out.append(f'<p>{" ".join(para_buf)}</p>')
            para_buf.clear()

    for line in lines:
        # ── fenced code blocks ────────────────────────────────────────────────
        if line.startswith('```'):
            if in_code:
                out.append(f'<pre><code>{_esc(chr(10).join(code_buf))}</code></pre>')
                code_buf.clear()
                in_code = False
            else:
                flush_para()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        # ── display math ($$ ... $$) ──────────────────────────────────────────
        # A line that is *only* $$ (possibly with whitespace) is a block delimiter.
        # A line like $$...$$ (content on same line) is a self-closing block.
        if re.match(r'^\s*\$\$', line):
            stripped = line.strip()
            # Self-contained: $$ ... $$ on one line (content between the delimiters)
            if stripped != '$$' and stripped.endswith('$$') and len(stripped) > 4:
                flush_para()
                out.append(line)
                continue
            # Toggle multi-line block
            if in_dmath:
                out.append('$$\n' + '\n'.join(math_buf) + '\n$$')
                math_buf.clear()
                in_dmath = False
            else:
                flush_para()
                in_dmath = True
            continue
        if in_dmath:
            math_buf.append(line)
            continue

        # ── headings ──────────────────────────────────────────────────────────
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            flush_para()
            lvl = len(m.group(1))
            text = _inline_md(m.group(2))
            slug = re.sub(r'\W+', '-', m.group(2).lower()).strip('-')
            out.append(f'<h{lvl} id="{slug}">{text}</h{lvl}>')
            continue

        # ── list items (bullet or numbered) ───────────────────────────────────
        m = re.match(r'^(?:[-*]|\d+\.)\s+(.+)$', line)
        if m:
            flush_para()
            out.append(f'<li>{_inline_md(m.group(1))}</li>')
            continue

        # Horizontal rule
        if re.match(r'^---+$', line.strip()):
            flush_para()
            out.append('<hr>')
            continue

        # Blank line → paragraph break
        if not line.strip():
            flush_para()
            continue

        para_buf.append(_inline_md(line))

    flush_para()
    return '\n'.join(out)


_SHARED_CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,serif;background:#fafaf8;color:#1a1a1a;line-height:1.7}
h2{font-size:1.45rem;color:#1e3a5f;margin-bottom:12px}
h3{font-size:1.1rem;color:#2e4a7f;margin:20px 0 8px}
h4{font-size:1rem;color:#3a5a8f;margin:16px 0 6px}
p{margin-bottom:16px;font-size:1rem}
li{margin-bottom:6px;margin-left:24px;font-size:1rem}
pre{background:#f4f4f0;border:1px solid #d8d8d0;border-radius:6px;
    padding:16px 20px;overflow-x:auto;margin:16px 0}
code{font-family:Menlo,Consolas,monospace;font-size:.87em}
p code{background:#f0f0ea;padding:1px 4px;border-radius:3px}
footer.spl-credit{margin-top:32px;padding-top:16px;border-top:1px solid #e0e0d8;
      font-family:system-ui,sans-serif;font-size:.78rem;color:#999;text-align:center}
footer.spl-credit a{color:#2563eb;text-decoration:none}
footer.spl-credit span{display:block}
footer.spl-credit .spl-credit__meta{margin-bottom:4px}"""

_MATHJAX_HEAD = """\
<script>
MathJax = {
  loader: { load: ['[tex]/mathtools'] },
  tex: { inlineMath: [['$','$'],['\\\\(','\\\\)']], displayMath: [['$$','$$'],['\\\\[','\\\\]']],
         packages: { '[+]': ['mathtools'] } },
  options: { skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" async></script>"""

_CONCEPT_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html{lang_attr}>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{concept_title} | {domain_title}</title>
""" + _MATHJAX_HEAD + """
<style>
""" + _SHARED_CSS + """
.page{max-width:780px;margin:0 auto;padding:40px 32px}
section{margin-bottom:48px;border-top:1px solid #e0e0d8;padding-top:36px}
section:first-of-type{border-top:none;padding-top:0}
</style>
</head>
<body>
<div class="page">
  <main>
    {body}
  </main>
  <footer class="spl-credit"><span class="spl-credit__meta">{footer_meta}</span><span class="spl-credit__powered">Generated and Powered by <a href="https://github.com/digital-duck/SPL.py" target="_blank" rel="noopener">SPL</a></span></footer>
</div>
</body>
</html>"""

_BOOK_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html{lang_attr}>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Concept Book: {target_title} — {domain_title}</title>
""" + _MATHJAX_HEAD + """
<style>
""" + _SHARED_CSS + """
.page{display:grid;grid-template-columns:260px 1fr;min-height:100vh}
nav.toc{position:sticky;top:0;height:100vh;overflow-y:auto;
        background:#1e3a5f;color:#e8f0fe;padding:24px 16px}
nav.toc h2{font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;
           color:#90b4e8;margin-bottom:14px;font-family:system-ui,sans-serif}
nav.toc ol{list-style:decimal inside;padding:0}
nav.toc li{margin-bottom:7px;font-size:.85rem;line-height:1.4;font-family:system-ui,sans-serif}
nav.toc a{color:#a8c8f0;text-decoration:none}
nav.toc a:hover{color:#fff}
nav.toc li.toc-target{font-weight:700}
nav.toc li.toc-target a{color:#fff}
main{padding:48px 64px;max-width:860px}
h1.book-title{font-size:2rem;color:#1e3a5f;margin-bottom:4px}
.subtitle{color:#666;margin-bottom:48px;font-size:1rem;font-style:italic;font-family:system-ui,sans-serif}
section{margin-bottom:56px;border-top:1px solid #e0e0d8;padding-top:40px}
section:first-of-type{border-top:none;padding-top:0}
@media(max-width:768px){.page{grid-template-columns:1fr}
nav.toc{position:relative;height:auto}}
</style>
</head>
<body>
<div class="page">
  <nav class="toc">
    <h2>Contents</h2>
    {toc}
  </nav>
  <main>
    <h1 class="book-title">Concept Book: {target_title}</h1>
    <p class="subtitle">{domain_title} &middot; Generated by SPL</p>
    <section>
      {payoff}
    </section>
    <footer class="spl-credit"><span class="spl-credit__meta">{footer_meta}</span><span class="spl-credit__powered">Generated and Powered by <a href="https://github.com/digital-duck/SPL.py" target="_blank" rel="noopener">SPL</a></span></footer>
  </main>
</div>
</body>
</html>"""
