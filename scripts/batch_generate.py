#!/usr/bin/env python3
"""Batch pre-generate concept books for all domains.

Picks every application node per domain (the whole graph.yaml applications:
dict, in order) and runs spl3 for each, updating catalog.json on success —
same path as the FastAPI backend. Skipping applications beyond the first
few used to be the default; a domain like college_physics_ch24 has 12, so
capping silently left the static site incomplete for the rest.

Targets already present in catalog.json are skipped by default (pass
--no-skip-existing to force regeneration, e.g. after a prompt/style change).

Prerequisites (spl123 conda env must be active):
    conda activate spl123
    pip install -r requirements-api.txt   # click, pyyaml, pydantic-settings

Usage examples:
    # Dry-run: show what would be generated
    python scripts/batch_generate.py --dry-run

    # Cap cost: at most 1 application per domain
    python scripts/batch_generate.py --n-targets 1

    # Only specific domains
    python scripts/batch_generate.py --domain mechanics --domain calculus

    # Domain ranges/lists in one --domain value (comma-separated, "-" for an
    # inclusive numeric range between two same-prefix ids)
    python scripts/batch_generate.py --domain "chemistry_ch05-chemistry_ch10,chemistry_ch21"

    # Force-regenerate targets already in catalog.json (default is to skip them)
    python scripts/batch_generate.py --no-skip-existing

    # Only specific targets (concept IDs) across all/selected domains
    python scripts/batch_generate.py --include data_science,dataset

    # Skip specific targets
    python scripts/batch_generate.py --exclude arima,hipaa

    # Override level (single or comma-separated for multi-level runs)
    python scripts/batch_generate.py --level college --llm claude_cli:claude-opus-4-8
    python scripts/batch_generate.py --level intro,core,college,research

    # Language accepts ISO codes or friendly names (case-insensitive)
    python scripts/batch_generate.py --language chinese
    python scripts/batch_generate.py --language French
    python scripts/batch_generate.py --language zh
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import click
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from catalog_lock import read_catalog, update_catalog  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
SPL_WORKFLOW = REPO_ROOT / "spl"
DOMAINS_DIR = REPO_ROOT / "public" / "domains"
CATALOG_PATH = DOMAINS_DIR / "catalog.json"

# api/config.py's Settings is the single source of truth for these limits
# (CB_SPL_WHILE_MAX_ITER / CB_SPL_MAX_LLM_CALLS env vars, default 50 each) —
# the FastAPI backend (api/services/executor.py) already passes them to spl3
# this way. This script used to invoke spl3 with a bare environment, silently
# falling back to SPL.py's own hardcoded default of 15 for SPL_WHILE_MAX_ITER
# — much tighter than the backend's 50, and the actual cause of "WHILE loop
# exceeded 15 iterations" failures on longer sections that the same domain
# generates fine through the web UI.
sys.path.insert(0, str(REPO_ROOT))
from api.config import settings as _api_settings  # noqa: E402

# Maps friendly language names and aliases → ISO 639-1 codes (case-insensitive lookup).
_LANG_MAP: dict[str, str] = {
    "english":    "en",
    "chinese":    "zh",
    "mandarin":   "zh",
    "french":     "fr",
    "spanish":    "es",
    "german":     "de",
    "japanese":   "ja",
    "korean":     "ko",
    "portuguese": "pt",
    "italian":    "it",
    "russian":    "ru",
    "arabic":     "ar",
    "hindi":      "hi",
    # Common non-ISO codes — `jp` once produced a whole college.jp/ tree that
    # the app (which asks for `ja`) could never find.
    "jp":         "ja",
    "cn":         "zh",
    "kr":         "ko",
}


def _resolve_lang(raw: str) -> str:
    """Accept ISO code or friendly name, return ISO 639-1 code."""
    key = raw.strip().lower()
    if key in _LANG_MAP:
        return _LANG_MAP[key]
    # Already an ISO code (2-3 chars) or unknown — pass through as-is
    return key


# level->style mapping shared with api/services/executor.py — see
# scripts/level_style.py for the map and math-tag fallback rationale.
from level_style import LEVEL_TO_STYLE as _LEVEL_TO_STYLE, resolve_style as _resolve_style  # noqa: E402


# Maps spl3 llm strings → short model names used as folder segments.
# For ollama:{name}, the name is used directly if not listed here.
_LLM_TO_MODEL: dict[str, str] = {
    "ollama:gemma3":                    "gemma3",
    "ollama:gemma4":                    "gemma4",
    "claude_cli:claude-sonnet-5":     "sonnet",
    "claude_cli:claude-haiku-4-5-20251001": "haiku",
    "claude_cli:claude-opus-4-8":       "opus",
}


def _llm_to_model(llm: str) -> str:
    if llm in _LLM_TO_MODEL:
        return _LLM_TO_MODEL[llm]
    if llm.startswith("ollama:"):
        return llm[len("ollama:"):]
    return llm.replace(":", "_").replace("-", "_")


def _load_catalog() -> list[dict]:
    return read_catalog(CATALOG_PATH)


def _get_application_ids(domain_id: str) -> list[str]:
    """Return ordered list of application node IDs from graph.yaml."""
    graph_yaml = DOMAINS_DIR / domain_id / "input" / "graph.yaml"
    if not graph_yaml.exists():
        return []
    data = yaml.safe_load(graph_yaml.read_text())
    apps = data.get("applications") or {}
    return list(apps.keys())


def _already_generated(catalog_entry: dict, target: str, model: str, language: str, level: str) -> bool:
    variant_prefix = f"output/{level}.{language}/"
    return any(
        b["target"] == target and b.get("model") == model and b.get("language", "en") == language
        and b.get("file", "").startswith(variant_prefix)
        for b in catalog_entry.get("books", [])
    )


def _mark_generated(domain_id: str, target: str, level: str, language: str, model: str) -> None:
    """Update catalog.json after a successful generation."""
    variant = f"{level}.{language}"
    html_dir = DOMAINS_DIR / domain_id / "output" / variant / model / "html"
    # spl/tools.py's write_concept_html/build_book_index suffix every filename
    # with "_{language}" except English — match that convention when
    # recording book_file below, otherwise it points at a file that was
    # never written for any non-English generation.
    suffix = f"_{language}" if language and language != "en" else ""
    new_concepts = []
    for p in html_dir.glob("concept_*.html"):
        stem = p.stem[len("concept_"):]
        # Strip the same "_{language}" suffix write_concept_html appends to
        # the filename — otherwise a Chinese "observation" concept gets
        # named/labeled "observation_zh"/"Observation Zh", a different
        # identity from the English "observation" entry rather than the
        # same concept in a different language.
        name = stem[:-len(suffix)] if suffix and stem.endswith(suffix) else stem
        new_concepts.append({
            "name": name,
            "label": name.replace("_", " ").title(),
            "file": f"output/{variant}/{model}/html/{p.name}",
            "model": model,
        })

    def mutate(catalog: list[dict]) -> None:
        for d in catalog:
            if d["id"] != domain_id:
                continue
            books: list[dict] = d.setdefault("books", [])
            book_file = f"output/{variant}/{model}/html/book_{target}{suffix}.html"
            # Dedupe by the exact output file path (which already encodes
            # level/language/model) rather than the (target, model, language)
            # triple — that triple collided across levels: generating the
            # same target/model/language at a level different from an
            # earlier run matched the earlier run's entry and silently
            # skipped recording the new file at all.
            if not any(b.get("file") == book_file for b in books):
                books.append({"target": target, "file": book_file, "model": model, "language": language})
            d["has_book"] = True
            # Preserve every entry except the ones this exact directory glob
            # just superseded (same level/language/model). Filtering by
            # (model, language) alone — the old behavior — wiped out a
            # *different* level's already-generated concepts sharing the
            # same model/language: e.g. generating "research" level for
            # model=sonnet silently deleted the "college" level sonnet
            # entries an earlier run had recorded, even though those files
            # were untouched on disk.
            variant_dir_prefix = f"output/{variant}/{model}/html/"
            other = [
                c for c in d.get("generated_concepts", [])
                if not c.get("file", "").startswith(variant_dir_prefix)
            ]
            for c in new_concepts:
                c["language"] = language
            d["generated_concepts"] = sorted(other + new_concepts, key=lambda c: c["label"])
            break

    update_catalog(mutate, CATALOG_PATH)


# Substrings (checked lowercase) that indicate the LLM backend has hit a
# session/rate limit rather than a genuine workflow or code error.
#
# This scans *every* line of the subprocess's live output — which includes
# the LLM's own generated section text (echoed to the console as it
# streams), not just log/error lines — so generic phrases are dangerous:
# a generated section on ecology, economics, or biochemistry can
# legitimately say "fishing quotas" or discuss a reaction's "rate limiting
# step" and false-trigger an abort mid-batch (confirmed in practice: a
# Biology chapter's "Ecosystem" section describing fishery management
# quotas killed a 173-job batch after 1 real success, with the earlier,
# broader marker list here).
#
# These two are instead exactly what SPL.py's claude_cli adapter always
# wraps a real limit as before it can reach this output — see
# `raise ModelOverloaded(f"Claude CLI limit reached: {error_detail}")` in
# spl/adapters/claude_cli.py — and build_concept_book.spl has no
# `EXCEPTION WHEN ModelOverloaded` clause, so a real hit always propagates
# as an uncaught exception containing both strings verbatim. Neither has
# any plausible reason to appear in generated academic prose.
_SESSION_LIMIT_MARKERS = ("modeloverloaded", "claude cli limit reached")


class SessionLimitHit(Exception):
    """Raised when the subprocess output indicates an LLM session/rate limit."""

    def __init__(self, line: str):
        self.line = line
        super().__init__(line)


def _run_spl3(
    domain_id: str,
    target: str,
    level: str,
    style: str,
    language: str,
    model: str,
    spl_dir: Path,
    llm: str,
    skip_cache: bool,
) -> bool:
    """Run spl3 synchronously, streaming output. Returns True on success.

    Raises SessionLimitHit as soon as the output signals an LLM session/rate
    limit, terminating the subprocess immediately instead of letting it run
    to completion and print its full traceback.
    """
    output_dir = DOMAINS_DIR / domain_id / "output" / f"{level}.{language}" / model / "html"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pass the domain's own synced graph.yaml as an absolute path rather than
    # a bare "{domain_id}_graph.yaml" filename. graph_lib.load_domain()
    # resolves bare filenames relative to SPL.py's own cookbook/74_concept_book
    # directory, which requires every domain's graph to also be hand-copied
    # there; an absolute path is honored as-is and works for any domain synced
    # into public/domains/ regardless of whether a same-named copy exists in
    # SPL.py's cookbook dir (e.g. domains synced from concept-book-press's
    # ingestion pipeline, which never puts anything there).
    domain_yaml_path = DOMAINS_DIR / domain_id / "input" / "graph.yaml"

    cmd = [
        "spl3", "run", str(SPL_WORKFLOW / "build_concept_book.spl"),
        "--tools", str(SPL_WORKFLOW / "tools.py"),
        "--llm", llm,
        "--param", f"domain_yaml={domain_yaml_path}",
        "--param", f"target={target}",
        "--param", f"style={style}",
        "--param", f"language={language}",
        "--param", f"output_dir={output_dir}",
        "--param", f"skip_cache={'yes' if skip_cache else 'no'}",
        "--param", f"model={model}",
    ]

    spl_env = {
        **os.environ,
        "SPL_WHILE_MAX_ITER": str(_api_settings.spl_while_max_iter),
        "SPL_MAX_LLM_CALLS": str(_api_settings.spl_max_llm_calls),
    }

    proc = subprocess.Popen(
        cmd, cwd=str(spl_dir), env=spl_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            low = line.lower()
            if any(marker in low for marker in _SESSION_LIMIT_MARKERS):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise SessionLimitHit(line.strip())
            click.echo(line, nl=False)
    finally:
        if proc.stdout:
            proc.stdout.close()

    proc.wait()
    return proc.returncode == 0


_TRAILING_NUM = re.compile(r"^(.*?)(\d+)$")


def _expand_domain_spec(spec: str) -> list[str]:
    """Expand one --domain value into concrete domain ids.

    Supports comma-separated lists and inclusive numeric ranges written as
    "<prefix><NN>-<prefix><MM>" (same prefix, zero-padded to the left id's
    width) or "<prefix><NN>-<MM>" (bare end number). Anything that doesn't
    match a range shape is passed through unchanged.
    """
    ids = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            left, _, right = chunk.partition("-")
            left, right = left.strip(), right.strip()
            m_left = _TRAILING_NUM.match(left)
            if m_left:
                prefix, start_str = m_left.groups()
                m_right = _TRAILING_NUM.match(right)
                if m_right and m_right.group(1) == prefix:
                    end_str = m_right.group(2)
                elif right.isdigit():
                    end_str = right
                else:
                    end_str = None
                if end_str is not None:
                    start, end, width = int(start_str), int(end_str), len(start_str)
                    if start <= end:
                        ids.extend(f"{prefix}{n:0{width}d}" for n in range(start, end + 1))
                        continue
            ids.append(chunk)  # not a recognized range — treat as a literal id
        else:
            ids.append(chunk)
    return ids


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """Batch pre-generate concept books. See 'generate --help' / 'status --help'.

    A bare invocation with no subcommand (e.g. `batch_generate.py --domain X`)
    implicitly runs 'generate' for backward compatibility.
    """


@cli.command("generate", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--domain", "domains", multiple=True,
    help="Domain ID to generate (repeatable). Each value may also be a "
         "comma-separated list, and/or a range of two same-prefix "
         "zero-padded ids joined by '-' (e.g. "
         "'chemistry_ch05-chemistry_ch10,chemistry_ch21'). "
         "Default: all domains in catalog.",
)
@click.option(
    "--n-targets", default=None, type=int,
    help="Cap the number of applications generated per domain (default: all of them).",
)
@click.option(
    "--level", default=None,
    help="Comma-separated content level(s) to generate (intro/core/college/research). "
         "Default: each domain's default_level. Multiple levels run all combinations.",
)
@click.option("--language", default="en", show_default=True, help="Output language code.")
@click.option(
    "--llm", default="claude_cli:claude-sonnet-5", show_default=True,
    envvar="CB_LLM", help="LLM backend string passed to spl3.",
)
@click.option(
    "--spl-dir", default=None, type=click.Path(path_type=Path),
    envvar="CB_SPL_DIR",
    help="Path to SPL.py project root. Default: ~/projects/digital-duck/SPL.py",
)
@click.option(
    "--include", "include_targets", default=None,
    help="Comma-separated target IDs to include (default: all). Applied after --n-targets.",
)
@click.option(
    "--exclude", "exclude_targets", default=None,
    help="Comma-separated target IDs to skip.",
)
@click.option("--skip-cache", is_flag=True, help="Pass skip_cache=yes to spl3.")
@click.option(
    "--skip-existing/--no-skip-existing", default=True,
    help="Skip targets already present in catalog.json books list for this model "
         "(default: on — pass --no-skip-existing to force regeneration).",
)
@click.option("--dry-run", is_flag=True, help="Print planned jobs without running them.")
@click.option(
    "--stop-on-error", is_flag=True, default=False,
    help="Abort the batch if any single generation fails.",
)
def generate(
    domains: tuple,
    n_targets: int | None,
    level,
    language: str,
    llm: str,
    spl_dir,
    include_targets: str | None,
    exclude_targets: str | None,
    skip_cache: bool,
    skip_existing: bool,
    dry_run: bool,
    stop_on_error: bool,
) -> None:
    """Batch pre-generate concept books for multiple domains."""
    domains = tuple(dict.fromkeys(
        expanded for raw in domains for expanded in _expand_domain_spec(raw)
    ))
    if spl_dir is None:
        spl_dir = Path.home() / "projects" / "digital-duck" / "SPL.py"

    model = _llm_to_model(llm)
    language = _resolve_lang(language)
    include_set = {t.strip() for t in include_targets.split(",")} if include_targets else None
    exclude_set = {t.strip() for t in exclude_targets.split(",")} if exclude_targets else set()
    requested_levels = [l.strip() for l in level.split(",")] if level else None
    if requested_levels:
        unknown = [l for l in requested_levels if l not in _LEVEL_TO_STYLE]
        if unknown:
            click.echo(f"[warn] Unknown level(s): {', '.join(unknown)} (known: {', '.join(_LEVEL_TO_STYLE)})", err=True)

    catalog = _load_catalog()
    domain_map = {d["id"]: d for d in catalog}

    targets_domains = [d for d in catalog if not domains or d["id"] in domains]
    if domains:
        missing = set(domains) - set(domain_map)
        if missing:
            click.echo(f"[warn] Unknown domain(s): {', '.join(sorted(missing))}", err=True)

    jobs = []  # list of (domain_id, target, eff_level, style)
    seen_targets: set[str] = set()
    for entry in targets_domains:
        did = entry["id"]
        levels_for_domain = requested_levels or [entry.get("default_level", "college")]
        app_ids = _get_application_ids(did)
        if not app_ids:
            click.echo(f"[skip] {did}: no application nodes in graph.yaml")
            continue
        selected = app_ids[:n_targets] if n_targets else app_ids
        if include_set is not None:
            selected = [t for t in selected if t in include_set]
        selected = [t for t in selected if t not in exclude_set]
        for target in selected:
            seen_targets.add(target)
            for eff_level in levels_for_domain:
                style = _resolve_style(eff_level, entry.get("tags", []))
                if skip_existing and _already_generated(entry, target, model, language, eff_level):
                    click.echo(f"[skip] {did}/{target} level={eff_level} ({model}): already in catalog")
                    continue
                jobs.append((did, target, eff_level, style))

    if include_set:
        missing = include_set - seen_targets
        if missing:
            click.echo(f"[warn] --include targets not found in any domain: {', '.join(sorted(missing))}", err=True)

    if not jobs:
        click.echo("No jobs to run.")
        return

    click.echo(f"\n{'DRY RUN — ' if dry_run else ''}Planned {len(jobs)} generation job(s)  [model={model}]:\n")
    for did, target, eff_level, style in jobs:
        click.echo(f"  {did:30s}  target={target:35s}  level={eff_level:10s}  style={style}")
    click.echo()

    if dry_run:
        return

    succeeded, failed = 0, 0
    for idx, (did, target, eff_level, style) in enumerate(jobs):
        click.echo(f"{'='*70}")
        click.echo(f"GENERATING  domain={did}  target={target}  level={eff_level}  style={style}  lang={language}  model={model}")
        click.echo(f"{'='*70}")

        try:
            ok = _run_spl3(did, target, eff_level, style, language, model, spl_dir, llm, skip_cache)
        except SessionLimitHit as exc:
            click.echo(f"[FAIL] {did}/{target}: session/rate limit reached — {exc.line}", err=True)
            remaining = len(jobs) - idx - 1
            click.echo(
                f"\nAborting batch early: LLM session/rate limit hit, remaining jobs "
                f"would fail the same way. {succeeded} succeeded, {failed + 1} failed, "
                f"{remaining} not attempted.",
                err=True,
            )
            sys.exit(1)

        if ok:
            _mark_generated(did, target, eff_level, language, model)
            click.echo(f"[ok] {did}/{target} ({model}) — catalog updated")
            succeeded += 1
        else:
            click.echo(f"[FAIL] {did}/{target}", err=True)
            failed += 1
            if stop_on_error:
                click.echo("Aborting batch (--stop-on-error).", err=True)
                sys.exit(1)

    click.echo(f"\nBatch complete: {succeeded} succeeded, {failed} failed.")
    if failed:
        sys.exit(1)


@cli.command("status", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--domain", "domains", multiple=True,
    help="Restrict to these domain ids (same comma-list/range syntax as "
         "'generate --domain'). Default: all domains in catalog.json.",
)
@click.option(
    "--verbose", "-v", is_flag=True,
    help="Also list each domain's not-yet-generated target ids.",
)
def status(domains: tuple, verbose: bool) -> None:
    """Show, per domain, how many application targets have been generated."""
    domains = tuple(dict.fromkeys(
        expanded for raw in domains for expanded in _expand_domain_spec(raw)
    ))
    catalog = _load_catalog()
    domain_map = {d["id"]: d for d in catalog}
    if domains:
        missing = set(domains) - set(domain_map)
        if missing:
            click.echo(f"[warn] Unknown domain(s): {', '.join(sorted(missing))}", err=True)

    entries = [d for d in catalog if not domains or d["id"] in domains]
    if not entries:
        click.echo("No domains found in catalog.json.")
        return

    header = f"{'Domain':28s} {'Name':38s} {'Done':>5s} {'Total':>6s} {'Pending':>8s}  Models/Langs"
    click.echo(header)
    click.echo("-" * len(header))

    total_done = total_targets = 0
    for entry in entries:
        did = entry["id"]
        app_ids = _get_application_ids(did)
        books = entry.get("books", [])
        done_targets = sorted({b["target"] for b in books if b["target"] in app_ids})
        pending = [t for t in app_ids if t not in done_targets]
        variants = sorted({f"{b.get('model', '?')}/{b.get('language', 'en')}" for b in books})
        total_done += len(done_targets)
        total_targets += len(app_ids)

        name = entry.get("name", did)
        click.echo(
            f"{did:28s} {name[:38]:38s} {len(done_targets):5d} {len(app_ids):6d} "
            f"{len(pending):8d}  {', '.join(variants) or '-'}"
        )
        if verbose and pending:
            click.echo(f"    pending: {', '.join(pending)}")

    click.echo("-" * len(header))
    click.echo(
        f"{'TOTAL':28s} {'':38s} {total_done:5d} {total_targets:6d} "
        f"{total_targets - total_done:8d}"
    )


def _main() -> None:
    """Dispatch to 'generate' by default so `batch_generate.py --domain X`
    (pre-subcommand invocation style) keeps working unchanged."""
    known = {"generate", "status"}
    args = sys.argv[1:]
    if not args:
        args = ["generate"]
    elif args[0] not in known and args[0] not in ("-h", "--help"):
        args = ["generate", *args]
    cli(args=args, prog_name=Path(sys.argv[0]).name)


if __name__ == "__main__":
    _main()
