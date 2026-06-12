"""Note-legibility layer — the opt-in write-time LLM at the edge of ingest.

These tests pin the guarantees that make the feature safe to ship off-by-default:

- With it disabled, ingest output is byte-identical to the base brain.
- With it on, a headingless dump chunks into multiple self-describing units.
- The analysis-hash cache makes re-ingest of unchanged content reuse the stored
  analysis instead of re-running the LLM (idempotency).
- The three rewrite triggers (auto / manual-force / 'off' pin) behave as specified.
- map() carries the health score; doc() stays verbatim.
- The config seam: validate() never requires the LLM key, and 'enabled but no key'
  degrades to pass-through.

The Anthropic call itself is faked everywhere (deterministic structural splitter),
exactly as the Voyage embedder is — the live model's voice/grounding quality is a
Phase-3 eval concern, not a unit-test one. The analyzer's MECHANICAL contract
(parse + clamp the structured response) is covered with a mocked SDK client.
"""

from __future__ import annotations

import asyncio

import asyncpg
import pytest
from pgvector.asyncpg import register_vector

from brain import store
from brain.settings import (
    LEGIBILITY_ENABLED_KEY,
    LEGIBILITY_MODE_KEY,
    LEGIBILITY_THRESHOLD_KEY,
    set_setting,
)

# A headingless three-idea dump: the canonical case the feature targets. With
# legibility off it collapses to ONE chunk (the whole-page average embedding the
# spec calls "mushy"); with the rewrite on it becomes three.
DUMP = "first idea about apples\nsecond idea about bananas\nthird idea about cherries"
DUMP_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


class FakeAnalyze:
    """Deterministic stand-in for legibility.analyze: turns each non-empty line
    into its own ``## heading`` idea-unit (so the chunker splits it), reports a
    fixed health score, and counts calls (to prove the analysis-hash cache)."""

    def __init__(self, score: int = 10):
        self.score = score
        self.calls = 0

    def __call__(self, raw_text: str, model: str = "fake-model"):
        self.calls += 1
        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        rewrite = "\n\n".join(f"## {ln.split()[-1]}\n{ln}" for ln in lines)
        health = {
            "score": self.score,
            "dimensions": {
                "separability": 0.2,
                "self_containment": 0.3,
                "redundancy": 0.9,
                "signal_density": 0.5,
            },
            "notes": ["three ideas merged into one blob"],
            "grounded": True,
        }
        return health, rewrite


# ---- low-level helpers: drive the store directly with a short-lived pool ------
# (mirrors conftest.seed — own pool, own loop, never shares the client's)


def _run(dsn: str, coro_factory):
    async def _go():
        pool = await asyncpg.create_pool(dsn, init=register_vector)
        try:
            return await coro_factory(pool)
        finally:
            await pool.close()

    return asyncio.run(_go())


def _ingest(dsn, *, force_rewrite=False, source_id=DUMP_ID, text=DUMP, title="Dump", path="Dump"):
    async def _c(pool):
        return await store.upsert_source(
            pool,
            kind="notion_page",
            title=title,
            raw_text=text,
            path=path,
            source_id=source_id,
            force_rewrite=force_rewrite,
        )

    return _run(dsn, _c)


def _row(dsn, source_id=DUMP_ID):
    async def _c(pool):
        return await pool.fetchrow(
            "SELECT rewrite_text, health, analysis_hash, rewrite_policy FROM sources WHERE id=$1::uuid",
            source_id,
        )

    return _run(dsn, _c)


def _chunks(dsn, source_id=DUMP_ID):
    async def _c(pool):
        return await pool.fetch(
            "SELECT heading, text FROM chunks WHERE source_id=$1::uuid ORDER BY position",
            source_id,
        )

    return _run(dsn, _c)


def _set_policy(dsn, policy, source_id=DUMP_ID):
    async def _c(pool):
        await pool.execute(
            "UPDATE sources SET rewrite_policy=$2 WHERE id=$1::uuid", source_id, policy
        )

    return _run(dsn, _c)


@pytest.fixture
def legible(clean_db, fake_embed, monkeypatch):
    """Enable the feature for a test: provision a (fake) API key, install the
    deterministic analyzer, and turn on legibility.enabled. Cleans the legibility
    settings on teardown so the next test sees the default (off) — clean_db only
    truncates sources, not settings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    fake = FakeAnalyze()
    monkeypatch.setattr(store, "analyze", fake)

    def enable(*, mode="auto", threshold=60):
        async def _c(pool):
            await set_setting(pool, LEGIBILITY_ENABLED_KEY, "true")
            await set_setting(pool, LEGIBILITY_MODE_KEY, mode)
            await set_setting(pool, LEGIBILITY_THRESHOLD_KEY, str(threshold))

        _run(clean_db, _c)
        return clean_db

    yield enable, fake

    async def _cleanup(pool):
        await pool.execute(
            "DELETE FROM settings WHERE key IN ($1,$2,$3)",
            LEGIBILITY_ENABLED_KEY,
            LEGIBILITY_MODE_KEY,
            LEGIBILITY_THRESHOLD_KEY,
        )

    _run(clean_db, _cleanup)


# ---- the schema + the guardrails ---------------------------------------------


def test_schema_has_legibility_columns(clean_db):
    async def _c(pool):
        rows = await pool.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='sources'"
        )
        return {r["column_name"] for r in rows}

    cols = _run(clean_db, _c)
    assert {"rewrite_text", "health", "analysis_hash", "rewrite_policy"} <= cols


def test_disabled_is_byte_identical(clean_db):
    """With legibility off (the default — no settings rows), a headingless dump is
    ONE chunk whose text is the raw input verbatim, and all four columns are at
    their NULL/'auto' defaults. This is the base-brain behavior, unchanged."""
    _, n = _ingest(clean_db)
    assert n == 1
    chunks = _chunks(clean_db)
    assert len(chunks) == 1
    assert chunks[0]["text"] == DUMP  # verbatim, no restructuring
    row = _row(clean_db)
    assert row["rewrite_text"] is None
    assert row["health"] is None
    assert row["analysis_hash"] is None
    assert row["rewrite_policy"] == "auto"


def test_enabled_auto_rewrites_headingless_dump(legible):
    """Below threshold in auto mode: the dump is restructured into three
    self-describing chunks, and health is stored."""
    enable, fake = legible
    dsn = enable(mode="auto", threshold=60)  # fake score 10 < 60 -> rewrite fires
    _, n = _ingest(dsn)
    assert n == 3
    chunks = _chunks(dsn)
    assert [c["heading"] for c in chunks] == ["apples", "bananas", "cherries"]
    row = _row(dsn)
    assert row["rewrite_text"] is not None
    assert row["health"] is not None
    assert fake.calls == 1


def test_doc_stays_verbatim_when_rewritten(legible, client):
    """doc() is ground truth: even when chunks derive from the rewrite, the doc
    text is the raw input byte-for-byte (the rewrite is never exposed on doc)."""
    enable, _ = legible
    dsn = enable()
    _ingest(dsn)
    doc = client.get("/doc", params={"id": DUMP_ID}).json()
    assert doc["text"] == DUMP


def test_map_carries_health_score(legible, client):
    enable, fake = legible
    fake.score = 42
    dsn = enable()
    _ingest(dsn)
    [src] = [s for s in client.get("/map").json()["sources"] if s["id"] == DUMP_ID]
    assert src["health"] is not None
    assert src["health"]["score"] == 42
    assert set(src["health"]["dimensions"]) == {
        "separability",
        "self_containment",
        "redundancy",
        "signal_density",
    }


def test_analysis_hash_cache_skips_llm_on_unchanged_reingest(legible):
    """Re-ingesting identical content reuses the stored analysis — no second LLM
    call — and the chunks are stable (idempotency: no churn under consumers)."""
    enable, fake = legible
    dsn = enable()
    _ingest(dsn)
    first = [(c["heading"], c["text"]) for c in _chunks(dsn)]
    _ingest(dsn)  # same bytes
    assert fake.calls == 1  # cache hit, no re-analysis
    assert [(c["heading"], c["text"]) for c in _chunks(dsn)] == first


def test_changed_content_reanalyzes(legible):
    enable, fake = legible
    dsn = enable()
    _ingest(dsn)
    _ingest(dsn, text=DUMP + "\nfourth idea about dates")
    assert fake.calls == 2  # content moved -> hash differs -> re-analysis
    assert len(_chunks(dsn)) == 4


def test_manual_mode_analyzes_but_does_not_rewrite(legible):
    """mode='manual': health is computed on every ingest, but the rewrite is
    withheld until an explicit request — so chunks stay raw (one blob) and
    rewrite_text is NULL while health is populated."""
    enable, _ = legible
    dsn = enable(mode="manual")
    _, n = _ingest(dsn)
    assert n == 1  # no rewrite -> chunked from raw
    row = _row(dsn)
    assert row["rewrite_text"] is None
    assert row["health"] is not None  # health still stored


def test_force_rewrite_overrides_manual_mode_and_cache(legible):
    """force_rewrite (the manual-trigger path) rewrites even in manual mode and
    even on unchanged text (bypassing the hash cache)."""
    enable, fake = legible
    dsn = enable(mode="manual")
    _ingest(dsn)  # manual -> no rewrite, but analysis_hash now set
    assert _row(dsn)["rewrite_text"] is None
    _, n = _ingest(dsn, force_rewrite=True)  # same bytes, but forced
    assert fake.calls == 2  # cache bypassed
    assert n == 3
    assert _row(dsn)["rewrite_text"] is not None


def test_force_rewrite_failure_preserves_existing_rewrite(legible, monkeypatch):
    """A force_rewrite re-trigger that hits a transient LLM error on UNCHANGED text
    must keep the existing valid rewrite — not destroy it (regression guard)."""
    enable, _ = legible
    dsn = enable()
    _ingest(dsn)  # good rewrite stored
    before = _row(dsn)
    assert before["rewrite_text"] is not None

    def boom(raw_text, model="x"):
        raise RuntimeError("transient LLM error")

    monkeypatch.setattr(store, "analyze", boom)
    _, n = _ingest(dsn, force_rewrite=True)  # same bytes, analysis fails
    after = _row(dsn)
    assert after["rewrite_text"] == before["rewrite_text"]  # preserved
    assert after["health"] is not None
    assert n == 3  # still chunked from the preserved rewrite


def test_analyze_failure_on_changed_content_passes_through(legible, monkeypatch):
    """When the content changed, a failed analysis drops the now-stale rewrite and
    chunks from raw — a stale rewrite for changed text would be worse."""
    enable, _ = legible
    dsn = enable()
    _ingest(dsn)  # good rewrite for the original text

    def boom(raw_text, model="x"):
        raise RuntimeError("transient")

    monkeypatch.setattr(store, "analyze", boom)
    _, n = _ingest(dsn, text=DUMP + "\nfourth unrelated line about dates")
    after = _row(dsn)
    assert after["rewrite_text"] is None  # stale rewrite dropped
    assert after["health"] is None
    assert n == 1  # headingless changed text -> one blob from raw


def test_off_pin_is_never_rewritten(legible):
    """rewrite_policy='off' pins the page to its raw voice: no analysis runs at
    all (health AND rewrite stay NULL), even below threshold in auto mode."""
    enable, fake = legible
    dsn = enable(mode="auto", threshold=60)
    _ingest(dsn)  # first ingest rewrites
    assert _row(dsn)["rewrite_text"] is not None
    _set_policy(dsn, "off")
    calls_before = fake.calls
    _, n = _ingest(dsn, force_rewrite=True, text=DUMP + "\nnew line about dates")
    assert fake.calls == calls_before  # 'off' short-circuits before the LLM
    assert n == 1  # headingless raw text -> one blob, the deliberate pinned voice
    row = _row(dsn)
    assert row["rewrite_text"] is None  # prior rewrite cleared
    assert row["health"] is None


def test_enabled_but_no_key_degrades_to_passthrough(clean_db, monkeypatch):
    """The config seam: legibility.enabled=true with no ANTHROPIC_API_KEY behaves
    exactly like disabled (pass-through) instead of crashing ingest."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def _c(pool):
        await set_setting(pool, LEGIBILITY_ENABLED_KEY, "true")

    _run(clean_db, _c)
    try:
        _, n = _ingest(clean_db)
        assert n == 1  # no rewrite -> base chunking
        assert _row(clean_db)["health"] is None
    finally:
        _run(clean_db, lambda p: p.execute("DELETE FROM settings WHERE key=$1", LEGIBILITY_ENABLED_KEY))


# ---- analyzer mechanical contract (mocked SDK; semantic quality is Phase-3) ----

import json  # noqa: E402

from brain import legibility  # noqa: E402


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [_Block(payload)]
        self.stop_reason = stop_reason


def test_normalize_health_clamps_out_of_range():
    raw = {
        "score": 150,  # over 100
        "dimensions": {
            "separability": 2.0,  # over 1
            "self_containment": -0.5,  # under 0
            "redundancy": 0.5,
            "signal_density": 1.0,
        },
        "notes": [1, "real note"],  # coerced to str
        "grounded": 1,  # coerced to bool
    }
    out = legibility._normalize_health(raw)
    assert out["score"] == 100
    assert out["dimensions"]["separability"] == 1.0
    assert out["dimensions"]["self_containment"] == 0.0
    assert out["notes"] == ["1", "real note"]
    assert out["grounded"] is True


def test_analyze_parses_and_normalizes(monkeypatch):
    """analyze() returns (normalized health, rewrite) from the SDK's structured
    JSON, with a heading-bearing rewrite and clamped numbers — the mechanical
    contract the ingest fork relies on."""
    payload = json.dumps(
        {
            "health": {
                "score": 35,
                "dimensions": {
                    "separability": 0.2,
                    "self_containment": 0.4,
                    "redundancy": 0.9,
                    "signal_density": 0.6,
                },
                "notes": ["two ideas merged"],
                "grounded": True,
            },
            "rewrite": "## Apples\nnote about apples\n\n## Bananas\nnote about bananas",
        }
    )

    captured = {}

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp(payload)

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(legibility, "_client", lambda: _Client())

    health, rewrite = legibility.analyze("apples and bananas", model="claude-sonnet-4-6")

    assert health["score"] == 35
    assert health["grounded"] is True
    assert "## Apples" in rewrite and "## Bananas" in rewrite
    # The call was wired with the structured-output schema + the configured model.
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["output_config"]["format"]["schema"] is legibility.ANALYSIS_SCHEMA


def test_analyze_raises_on_no_text_block(monkeypatch):
    class _Messages:
        def create(self, **kwargs):
            return _Resp("ignored")  # then strip its content

    class _Client:
        messages = _Messages()

    client = _Client()
    client.messages.create = lambda **k: type("R", (), {"content": [], "stop_reason": "end_turn"})()
    monkeypatch.setattr(legibility, "_client", lambda: client)
    with pytest.raises(RuntimeError):
        legibility.analyze("x")


# ---- config seam: the secret is env, validate() stays key-agnostic ------------

from brain.config import Config  # noqa: E402


def test_validate_does_not_require_anthropic_key(monkeypatch):
    """Boot stays key-agnostic: validate() requires only VOYAGE_API_KEY, never the
    LLM key — because whether legibility is on is a runtime DB value with no pool
    at boot. Enforcement is deferred to _effective_legibility."""
    monkeypatch.setenv("VOYAGE_API_KEY", "v")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    Config().validate()  # must not raise


def test_config_reads_anthropic_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    assert Config().anthropic_api_key == "secret"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert Config().anthropic_api_key == ""  # empty string when unset, not error


# ---- manual-trigger endpoint + per-source policy (Phase 4) --------------------

ABSENT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def test_manual_rewrite_endpoint_rewrites_on_demand(legible, client, seed):
    """POST /sources/{id}/rewrite re-analyzes the stored raw_text and re-chunks
    from the rewrite, even though the page was ingested raw while legibility was
    off. doc() stays verbatim."""
    seed(title="Dump", text=DUMP, path="Dump", source_id=DUMP_ID)  # ingested raw (off)
    enable, fake = legible
    dsn = enable()
    resp = client.post(f"/sources/{DUMP_ID}/rewrite")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rewrote"] is True
    assert body["chunk_count"] == 3
    assert body["health"]["score"] == 10
    assert len(_chunks(dsn)) == 3  # now derived from the rewrite
    assert client.get("/doc", params={"id": DUMP_ID}).json()["text"] == DUMP  # verbatim


def test_manual_rewrite_409_when_globally_disabled(client, seed):
    seed(title="Dump", text=DUMP, path="Dump", source_id=DUMP_ID)
    resp = client.post(f"/sources/{DUMP_ID}/rewrite")
    assert resp.status_code == 409
    assert resp.json()["rewrote"] is False


def test_manual_rewrite_respects_off_pin(legible, client, seed):
    seed(title="Dump", text=DUMP, path="Dump", source_id=DUMP_ID)
    enable, _ = legible
    dsn = enable()
    assert client.put(
        f"/sources/{DUMP_ID}/rewrite-policy", json={"policy": "off"}
    ).json()["rewrite_policy"] == "off"
    resp = client.post(f"/sources/{DUMP_ID}/rewrite")
    assert resp.status_code == 200
    assert resp.json()["rewrote"] is False
    assert "off" in resp.json()["reason"]
    assert len(_chunks(dsn)) == 1  # untouched — still the pinned raw voice


def test_manual_rewrite_404_unknown_source(legible, client):
    enable, _ = legible
    enable()
    assert client.post(f"/sources/{ABSENT}/rewrite").status_code == 404


def test_get_rewrite_returns_stored_columns_for_diff(legible, client, seed):
    """The diff-view read surface: GET returns the stored raw vs rewrite + health
    + policy, so the dashboard can render the diff from the columns."""
    seed(title="Dump", text=DUMP, path="Dump", source_id=DUMP_ID)
    enable, _ = legible
    enable()
    client.post(f"/sources/{DUMP_ID}/rewrite")
    body = client.get(f"/sources/{DUMP_ID}/rewrite").json()
    assert body["raw_text"] == DUMP  # verbatim original
    assert body["rewrite_text"] is not None and "## apples" in body["rewrite_text"]
    assert body["health"]["score"] == 10
    assert body["rewrite_policy"] == "auto"


def test_get_rewrite_404_unknown_source(client):
    assert client.get(f"/sources/{ABSENT}/rewrite").status_code == 404


def test_rewrite_policy_validation_and_404(client, seed):
    seed(title="Dump", text=DUMP, path="Dump", source_id=DUMP_ID)
    assert client.put(
        f"/sources/{DUMP_ID}/rewrite-policy", json={"policy": "nonsense"}
    ).status_code == 400
    assert client.put(
        f"/sources/{ABSENT}/rewrite-policy", json={"policy": "off"}
    ).status_code == 404
    assert client.put(
        f"/sources/{DUMP_ID}/rewrite-policy", json={"policy": "manual"}
    ).json() == {"id": DUMP_ID, "rewrite_policy": "manual"}


# ---- legibility settings via /integrations (UI toggle, like the poll interval) -


@pytest.fixture
def integrations_clean(client):
    """Reset the legibility settings after a test so they don't leak (the settings
    table isn't truncated by clean_db)."""
    yield
    client.delete("/integrations/legibility")


def test_integrations_reports_legibility_default_off(client, integrations_clean):
    body = client.get("/integrations").json()
    assert "legibility" in body
    leg = body["legibility"]
    assert leg["enabled"] is False  # off by default
    assert leg["active"] is False
    assert set(leg) == {"enabled", "active", "mode", "threshold", "model", "has_key"}


def test_put_legibility_settings_roundtrip(client, integrations_clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # key present -> active can be true
    resp = client.put(
        "/integrations/legibility",
        json={"enabled": True, "mode": "manual", "threshold": 45},
    )
    assert resp.status_code == 200
    leg = resp.json()
    assert leg["enabled"] is True
    assert leg["active"] is True  # enabled AND key present
    assert leg["mode"] == "manual"
    assert leg["threshold"] == 45
    # GET reflects the stored values.
    assert client.get("/integrations").json()["legibility"]["threshold"] == 45


def test_put_legibility_enabled_without_key_is_inactive(client, integrations_clean, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    leg = client.put("/integrations/legibility", json={"enabled": True}).json()
    assert leg["enabled"] is True  # the toggle is on
    assert leg["has_key"] is False
    assert leg["active"] is False  # ...but it won't run -> the UI can warn


def test_put_legibility_validation(client, integrations_clean):
    assert client.put("/integrations/legibility", json={"mode": "nope"}).status_code == 400
    assert client.put("/integrations/legibility", json={"threshold": 500}).status_code == 400
    assert client.put("/integrations/legibility", json={"enabled": "yes"}).status_code == 400
    assert client.put("/integrations/legibility", json={}).status_code == 400


def test_delete_legibility_resets(client, monkeypatch):
    client.put("/integrations/legibility", json={"enabled": True, "threshold": 30})
    leg = client.delete("/integrations/legibility").json()
    assert leg["enabled"] is False
    assert leg["threshold"] == 60  # back to the default placeholder
