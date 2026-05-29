#!/usr/bin/env python3
"""Drop arbitrary text or documents into the brain.

This is the primary ingest surface for the brain — point it at text on
stdin, a file, or a directory and it calls the brain's `capture` for each
chunk. The brain decomposes the text into named-subject atomic facts and
extracts each (typed entities, relations, bi-temporal dedup).

Note: `capture` always decomposes (that's the brain's whole value-add — see
brain/README.md). For long documents, use `--split headings` so each chunk
is a reasonable size for decomposition; capture also awaits the full
pipeline (seconds per chunk), so a directory ingest runs sequentially.

The Notion migrator (migrate/notion_to_graphiti.py) is a specialized
producer of episodes; this CLI is the general-purpose one. For a
human-typed thought, a journal entry, a captured meeting note, or a
markdown document, use this. Reach for the Notion migrator only when
you want to seed structured content out of an actual Notion workspace.

Examples:
    # stdin
    echo "Met Alice at Acme today to discuss the role." | scripts/ingest.py

    # single file (episode name derived from filename)
    scripts/ingest.py notes/2026-05-25-meeting.md

    # entire directory (one episode per file)
    scripts/ingest.py journal/

    # split a long markdown by H1/H2 into multiple episodes
    scripts/ingest.py docs/spec.md --split headings

    # explicit naming
    cat raw.txt | scripts/ingest.py --name "Journal entry 2026-05-25"

Required env:
    BRAIN_URL                 e.g. http://127.0.0.1:8100 (local) or
                              https://brain.api.example.com (VPS)
    BRAIN_BEARER_TOKEN        bearer for Caddy (only on VPS)

The target graph is the brain's configured namespace (BRAIN_GROUP_ID on the
brain service) — the client no longer chooses it per-call.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "migrate"))

from graphiti_clients import BrainClient  # noqa: E402

log = logging.getLogger("ingest")


# ---------- splitters ---------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


def split_none(text: str, base_name: str) -> Iterator[tuple[str, str]]:
    """No splitting — yield one (name, body) pair."""
    yield base_name, text.strip()


def split_headings(text: str, base_name: str) -> Iterator[tuple[str, str]]:
    """Split markdown on H1/H2 boundaries. Each section becomes an episode.

    Content before the first heading becomes its own episode named
    '<base_name> - prelude' (only if non-empty after strip).

    Episodes inherit the section heading text as their name, prefixed
    with the base_name for context.
    """
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        yield base_name, text.strip()
        return

    # Prelude before the first heading
    prelude = text[: matches[0].start()].strip()
    if prelude:
        yield f"{base_name} — prelude", prelude

    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        # Include the heading line in the body so the episode is self-contained
        section = f"{m.group(0).strip()}\n\n{body}"
        yield f"{base_name} — {heading}", section


SPLITTERS = {
    "none": split_none,
    "headings": split_headings,
}


# ---------- sources -----------------------------------------------------


def read_stdin() -> str:
    text = sys.stdin.read()
    if not text.strip():
        sys.exit("stdin was empty")
    return text


def iter_files(path: Path) -> Iterator[Path]:
    """Yield every readable text-like file under path."""
    if path.is_file():
        yield path
        return
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                yield p
        return
    sys.exit(f"not a file or directory: {path}")


def derive_episode_name(path: Path | None, override: str | None) -> str:
    if override:
        return override
    if path is None:
        return f"stdin-{time.strftime('%Y-%m-%dT%H:%M:%S')}"
    # Use the file's stem (no extension), restore spaces from dashes/underscores
    return path.stem.replace("_", " ").replace("-", " ")


def derive_source_description(path: Path | None, override: str | None) -> str:
    if override:
        return override
    if path is None:
        return "stdin"
    return f"file:{path.name}"


# ---------- the actual ingest -------------------------------------------


def make_client() -> BrainClient:
    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        sys.exit("BRAIN_URL not set (e.g. http://127.0.0.1:8100)")
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if base_url.startswith("https://") and not bearer:
        log.warning(
            "BRAIN_BEARER_TOKEN is unset but BRAIN_URL is https — Caddy will 401."
        )
    return BrainClient(base_url=base_url, bearer=bearer)


def ingest_one(
    client: BrainClient,
    name: str,
    body: str,
    source_description: str,
    dry_run: bool,
) -> None:
    # name + source_description are kept for human-readable logging; the brain's
    # capture() takes only the text (it derives its own episode names from the
    # decomposition). They are not sent to the brain.
    if dry_run:
        print(f"DRY-RUN  {name}  ({len(body)} chars)  source={source_description}")
        return
    result = client.capture(body)
    print(f"captured {name}  ({len(body)} chars)  -> {result.get('episodes', '?')} episodes, {result.get('facts', '?')} facts")


# ---------- CLI ---------------------------------------------------------


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="File or directory to ingest. Omit (or pass '-') to read stdin.",
    )
    parser.add_argument(
        "--name",
        help="Override the episode name. With --split headings on a file, this "
        "becomes the prefix for each section.",
    )
    parser.add_argument(
        "--source-description",
        help="Free-text source label stored on the episode. Defaults to the "
        "filename or 'stdin'.",
    )
    parser.add_argument(
        "--split",
        choices=list(SPLITTERS),
        default="none",
        help="Chunking strategy for long content. Default: none (one episode "
        "per file / stdin invocation). 'headings' splits markdown on H1/H2.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be ingested without calling the brain.",
    )
    args = parser.parse_args()

    splitter = SPLITTERS[args.split]
    client = None if args.dry_run else make_client()

    # Resolve source(s)
    if args.path in (None, "-"):
        text = read_stdin()
        base = derive_episode_name(None, args.name)
        src = derive_source_description(None, args.source_description)
        for ep_name, ep_body in splitter(text, base):
            ingest_one(client, ep_name, ep_body, src, args.dry_run)
        return 0

    path = Path(args.path).expanduser().resolve()
    files = list(iter_files(path))
    if not files:
        sys.exit(f"no files found at {path}")

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError) as e:
            log.warning("skipping %s: %s", f, e)
            continue
        if not text.strip():
            log.info("skipping %s: empty", f)
            continue
        base = derive_episode_name(f, args.name if len(files) == 1 else None)
        src = derive_source_description(f, args.source_description)
        for ep_name, ep_body in splitter(text, base):
            ingest_one(client, ep_name, ep_body, src, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
