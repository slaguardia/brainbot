# Recipes

Recipes are how you teach the migrator about your data without baking
your domain into the headline API. The default migration ingests any
Notion database or page generically: title becomes the episode name,
properties or block text becomes the body, Graphiti's per-write entity
extraction handles routing and dedup. That's the right default for
most data.

Sometimes you have structure worth preserving — a tracker DB with
columns the agent should know about, a notes folder where you want
each H2 to become its own episode, a per-row schema where the property
names don't survive flattening well. That's when you write a recipe.

## Contract

A recipe is a callable:

```python
from migrate.notion_to_graphiti import PlannedEpisode, RecipeContext

def my_recipe(item: dict, context: RecipeContext) -> PlannedEpisode | list[PlannedEpisode] | None:
    ...
```

- `item` is the Notion row dict (when the migrator is in `database` mode)
  or the Notion page dict (when in `page` mode). It is whatever the
  Notion API returned — properties, ids, timestamps included.
- `context` is a `RecipeContext` with:
  - `notion_client` — the same `NotionClient` the migrator is using
  - `target_id` — the database or page id that was passed on the CLI
  - `kind` — `"database"` or `"page"`
  - `dry_run` — `True` when `--dry-run` was passed
- Return `None` if you want the default shape for this item; the
  migrator will fall back to its built-in flattening.
- Return a single `PlannedEpisode` for one episode per item, or a list
  if one item should produce many.

The migrator wires `notion_page_id` and `notion_last_edited` from the
PlannedEpisode you return into the idempotency log, so set them on
every episode you emit if you want re-runs to be idempotent. (The
default shape sets them automatically.)

## Wiring a recipe

Recipes live in this directory or anywhere on the Python path. Pass the
dotted `module:function` path on the CLI:

```sh
python migrate/notion_to_graphiti.py \
    --target <notion-id> --kind database \
    --recipe migrate.recipes.example_plain_page:as_one_episode \
    --dry-run
```

## Example

`example_plain_page.py` in this directory ships a trivial example:
collapse a Notion page into one episode named after the page title,
ignoring any heading-2 splits. Use it as a starting point for your own
recipes.

## What ships here

Only example recipes that demonstrate the contract. Domain-specific
recipes (your job-hunt tracker, your reading list, your contacts DB)
should live in your own fork — they encode private structure and would
not survive open-source review anyway.
