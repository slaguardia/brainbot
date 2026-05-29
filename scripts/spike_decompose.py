#!/usr/bin/env python3
"""Spike: prose → graphiti-ready rewrite.

Single-purpose experiment for the Phase 2 PWA decomposer architecture.
Takes raw text on stdin (or a file path), calls Claude to rewrite it
into named-subject, context-preserving prose suitable for graphiti's
entity extractor, and prints the result + a topic label.

What this is testing:
  1. Can an LLM reliably rewrite first-person prose so the user's name
     is the subject of every statement?
  2. Can it sharpen vague concept names (e.g. "velocity") into
     domain-specific ones (e.g. "iteration velocity at work") so the
     brain doesn't conflate concepts across domains?
  3. Does the resulting text actually produce better graphiti extraction
     than the raw input?

Usage:
    # stdin
    cat goal.md | scripts/spike_decompose.py

    # file
    scripts/spike_decompose.py path/to/goal.md

    # explicit user (overrides BRAIN_USER_NAME)
    scripts/spike_decompose.py --user "Steve LaGuardia" path/to/goal.md

Env:
    ANTHROPIC_API_KEY    required. Read from compose/.env if not exported.
    BRAIN_USER_NAME      optional. Defaults to "the user" if unset.
    DECOMPOSE_MODEL      optional. Defaults to claude-sonnet-4-5.

This is NOT yet wired into the PWA. It's a standalone spike so we can
eyeball the output and decide whether the architecture is worth committing
to before touching the capture pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_ENV = ROOT / "compose" / ".env"

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"


def load_compose_env() -> None:
    """Lazy-load compose/.env into os.environ for ANTHROPIC_API_KEY.

    Same trick the graphiti container uses via env_file. We don't
    overwrite anything already set in the shell.
    """
    if not COMPOSE_ENV.exists():
        return
    for line in COMPOSE_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Override if the shell exports an empty string (Claude Code does
        # this for ANTHROPIC_API_KEY — same shadowing bug compose handles
        # via env_file).
        if key and not os.environ.get(key):
            os.environ[key] = value


SYSTEM_PROMPT = """You are preprocessing raw text that a person has captured into their personal knowledge graph (the "brain"). Your output gets fed to a downstream entity-extraction system that pulls out entities and relationships. Your job is to make that extraction comprehensive and unambiguous.

Produce three things from the input:

## 1. topic (short string)

A 3–8 word sentence-case label that could be used as an episode title in the brain. Examples: "Target role goals and preferences", "Exercise routine and training principles".

## 2. body (one paragraph)

Rewrite the input as a single, clean paragraph that follows these rules:

- **Named subject throughout.** Replace first-person pronouns (I, me, my, mine, myself) with the writer's name: "{user_name}". Every sentence has an explicit named subject, never a bare pronoun. Keep other named people as-is.
- **Unambiguous concept names.** Vague nouns that could mean different things in different domains ("velocity", "consistency", "growth", "balance") MUST be qualified — e.g. "iteration velocity at work" or "training consistency in his exercise routine". This prevents the brain from conflating concepts across life domains.
- **Domain anchor in the opening sentence.** First sentence explicitly names the domain — e.g. "{user_name} describes his goals for his next professional role."
- **Preserve all factual content.** No summarizing away details. No invented facts.
- **Declarative prose.** No bullets, no headings, no markdown. Continuous sentences.

## 3. facts (list of atomic-fact sentences)

A list of single, self-contained sentences. Each sentence states ONE fact — one subject, one relationship, one concept/object. These will be sent individually to the entity-extraction system, so each must read as a clean standalone statement.

Rules for each fact sentence:

- **Subject is explicit and named.** Usually "{user_name}", or another named person/organization from the input.
- **One predicate per sentence.** No compound predicates. "Steve values X and prefers Y" → split into two facts.
- **Object is concrete.** If the original idea is abstract, name it explicitly — "Steve LaGuardia values iteration velocity" not "Steve values speed."
- **Domain context included when needed.** If the concept could be confused with one from another domain, add the context — "in his work environment", "in his exercise routine", etc.
- **Comprehensive coverage.** Aim for HIGH RECALL. Extract every distinct preference, value, goal, constraint, opinion, claim, attribute, history fact, relationship, or capability mentioned in the input. A 100-word paragraph might produce 15–25 facts. Err on the side of extracting more, not less.
- **One sentence per fact, no commentary.** Just the sentence.
- **No facts not present in the input.** If you're not certain something was stated, don't include it.

Example for input "I value velocity through iteration and I'm mission-driven, looking at B2B companies":

```
"Steve LaGuardia values iteration velocity in his work environment.",
"Steve LaGuardia values eliminating organizational drag.",
"Steve LaGuardia is mission-driven.",
"Steve LaGuardia is looking at business-to-business companies."
```

## Output

ONLY a JSON object with no preamble, no code fences, no commentary:

{"topic": "...", "body": "...", "facts": ["...", "...", ...]}"""


def call_claude(api_key: str, model: str, user_name: str, raw_text: str) -> dict:
    system = SYSTEM_PROMPT.replace("{user_name}", user_name)
    body = {
        "model": model,
        "max_tokens": 2048,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": f"Rewrite the following input for the brain. Writer's name: {user_name}.\n\n---\n\n{raw_text}",
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    r = requests.post(ANTHROPIC_API, headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        sys.exit(f"Anthropic API {r.status_code}: {r.text}")
    payload = r.json()
    # Sonnet returns content blocks; we want the text from the first text block.
    blocks = payload.get("content", [])
    text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
    if not text:
        sys.exit(f"empty response from Claude: {payload}")
    # Strip any code-fence wrapping the model might emit anyway.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # drop first and last fence lines
        cleaned = "\n".join(cleaned.splitlines()[1:-1]).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        sys.exit(f"Claude returned non-JSON: {e}\n---\n{text}")


def read_input(path: str | None) -> str:
    if path in (None, "-"):
        text = sys.stdin.read()
        if not text.strip():
            sys.exit("stdin was empty")
        return text
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        sys.exit(f"not a file: {p}")
    return p.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", nargs="?", help="File to read, or '-' for stdin (default)")
    parser.add_argument(
        "--user",
        help="Writer's name. Overrides BRAIN_USER_NAME. Defaults to 'the user' if neither is set.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print only the rewritten body (no topic, no JSON). For piping into ingest.py.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the structured JSON {topic, body, facts}. For piping into the ingest test.",
    )
    args = parser.parse_args()

    load_compose_env()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("sk-ant-xxxxxx"):
        sys.exit("ANTHROPIC_API_KEY not set (checked env + compose/.env)")
    user_name = args.user or os.environ.get("BRAIN_USER_NAME") or "the user"
    model = os.environ.get("DECOMPOSE_MODEL", DEFAULT_MODEL)

    raw = read_input(args.path)

    result = call_claude(api_key, model, user_name, raw)

    if args.raw:
        print(result.get("body", "").strip())
        return 0
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    facts = result.get("facts", []) or []
    print("=" * 72)
    print(f"TOPIC: {result.get('topic', '(none)')}")
    print(f"USER:  {user_name}")
    print(f"MODEL: {model}")
    print("=" * 72)
    print()
    print("BODY:")
    print(result.get("body", "").strip())
    print()
    print("=" * 72)
    print(f"FACTS ({len(facts)}):")
    for i, fact in enumerate(facts, 1):
        print(f"  {i:>2}. {fact}")
    print()
    print("=" * 72)
    print(f"input chars:  {len(raw.strip())}")
    print(f"body chars:   {len(result.get('body', '').strip())}")
    print(f"facts count:  {len(facts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
