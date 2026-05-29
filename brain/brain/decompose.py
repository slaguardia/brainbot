"""LLM decomposer — raw capture text -> graphiti-ready rewrite + atomic facts.

Why this exists: graphiti's extractor works on named-subject, domain-explicit
statements, not first-person preference prose. The decomposer rewrites input
so the extractor can do its job, and emits atomic-fact sentences that each
extract cleanly. Validated in the Phase 2 spike (scripts/spike_decompose.py
was the prototype; this is the productionized version).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from anthropic import AsyncAnthropic


@dataclass
class Decomposition:
    topic: str
    body: str
    facts: list[str]


SYSTEM_PROMPT = """You are preprocessing raw text that a person has captured into their personal knowledge graph (the "brain"). Your output gets fed to a downstream entity-extraction system that pulls out entities and relationships. Your job is to make that extraction comprehensive and unambiguous.

Produce three things from the input:

## 1. topic (short string)
A 3-8 word sentence-case label usable as an episode title. E.g. "Target role goals and preferences".

## 2. body (one paragraph)
Rewrite the input as a single clean paragraph:
- Replace first-person pronouns (I, me, my) with the writer's name: "{user_name}". Every sentence has an explicit named subject. Keep other named people as-is.
- Disambiguate vague nouns by domain ("velocity" -> "iteration velocity at work" / "training velocity in his running"). This stops the brain conflating concepts across life domains.
- First sentence names the domain ("{user_name} describes his goals for his next professional role.").
- Preserve all factual content. No invented facts. No markdown — continuous prose.

## 3. facts (list of atomic-fact sentences)
Single self-contained sentences, one fact each, that the extractor will turn into clean subject-predicate-object triples:
- Subject explicit and named (usually "{user_name}", or another named person/org).
- One predicate per sentence (split compounds).
- Object concrete and named ("iteration velocity" not "speed").
- Include domain context when a concept could be confused across domains.
- HIGH RECALL: extract every distinct preference, value, goal, constraint, opinion, attribute, history fact, relationship, or capability. A 100-word paragraph may yield 15-25 facts.
- No facts not present in the input.

## Output
ONLY a JSON object, no preamble, no code fences:
{"topic": "...", "body": "...", "facts": ["...", "..."]}"""


async def decompose(
    client: AsyncAnthropic, model: str, user_name: str, raw_text: str
) -> Decomposition:
    system = SYSTEM_PROMPT.replace("{user_name}", user_name)
    msg = await client.messages.create(
        model=model,
        max_tokens=2048,
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
    return Decomposition(
        topic=data.get("topic", "").strip() or "Capture",
        body=data.get("body", "").strip(),
        facts=[f.strip() for f in (data.get("facts") or []) if f.strip()],
    )
