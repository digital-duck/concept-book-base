#!/usr/bin/env python3
"""Batch-generate concept books for a list of domains, one book per domain.

Reads a plain-text domain list (one domain id per line, '#' starts a comment,
blank lines ignored), picks each domain's capstone target (same rule the sync
script used: first application node, else the highest-tier concept), and runs
spl3 for it — same path as batch_generate.py, but driven from a file instead
of --domain flags, with a progress file for resuming a long/interrupted run
and a hard stop on Claude CLI rate limits (retrying the same wall on the next
domain wastes calls instead of avoiding it).

Catalog marking reuses batch_generate.py's _mark_generated so there is one
source of truth for what a "generated" catalog entry looks like.

Usage:
    # Test one domain first
    python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt --limit 1

    # Full run (resumable — safe to re-run after an interruption)
    python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt

    # Different model/level/language for a later pass
    python scripts/batch_gen_domains.py -f scripts/domains-college-physics.txt \\
        --model gemma4 --level core --language zh
"""
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import click
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from batch_generate import _llm_to_model, _mark_generated, _resolve_lang  # noqa: E402
from level_style import resolve_style  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SPL_WORKFLOW = REPO_ROOT / "spl"
DOMAINS_DIR = REPO_ROOT / "public" / "domains"
CATALOG_PATH = DOMAINS_DIR / "catalog.json"
DEFAULT_PROGRESS_FILE = Path(__file__).parent / "batch_gen_domains_progress.json"

# claude_cli / ollama shorthand -> the llm string spl3 expects.
_LLM_ALIASES: dict[str, str] = {
    "sonnet": "claude_cli:claude-sonnet-5",
    "haiku":  "claude_cli:claude-haiku-4-5-20251001",
    "opus":   "claude_cli:claude-opus-4-8",
    "gemma3": "ollama:gemma3",
    "gemma4": "ollama:gemma4",
}

# Claude CLI session/rate-limit signatures — seeing one means the wall applies
# to every subsequent domain too, so the whole batch stops rather than
# grinding through the rest of the list one failure at a time.
#
# Only these two — never generic phrases like "quota"/"rate limit"/"usage
# limit". This scan runs against the *entire* subprocess output, which
# includes the LLM's own generated section text as it streams to the
# console, not just log/error lines — a generic marker WILL eventually
# false-positive on legitimate content (confirmed in practice: an ecology
# section discussing fishery quotas). SPL.py's claude_cli adapter always
# wraps a real limit as `ModelOverloaded("Claude CLI limit reached: ...")`
# before it can reach this output, and build_concept_book.spl has no
# `EXCEPTION WHEN ModelOverloaded` clause, so a real hit always propagates
# as an uncaught exception containing both strings verbatim — safe and
# sufficient without the false-positive risk of broader wording.
_RATE_LIMIT_MARKERS = ("ModelOverloaded", "Claude CLI limit reached")


# spl3's built-in safety caps (15 WHILE iterations, 25 LLM calls, 100k tokens)
# are sized for small demos: build_concept_book.spl's section loop iterates
# once per concept and can make up to 3 LLM calls per concept (write + two
# conditional refines), so a 25-node chapter blows through all three. The web
# UI raises them via .env's CB_SPL_* settings; an unattended batch run gets
# these defaults instead. Values already exported in the shell win.
_SPL_CAP_DEFAULTS = {
    "SPL_WHILE_MAX_ITER": "60",
    "SPL_MAX_LLM_CALLS": "120",
    "SPL_MAX_TOTAL_TOKENS": "600000",
}


def _resolve_llm(model: str) -> str:
    return _LLM_ALIASES.get(model, model)


def _load_domains(path: Path) -> list[str]:
    domains = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            domains.append(line)
    return domains


def _capstone(domain_id: str) -> str | None:
    graph_yaml = DOMAINS_DIR / domain_id / "input" / "graph.yaml"
    if not graph_yaml.exists():
        return None
    data = yaml.safe_load(graph_yaml.read_text(encoding="utf-8"))
    apps = data.get("applications") or {}
    if apps:
        return next(iter(apps))
    concepts = data.get("concepts") or {}
    if not concepts:
        return None
    return max(concepts, key=lambda k: concepts[k].get("tier", 0))


def _domain_tags(domain_id: str) -> list[str]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else []
    entry = next((d for d in catalog if d.get("id") == domain_id), {})
    return entry.get("tags", [])


def _book_filename(target: str, language: str) -> str:
    # spl/tools.py's build_book_index suffixes the filename with "_{language}"
    # for every language except English — match it, or every non-English run
    # is reported as failed even though the book was written.
    suffix = f"_{language}" if language and language != "en" else ""
    return f"book_{target}{suffix}.html"


def _output_exists(domain_id: str, target: str, level: str, language: str, model: str) -> bool:
    path = DOMAINS_DIR / domain_id / "output" / f"{level}.{language}" / model / "html" / _book_filename(target, language)
    return path.exists() and path.stat().st_size > 500


def _load_progress(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_progress(path: Path, progress: dict) -> None:
    path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Once spl3 starts dumping a Python traceback, nothing useful follows in that
# subprocess's output — it's on its way out. Suppressing from here to EOF
# keeps a rate-limit (or any other crash) from spamming 60+ lines of stack
# frames to the console; the raw lines are still captured in full_output and,
# when --log-file is given, logged at DEBUG so nothing is actually lost.
_TRACEBACK_START = "Traceback (most recent call last):"

# Claude CLI's own message, e.g. "Claude CLI limit reached: You've hit your
# session limit · resets 11am (America/New_York)" — surfaced in the summary
# instead of the exception's stack frames.
_RATE_LIMIT_DETAIL_RE = re.compile(r"Claude CLI limit reached:\s*(.+)")


def _run_spl3(domain_id: str, target: str, level: str, style: str, language: str, model: str,
              llm: str, skip_cache: bool, log: logging.Logger,
              domain_yaml_dir: Path | None = None) -> tuple[bool, str | None]:
    """Run spl3, streaming output live (minus tracebacks) while capturing it in full.

    Returns (ok, error). error is "RATE_LIMITED: <detail>" when the batch should stop.
    """
    output_dir = DOMAINS_DIR / domain_id / "output" / f"{level}.{language}" / model / "html"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Absolute path, not a bare "{domain_id}_graph.yaml" filename — same fix
    # as batch_generate.py's _run_spl3: a bare filename is resolved by
    # graph_lib.load_domain() relative to SPL.py's own cookbook/74_concept_book
    # directory, which requires every domain to also be hand-copied there.
    # An absolute path works for any domain synced into public/domains/,
    # including ones synced from concept-book-press's ingestion pipeline,
    # which never puts anything in SPL.py's cookbook dir.
    domain_yaml_path = DOMAINS_DIR / domain_id / "input" / "graph.yaml"
    # --domain-yaml-dir lets an external orchestrator (concept-book-press's
    # publish pipeline) supply a per-domain override graph.yaml — e.g. one
    # annotated with cross-chapter concept context — without ever touching
    # this domain's own synced graph.yaml under public/domains/.
    if domain_yaml_dir is not None:
        override = Path(domain_yaml_dir) / f"{domain_id}_graph.yaml"
        if override.exists():
            domain_yaml_path = override

    cmd = [
        "spl3", "run", str(SPL_WORKFLOW / "build_concept_book.spl"),
        "--tools", str(SPL_WORKFLOW / "tools.py"),
        "--llm", llm,
        "--param", f"domain_yaml={domain_yaml_path}",
        "--param", f"target={target}",
        "--param", f"lvl={level}",
        # build_concept_book.spl has no @lvl input — @style is what actually
        # sets depth/rigor (see scripts/level_style.py); without it every
        # book silently generates at the workflow's default 'textbook' style.
        "--param", f"style={style}",
        "--param", f"language={language}",
        "--param", f"output_dir={output_dir}",
        "--param", f"skip_cache={'yes' if skip_cache else 'no'}",
        "--param", f"llm={llm}",
    ]

    env = {**_SPL_CAP_DEFAULTS, **os.environ}
    proc = subprocess.Popen(cmd, cwd=str(SPL_WORKFLOW), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=env)
    assert proc.stdout is not None
    lines: list[str] = []
    suppressing = False
    for line in proc.stdout:
        lines.append(line)
        if not suppressing and line.rstrip() == _TRACEBACK_START:
            suppressing = True
            print("       [traceback suppressed — pass --log-file to capture it]")
        if suppressing:
            log.debug(f"       {line.rstrip()}")
        else:
            print(f"       {line.rstrip()}")
    proc.wait()
    full_output = "".join(lines)

    if any(marker in full_output for marker in _RATE_LIMIT_MARKERS):
        m = _RATE_LIMIT_DETAIL_RE.search(full_output)
        return False, f"RATE_LIMITED: {m.group(1).strip()}" if m else "RATE_LIMITED"
    if proc.returncode != 0:
        return False, f"spl3 exited {proc.returncode}"

    out_file = output_dir / _book_filename(target, language)
    if not out_file.exists() or out_file.stat().st_size < 500:
        return False, f"spl3 exited 0 but {out_file.name} was not written (likely a caught exception)"

    return True, None


@click.command()
@click.option("--domains-file", "-f", required=True, type=click.Path(exists=True, path_type=Path),
              help="Text file with one domain id per line ('#' comments, blank lines ignored).")
@click.option("--model", default="sonnet", show_default=True,
              help="Shorthand (sonnet/haiku/opus/gemma3/gemma4) or a raw spl3 --llm string.")
@click.option("--level", default="college", show_default=True)
@click.option("--language", "-l", default="en", show_default=True, help="ISO code or friendly name.")
@click.option("--skip-cache", is_flag=True)
@click.option("--force", is_flag=True, help="Regenerate even if output already exists.")
@click.option("--limit", default=None, type=int, help="Only process the first N domains (e.g. for a test run).")
@click.option("--progress-file", default=DEFAULT_PROGRESS_FILE, type=click.Path(path_type=Path), show_default=True)
@click.option("--domain-yaml-dir", default=None, type=click.Path(path_type=Path),
              help="Look here first for a per-domain '{domain_id}_graph.yaml' override "
                   "before falling back to the domain's own synced graph.yaml.")
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
def main(domains_file: Path, model: str, level: str, language: str, skip_cache: bool,
         force: bool, limit: int | None, progress_file: Path, log_file: Path | None,
         domain_yaml_dir: Path | None) -> None:
    """Batch-generate concept books, one capstone target per domain."""
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    handlers: list[logging.Handler] = [console]
    if log_file:
        # DEBUG here (not INFO) so suppressed traceback lines land in the
        # file even though the console handler above filters them out.
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s  %(message)s",
                         datefmt="%H:%M:%S", handlers=handlers)
    log = logging.getLogger("batch_gen_domains")

    llm = _resolve_llm(model)
    model_dir = _llm_to_model(llm)
    language = _resolve_lang(language)

    domains = _load_domains(domains_file)
    if limit:
        domains = domains[:limit]

    log.info(f"Batch gen  domains_file={domains_file}  llm={llm}  model={model_dir}  "
              f"level={level}  lang={language}  skip_cache={skip_cache}")
    log.info(f"Items: {len(domains)}  |  Progress file: {progress_file}")
    log.info("")

    progress = _load_progress(progress_file)
    ok = skipped = failed = 0

    for domain_id in domains:
        key = f"{domain_id}|{model_dir}|{level}|{language}"

        if not force and progress.get(key) == "done":
            log.info(f"SKIP   {domain_id}  (done in progress file)")
            skipped += 1
            continue

        target = _capstone(domain_id)
        if not target:
            log.warning(f"SKIP   {domain_id}  (no capstone found — missing/empty graph.yaml?)")
            skipped += 1
            continue

        if not force and _output_exists(domain_id, target, level, language, model_dir):
            log.info(f"SKIP   {domain_id}  (output exists → target={target})")
            progress[key] = "done"
            _save_progress(progress_file, progress)
            skipped += 1
            continue

        style = resolve_style(level, _domain_tags(domain_id))
        log.info(f"Queue  {domain_id}  target={target}  style={style}")
        t0 = time.time()
        success, err = _run_spl3(domain_id, target, level, style, language, model_dir, llm, skip_cache, log,
                                  domain_yaml_dir=domain_yaml_dir)
        elapsed = time.time() - t0

        if success:
            _mark_generated(domain_id, target, level, language, model_dir)
            log.info(f"       ✓ done ({elapsed:.0f}s)")
            progress[key] = "done"
            ok += 1
        elif err and err.startswith("RATE_LIMITED"):
            detail = err.split(":", 1)[1].strip() if ":" in err else None
            log.error(f"       ✗ Claude CLI session/rate limit reached{f' — {detail}' if detail else ''} "
                      "— stopping batch early.")
            log.error(f"       {domain_id} was NOT marked done — re-run later to pick up here and beyond.")
            _save_progress(progress_file, progress)
            log.info("")
            log.info(f"Stopped early — {ok} generated, {skipped} skipped, {failed} failed, "
                      f"{len(domains) - ok - skipped - failed} not yet attempted.")
            log.info("Re-run once the limit resets; completed domains are skipped automatically.")
            sys.exit(1)
        else:
            log.error(f"       ✗ {err}")
            progress[key] = f"error: {err}"
            failed += 1

        _save_progress(progress_file, progress)

    log.info("")
    log.info(f"Batch complete — {ok} generated, {skipped} skipped, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
