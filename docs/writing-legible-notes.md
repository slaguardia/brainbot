# Writing notes your agents can read

> Optional help, **not a rule.** Capture is meant to be frictionless — open voice
> mode, ramble, dump it in Notion. You should never have to format your notes for
> a machine; that's exactly what the note-legibility layer
> ([`note-legibility.md`](./design/note-legibility.md)) is for: it restructures your dump
> so the brain can use it, without touching what you wrote. This page just explains
> what "legible to an agent" means, so the `health` score and its `notes` make
> sense — and so you can nudge a note if you ever want to.

## Why legibility ≠ tidiness

The brain chunks a page by its **own structure** so that a question about one idea
ranks that idea above everything else on the page. A long, headingless dump that
touches ten unrelated things collapses into a single chunk whose embedding is the
mushy average of all ten — it matches everything weakly and nothing strongly.
That's a *legibility* problem, not a *tidiness* one: the prose can be beautiful and
still be illegible to an agent, and it can be full of typos and fragments and still
be perfectly legible. We optimize for the second.

## The four things `health` looks at

`health` scores a note 0–100 from four sub-signals (each 0–1). The `notes` it
returns are concrete, per-page, and actionable — they point at the specific thing
costing you, not a style preference.

- **Separability** — are the distinct ideas *separable*, or fused into one blob?
  One idea per paragraph separates cleanly; five ideas in one run-on do not.
- **Self-containment** — does each part *stand on its own*, or does it lean on
  context that isn't there? "I agree with that" is reference-rot if *that* lives in
  your head, not on the page.
- **Redundancy** — is the same point made once, or three times in three places?
- **Signal density** — how much of the text is extractable content vs. filler?

## Light nudges (only if you feel like it)

None of this is required — a low-health note still gets restructured for you. But
if you want to help the rewrite (or skip it):

- **Start a new line or paragraph when you switch ideas.** This is the single
  biggest lever for *separability* — it gives the restructurer a clean seam.
- **Name the thing, once.** "The pricing idea" beats "this" when "this" is three
  paragraphs back. Helps *self-containment* without changing your voice.
- **A heading is a gift, not a chore.** If a `# heading` falls out naturally, great
  — the brain already splits on it. If not, don't force it; the rewrite adds them.
- **Keep your voice.** Weird phrasing, slang, half-thoughts — keep them. The
  rewrite preserves your words and only changes the *structure*; the raw spark is
  the asset, not a defect.

## Don't want a page touched?

Pin it to its raw voice: set its `rewrite_policy` to `off`
(`PUT /sources/{id}/rewrite-policy {"policy": "off"}`). An `off` page is never
rewritten — not on a re-sync, not below the threshold, not even by an explicit
"rewrite this page" request. Clear the pin (back to `auto`/`manual`) to re-enable.
