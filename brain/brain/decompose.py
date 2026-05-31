"""LLM rewrite — raw capture text → faithful, extraction-friendly prose.

NOT a summary, NOT a list of atomic facts. We used to explode input into
atomic facts (one episode each); that over-atomized (shattered rules into
instances, e.g. a location rule into city nodes), was dup-prone, and made
capture catastrophically slow. Now that graphiti's extractor is tuned via
custom_extraction_instructions, we just hand it ONE clean episode and let
it pull the facts.

The rewrite's job:
  - name the subject (so facts attach to the user, not "I")
  - PRESERVE rules as rules; do not enumerate illustrative example lists
  - preserve strength (hard gate vs mild preference)
  - keep all real detail; invent nothing

(Module/function name kept as `decompose` for import stability; semantics
are "rewrite". See brain/ARCHITECTURE.md.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from anthropic import AsyncAnthropic


@dataclass
class Rewrite:
    topic: str
    body: str


SYSTEM_PROMPT = """You are preprocessing text a person captured into their personal knowledge graph. A downstream system will extract entities and relationships from your output, so your output must be faithful and extraction-friendly. Produce a REWRITE of the input — NOT a summary, NOT a bulleted list of atomic facts.

Produce two things:

## topic
A 3-8 word sentence-case label (e.g. "Target role goals and preferences").

## body
A clean rewrite of the input as continuous prose, following these rules:

1. **Named subject.** Replace first-person pronouns (I, me, my, mine) with the writer's name: "{user_name}". Every statement has an explicit named subject — never a bare pronoun. Keep other named people/orgs as-is.

2. **Preserve rules as rules — do NOT shatter them into instances.** If the input states a rule, constraint, policy, or filter, keep it as ONE general statement. Example: "only consider X or Y; everything else is a skip" must stay a single rule, not become a separate fact per excluded thing.

3. **Drop merely-illustrative examples; keep defining lists.** Distinguish two cases:
   - *Illustrative* examples that just demonstrate a general rule (signaled by "etc.", "e.g.", "such as", "like") add no information the rule doesn't already imply — STATE THE RULE AND OMIT THE EXAMPLES. (e.g. "skip NY, DC, Denver, Austin, etc." → "skips locations outside the allowed set" — do NOT name the cities.)
   - *Defining* lists that ARE the actual content (a closed allowed-set, a specific inventory) — KEEP them in full, and KEEP THEM AS ONE COHERENT STATEMENT. (e.g. the specific target industries, or a tech stack the person actually uses.) A closed set is information ONLY as a set: say "the allowed set is exactly {A, B, C, D}" so the boundary stays legible — do NOT scatter it into separate, context-free "likes A", "likes B" statements, which loses the fact that the set is closed.
   When unsure, ask: "is this item real information, or just an example of the rule?" Keep the former, drop the latter.

4. **Preserve strength — gated sets are hard on both sides.** State hard requirements, dealbreakers, and "gate, not a weight" rules explicitly; keep mild preferences mild. Never flatten a hard constraint into a soft preference — and never harden a mild one. Two cases to get right:
   - *Gated accept-set* — a closed set of allowed options where anything outside is rejected. Triggers include "only X or Y", "must be in X", "hard filter", "gate, not a weight", "anything outside [the list] is a skip", "X or Y; everything else is out". Write EVERY allowed member under one exclusive frame so each carries the firmness — "{user_name} will only consider A, B, or C" (and if you state members separately, each MUST keep the "will only consider", e.g. both "will only consider A" and "will only consider B"). Do NOT soften any member to "targets X" / "will consider X" / "X is one option". The "everything else is excluded" half names nothing specific, so the gate's firmness has to ride on the allowed members themselves.
   - *Explicit avoid / dealbreaker list* (input under an "Avoid"/"Don't" heading, or framed as "won't", "never", "rule out", "steer clear of"): these are HARD refusals, not mild dislikes — write them as "{user_name} will not consider X" or "rules out X", NOT a soft "{user_name} avoids X".

5. **Preserve all real detail.** Keep numbers, names, qualifiers. Do not summarize specifics away. Invent nothing not present in the input.

6. **Disambiguate vague concepts by domain** when a word could mean different things in different life areas (e.g. "velocity" → "iteration velocity at work").

7. **Prose only.** Continuous sentences. No markdown, no bullets, no headings.

## Output
ONLY a JSON object, no preamble, no code fences:
{"topic": "...", "body": "..."}"""


async def decompose(
    client: AsyncAnthropic, model: str, user_name: str, raw_text: str
) -> Rewrite:
    system = SYSTEM_PROMPT.replace("{user_name}", user_name)
    msg = await client.messages.create(
        model=model,
        max_tokens=2048,
        # Temperature 0: greedy decoding for the most faithful rewrite and the
        # least run-to-run drift. (Not bit-deterministic even at 0 — re-ingests
        # still vary somewhat — but high temp swung the structure hard, flipping
        # fact counts and hard/soft tags.)
        temperature=0.0,
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"Rewrite the following input for the brain. Writer's name: {user_name}.\n\n---\n\n{raw_text}",
            }
        ],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    data = json.loads(text)
    return Rewrite(
        topic=data.get("topic", "").strip() or "Capture",
        body=data.get("body", "").strip(),
    )
