# LLM config

> **Historical (graph design).** The document substrate has **no write-time
> LLM** — ingest is split + embed + insert, and the embedder (Voyage) is the only
> external call. The extraction/decomposition LLM call sites below no longer
> exist. See [`../brain/README.md`](../brain/README.md) and
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md).

Two LLM call sites, configured separately.

## Extraction (Graphiti)

Configured via the **OpenAI-compatible API**: `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `MODEL_NAME`. Defaults to OpenRouter.

The OpenAI-compatible API is the lingua franca. A downstream user can swap to OpenAI direct, Together, Groq, local Ollama, vLLM, or anything else with a config change — no code edit. OpenRouter as the default gives one signup for every major model, including Anthropic models when that's what you want.

## Chat (PWA)

Uses the Anthropic SDK directly. Tool-use streaming is the killer feature for the chat surface, and the SDK's `stream` helper is the right abstraction for it. Provider neutrality matters less here because the chat experience is intentionally Anthropic-shaped.

## Alternatives considered

- **Hard-code Anthropic SDK calls for extraction too.** Rejected — would lock downstream users into one provider for the highest-cost call in the system.
- **Co-hosted extraction model on the VPS via Ollama.** Parked. The `OPENAI_BASE_URL` plumbing already accepts `http://host.docker.internal:11434/v1`, so the path is open. CPU-only inference at typical VPS sizes is slow enough to bottleneck the capture pipeline, and an extra container isn't justified for single-tenant. Revisit when: the VPS gets a GPU, per-extraction API spend becomes the dominant cost, or privacy requirements force local inference. (Note: the embedder is a separate call site with a different tradeoff — see [embedder.md](./embedder.md).)
