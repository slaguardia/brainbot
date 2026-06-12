"""Note-legibility analysis — the optional write-time LLM at the edge of ingest.

ONE Anthropic call per source returns BOTH halves of the feature in one pass
(segment-and-score is a single call):

- structured ``health`` — how legible-*to-agents* a note is (not how tidy it
  looks): are its ideas separable or one blob, self-describing or reference-rot,
  free of within-page repetition, dense with extractable signal.
- a structural, grounded ``rewrite`` — the freeform dump restructured into
  self-describing idea-units under markdown headings, so the heading-splitter
  (``store._split_sections``) can chunk it well instead of collapsing the whole
  page into one mushy embedding.

``analyze(raw_text, model) -> (health, rewrite)`` is SYNCHRONOUS (like ``embed``),
wrapped in ``asyncio.to_thread`` by ``upsert_source``. analyze always returns BOTH
halves; the DECISION of whether to *use* the rewrite (auto-threshold vs. manual
vs. the per-source ``'off'`` pin) belongs to the caller, which stores the rewrite
or NULLs it.

Hard guardrails — enforced by the prompt + the structured-output schema:

- **Structural, not stylistic.** Segment into idea-units, resolve dangling
  references ("I agree with that" → with *what*), dedupe within the page. Do NOT
  smooth the prose: the user's raw voice and the raw spark are the asset (this can
  be a content pipeline — weird phrasing is value, not a defect to fix).
- **Grounded — no new claims.** Every claim in the rewrite must trace to
  ``raw_text``; invent nothing. ``grounded`` is self-reported and the raw↔rewrite
  diff makes any drift auditable (v1; a real entailment checker is later
  hardening, noted not built — see docs/note-legibility.md).
- ``raw_text`` is never mutated and Notion is never written back — the rewrite is
  a derived artifact stored *beside* the source, disposable like ``chunks``.

The Anthropic SDK is a real new dependency + secret (``ANTHROPIC_API_KEY``). It is
imported lazily inside the client builder so the base brain still imports without
it; the whole feature is opt-in partly to keep the base brain free of both.
"""

from __future__ import annotations

import json
import logging
import threading

from .config import Config

logger = logging.getLogger(__name__)

# Output-token ceiling for the analysis call. 16K is the documented safe ceiling
# for a NON-streaming request (above it the SDK can time out / refuse). A page/day
# note's structural rewrite + health JSON + adaptive thinking fits comfortably; a
# pathologically huge page that truncates fails json.loads and the caller degrades
# to pass-through (logged), never a crash.
_MAX_OUTPUT_TOKENS = 16_000

# Input char budget. We never feed an unbounded page to the model. ~100K chars is
# far above any real note; a larger one is truncated (logged) so the call can't
# blow the context window. Mirrors store._EMBED_CHAR_BUDGET's defensive cap.
_INPUT_CHAR_BUDGET = 100_000

# The default model for both the health pass and the rewrite — one model, decided
# in docs/note-legibility.md (voice preservation + grounding win over a cheaper
# two-tier split at ~a page/day). The live value comes from `legibility.model`
# (settings); this is only the fallback the resolver hands us when unset.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Structured-output schema for the one call. JSON-Schema can't express numeric
# RANGES here (the API rejects minimum/maximum), so types are declared and ranges
# are clamped in _normalize_health below. Every object is closed
# (additionalProperties: false) with all keys required — structured outputs needs
# that to constrain the shape.
ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "health": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                # Overall legibility 0-100 (higher = more legible to agents).
                "score": {"type": "integer"},
                "dimensions": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        # 1 = ideas cleanly separable; 0 = one undifferentiated blob.
                        "separability": {"type": "number"},
                        # 1 = self-describing; 0 = reference-rot ("this", "that").
                        "self_containment": {"type": "number"},
                        # 1 = no within-page repetition; 0 = heavily redundant.
                        "redundancy": {"type": "number"},
                        # 1 = dense extractable content; 0 = mostly noise.
                        "signal_density": {"type": "number"},
                    },
                    "required": [
                        "separability",
                        "self_containment",
                        "redundancy",
                        "signal_density",
                    ],
                },
                # Short, actionable, per-page guidance ("dangling 'this' in para 3").
                "notes": {"type": "array", "items": {"type": "string"}},
                # The rewrite added no new claims — self-reported (see module docstring).
                "grounded": {"type": "boolean"},
            },
            "required": ["score", "dimensions", "notes", "grounded"],
        },
        # The structural restructuring of the note. Markdown headings per idea-unit
        # are REQUIRED — they are what the chunker keys on; without them the rewrite
        # would chunk no better than the raw blob.
        "rewrite": {"type": "string"},
    },
    "required": ["health", "rewrite"],
}

_SYSTEM_PROMPT = """\
You restructure a personal note so that a downstream retrieval system can chunk it \
well, and you score how legible-to-agents it already is. You are a librarian, not a \
writer or an editor: you reorganize the author's own words; you never improve, \
summarize, soften, or add to them.

You are given ONE note's text. Return JSON with two parts: `health` and `rewrite`.

REWRITE — restructure, do not rewrite:
- Split the note into self-describing idea-units. Put a short markdown heading \
(`## ...`) above each unit; the heading names the unit's topic in the author's own \
terms so the unit stands on its own. These headings are the ONLY thing the chunker \
splits on, so every distinct idea must get one.
- Resolve dangling references INSIDE the text using only what the note itself \
already says: replace a bare "this"/"that"/"it"/"the above" with the concrete thing \
it points back to, when the note makes that thing unambiguous. If it is ambiguous, \
leave it.
- Drop within-page duplication: if the same point is made twice, keep it once.
- PRESERVE THE AUTHOR'S VOICE AND WORDING. Keep their phrasing, slang, fragments, \
and raw spark verbatim wherever possible — the weird phrasing is the value, not a \
defect. Do not make the prose read nicely, do not standardize tone, do not expand \
abbreviations. Structure changes; words do not.
- GROUNDING IS ABSOLUTE: invent NOTHING. Every sentence in the rewrite must trace \
to something already in the note. Add no facts, no inferences, no conclusions, no \
transitions that assert anything new. If you cannot place a fragment, keep it under \
a heading rather than dropping or "fixing" it. Set `grounded` to false only if you \
could not avoid introducing something not in the source.
- If the note is already well-structured, the rewrite may be nearly identical to \
the input — that is fine. Return the note's content faithfully either way.

HEALTH — score the ORIGINAL note (not your rewrite):
- `dimensions` (each 0.0-1.0): `separability` (are ideas separable, or one blob?), \
`self_containment` (self-describing, or reference-rot?), `redundancy` (1.0 = no \
within-page repetition), `signal_density` (extractable content vs. noise).
- `score` (0-100): overall legibility to an agent, consistent with the dimensions \
(a blobby, reference-heavy dump scores low; a clean, self-contained note scores high).
- `notes`: a few short, concrete, actionable items the author could act on \
("idea about X and idea about Y are merged into one paragraph", "'this' in the \
third line has no antecedent"). Empty list if the note is already legible.
"""


_client_singleton = None
_client_lock = threading.Lock()


def _client():
    """Process-wide Anthropic client, built lazily. Missing key fails loud — but
    the caller (`upsert_source`) only reaches analyze() when
    `settings._effective_legibility` already confirmed the key is present, so in
    practice this RuntimeError is a defensive backstop, not the live degrade path
    (that one is in the resolver: 'enabled but no key' -> pass-through)."""
    global _client_singleton
    cfg = Config()
    if not cfg.anthropic_api_key:
        raise RuntimeError("missing required env: ANTHROPIC_API_KEY")
    if _client_singleton is None:
        # analyze() runs under asyncio.to_thread, so concurrent first-callers can
        # race — a double-checked lock keeps the single-client invariant real.
        with _client_lock:
            if _client_singleton is None:
                import anthropic  # lazy: the base brain imports without this dep

                _client_singleton = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    return _client_singleton


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _normalize_health(health: dict) -> dict:
    """Clamp the model's self-reported numbers into their declared ranges (the
    structured-output schema fixes the SHAPE but can't express numeric bounds), so
    a slightly-off score never poisons the stored signal. Shape is already
    guaranteed by the schema; this only coerces/bounds."""
    dims = health["dimensions"]
    return {
        "score": int(_clamp(round(health["score"]), 0, 100)),
        "dimensions": {
            k: round(_clamp(float(dims[k]), 0.0, 1.0), 4)
            for k in ("separability", "self_containment", "redundancy", "signal_density")
        },
        "notes": [str(n) for n in health["notes"]],
        "grounded": bool(health["grounded"]),
    }


def analyze(raw_text: str, model: str = DEFAULT_MODEL) -> tuple[dict, str]:
    """Run the one analysis call → (health, rewrite).

    `health` is the normalized structured signal; `rewrite` is the structural,
    grounded restructuring (markdown-headed idea-units in the author's own words).
    Synchronous — wrap with asyncio.to_thread in async callers. Raises on a missing
    key, an API failure, or an unparseable/truncated response; `upsert_source`
    catches that and degrades to pass-through so analysis never crashes ingest.
    """
    text = raw_text or ""
    if len(text) > _INPUT_CHAR_BUDGET:
        logger.warning(
            "legibility input %d chars exceeds budget %d; truncating",
            len(text),
            _INPUT_CHAR_BUDGET,
        )
        text = text[:_INPUT_CHAR_BUDGET]

    client = _client()
    # Adaptive thinking + structured output: voice-preservation and grounding are
    # judgment-heavy, so let the model think; the json_schema format pins the
    # return shape. (Both are supported together on claude-sonnet-4-6.)
    resp = client.messages.create(
        model=model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
    )
    if resp.stop_reason == "max_tokens":
        # The JSON is almost certainly truncated -> json.loads will raise below; say
        # why first so the pass-through degrade is diagnosable.
        logger.warning("legibility: response hit max_tokens (%d); output likely truncated", _MAX_OUTPUT_TOKENS)
    payload = next((b.text for b in resp.content if b.type == "text"), None)
    if not payload:
        raise RuntimeError("legibility: model returned no text block")
    data = json.loads(payload)
    return _normalize_health(data["health"]), data["rewrite"]
