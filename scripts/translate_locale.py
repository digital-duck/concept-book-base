#!/usr/bin/env python3
"""LLM-draft a language into locales/ui.yaml or locales/content.yaml.

Finds every key missing the target language, asks an LLM to translate it in
batches (with the source text, any existing translations as extra references,
and — for concept labels — the concept's `defines` from graph.yaml as
context), validates each answer, and writes it back **in place**: ruamel.yaml
keeps the files' comments, order and block style, so the diff is just one new
`<lang>:` line per key. See docs/DEV/readme-i18n.md §2a.

For ui.yaml, the language is registered under `_meta.languages` with
`status: machine`; the top-bar picker hides it until a reviewer changes that to
`reviewed` (or appConfig.showMachineLocales is set). For content.yaml, run
scripts/apply_content_locale.py afterwards (and re-render graph.html) so the app
and SPL see the labels.

Usage:
    python scripts/translate_locale.py --file ui --lang ja --name 日本語
    python scripts/translate_locale.py --file content --lang ja
    python scripts/translate_locale.py --file ui --lang ja --dry-run      # show the first prompt
    python scripts/translate_locale.py --file ui --lang ja --only panel. --limit 5 \\
        --output /tmp/ui.ja.yaml                                            # small trial

LLM: --llm claude_cli (default; the local `claude` CLI, no API key) or
--llm anthropic (SDK; ANTHROPIC_API_KEY or CB_ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, LiteralScalarString

ROOT = Path(__file__).resolve().parent.parent
FILES = {"ui": ROOT / "locales" / "ui.yaml", "content": ROOT / "locales" / "content.yaml"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Short model aliases for --llm anthropic (the claude CLI accepts them as-is).
ANTHROPIC_MODELS = {
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-5-5",
}

PROMPT = """You are translating the text of a learning web app ("concept-book") into {lang_name} (language code "{lang}").

Rules:
- Translate the "{source}" text of each item. Other languages given are references only.
- Keep every {{placeholder}} exactly as written, untranslated (e.g. {{nodes}}, {{lang}}).
- Keep HTML tags, attributes, URLs, code, command lines and product names (concept-book, SPL.py, API, PDF, LLM, Ollama) unchanged.
- Keep line breaks where the source has them.
- UI strings: short and natural, as a native speaker would expect on a button, label or hint.
- Concept labels (ids starting "concepts."): a concise display name for a node in a concept graph; use the
  established term in {lang_name} (for Traditional Chinese Medicine terms, the usual {lang_name} term). The
  "context" field is the concept's definition, for disambiguation only — do not translate it.
- Describe traditional-medicine ideas neutrally; never add praise such as "wisdom" or "time-tested".

Return ONLY a JSON object mapping each item's "id" to its translation — no commentary, no code fence.

Items:
{items}
"""


def _yaml() -> YAML:
    # Same settings the files round-trip byte-identically under.
    y = YAML()
    y.preserve_quotes = True
    y.width = 10**9
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _leaves(node, path=()):
    """Yield (path, mapping) for each {lang: text} leaf (all values strings)."""
    for k, v in node.items():
        if path == () and k == "_meta":
            continue
        if isinstance(v, dict):
            if v and all(isinstance(x, str) for x in v.values()):
                yield path + (k,), v
            else:
                yield from _leaves(v, path + (k,))


def _concept_context() -> dict[str, str]:
    """Concept id → `defines`, from every domain's graph.yaml (first one wins)."""
    import yaml
    ctx: dict[str, str] = {}
    for gy in sorted((ROOT / "public" / "domains").rglob("input/graph.yaml")):
        graph = yaml.safe_load(gy.read_text(encoding="utf-8")) or {}
        for section in ("primitives", "concepts", "applications"):
            for nid, attrs in (graph.get(section) or {}).items():
                if (attrs or {}).get("defines"):
                    ctx.setdefault(nid, " ".join(str(attrs["defines"]).split()))
    return ctx


def _ask_claude_cli(prompt: str, model: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # allow a nested run
    res = subprocess.run(["claude", "-p", "--model", model], input=prompt, capture_output=True,
                         text=True, env=env, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({res.returncode}): {res.stderr.strip()[:500]}")
    return res.stdout


def _ask_anthropic(prompt: str, model: str) -> str:
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CB_ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(model=ANTHROPIC_MODELS.get(model, model), max_tokens=16000,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if b.type == "text")


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in LLM reply: {text[:300]!r}")
    return json.loads(text[start:end + 1])


def _styled(value: str, like):
    """Match the source scalar's style: a `|` block stays a block; other text
    with line breaks is double-quoted (\\n escapes) rather than wrapped."""
    if isinstance(like, LiteralScalarString):
        return LiteralScalarString(value if value.endswith("\n") else value + "\n")
    if "\n" in value:
        return DoubleQuotedScalarString(value)
    return value


@click.command()
@click.option("--file", "which", type=click.Choice(sorted(FILES)), required=True,
              help="ui = locales/ui.yaml, content = locales/content.yaml")
@click.option("--lang", required=True, help="Target language code, e.g. ja")
@click.option("--name", help="Native display name for the picker (ui.yaml _meta), e.g. 日本語")
@click.option("--llm", type=click.Choice(["claude_cli", "anthropic"]), default="claude_cli",
              show_default=True)
@click.option("--model", default="sonnet", show_default=True)
@click.option("--batch", default=40, show_default=True, help="Keys per LLM call")
@click.option("--only", "only", default="", help="Only keys starting with this dotted prefix")
@click.option("--limit", type=int, help="At most this many keys (for a trial run)")
@click.option("--force", is_flag=True, help="Re-translate keys that already have the language")
@click.option("--dry-run", is_flag=True, help="Print the first prompt; no LLM call, no write")
@click.option("--output", type=click.Path(path_type=Path),
              help="Write here instead of in place (e.g. to review a trial)")
def main(which, lang, name, llm, model, batch, only, limit, force, dry_run, output):
    path = FILES[which]
    y = _yaml()
    data = y.load(path.read_text(encoding="utf-8"))
    meta = data.get("_meta") or {}
    source = meta.get("source", "en")
    if lang == source:
        sys.exit(f"--lang {lang} is the source language")

    languages = meta.get("languages") or {}
    lang_name = name or (languages.get(lang) or {}).get("name") or lang
    if which == "ui" and lang not in languages and not name:
        sys.exit(f"{lang} is new to ui.yaml — pass --name (its native display name, e.g. 日本語)")

    pending = [(p, leaf) for p, leaf in _leaves(data)
               if ".".join(p).startswith(only) and source in leaf and (force or lang not in leaf)]
    if limit:
        pending = pending[:limit]
    click.echo(f"{path.relative_to(ROOT)}: {len(pending)} key(s) to translate into {lang} ({lang_name})")
    if not pending:
        return

    context = _concept_context() if which == "content" else {}
    ask = _ask_claude_cli if llm == "claude_cli" else _ask_anthropic
    done = skipped = 0
    for i in range(0, len(pending), batch):
        chunk = pending[i:i + batch]
        items = []
        for p, leaf in chunk:
            item = {"id": ".".join(p), **{k: str(v) for k, v in leaf.items() if k != lang}}
            if p[0] == "concepts" and p[-1] in context:
                item["context"] = context[p[-1]]
            items.append(item)
        prompt = PROMPT.format(lang=lang, lang_name=lang_name, source=source,
                               items=json.dumps(items, ensure_ascii=False, indent=1))
        if dry_run:
            click.echo(prompt)
            return
        click.echo(f"  batch {i // batch + 1}: {len(chunk)} key(s) …")
        answers = _parse_json(ask(prompt, model))
        for p, leaf in chunk:
            key = ".".join(p)
            text = answers.get(key)
            want = set(PLACEHOLDER.findall(str(leaf[source])))
            if not isinstance(text, str) or not text.strip():
                click.echo(f"    ! {key}: no translation returned — skipped")
                skipped += 1
            elif set(PLACEHOLDER.findall(text)) != want:
                click.echo(f"    ! {key}: placeholders changed ({text!r}) — skipped")
                skipped += 1
            else:
                leaf[lang] = _styled(text.strip("\n") if not isinstance(leaf[source], LiteralScalarString)
                                     else text, leaf[source])
                done += 1

    if which == "ui" and lang not in languages:
        entry = CommentedMap()
        entry["name"] = lang_name
        entry["status"] = "machine"
        data["_meta"]["languages"][lang] = entry

    buf = io.StringIO()
    y.dump(data, buf)
    dest = output or path
    dest.write_text(buf.getvalue(), encoding="utf-8")
    click.echo(f"Wrote {done} translation(s) to {dest} ({skipped} skipped).")
    click.echo("Next: review them" + (", then set its _meta.languages status to `reviewed`"
                                      if which == "ui" else
                                      ", then run scripts/apply_content_locale.py and re-render graph.html")
               + "; run scripts/check_i18n.py.")


if __name__ == "__main__":
    main()
