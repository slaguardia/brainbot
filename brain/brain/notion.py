"""Notion ingest — fetch one page as {title, text, path}.

`fetch_page(url)` is the one new bit of ingest logic the substrate needs:

- **title** — the page's title property.
- **text**  — the page's block children, walked recursively and flattened to
  markdown / plain text (the canonical content the store chunks + embeds).
- **path**  — the materialized ancestry, built by walking the parent-page chain
  and joining ancestor titles with '/' (e.g. 'Career/Job Search/Target Role').
  This is the domain tree the brain inherits from Notion's nesting for free.

Talks to the official Notion REST API (Bearer NOTION_TOKEN + Notion-Version
header). Uses httpx when available (it ships transitively with the service deps),
else falls back to stdlib urllib so this module has no hard third-party dep.

Distinct errors: NotionTokenError (no token), NotionURLError (can't parse a page
id from the URL), NotionNotSharedError (Notion 404 — the integration wasn't
granted access to the page).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

from .config import Config

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# A Notion id is 32 hex chars, with or without the UUID dashes. In a page URL it's
# the trailing token (often after a slug-…-<id> or as a bare ?p=/last path segment).
_HEX32 = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


class NotionError(RuntimeError):
    """Base for Notion ingest failures."""


class NotionTokenError(NotionError):
    """NOTION_TOKEN is not configured."""


class NotionURLError(NotionError):
    """The URL has no parseable 32-hex page id."""


class NotionNotSharedError(NotionError):
    """Notion returned 404 — the page isn't shared with the integration."""


def parse_page_id(url: str) -> str:
    """Pull the 32-hex page id out of a Notion URL and return it dash-formatted.

    Accepts dashed or undashed ids; takes the LAST match so a slug that happens to
    contain hex doesn't win over the trailing id. Raises NotionURLError if none."""
    # An explicit ?p=<pageid> pointer wins: the database-row side-peek copy-link
    # form notion.so/<dbid>?v=<viewid>&p=<pageid> carries the parent DATABASE id in
    # the PATH, so the path would otherwise win over the real page. Fall back to the
    # path id (the canonical notion.so/<slug>-<pageid> link), which drops a
    # ?v=<viewid> and the #fragment (urlsplit strips it). Raises if neither has one.
    parts = urlsplit(url or "")
    matches = _HEX32.findall(parse_qs(parts.query).get("p", [""])[0])
    if not matches:
        matches = _HEX32.findall(parts.path)
    if not matches:
        raise NotionURLError(f"no Notion page id found in URL: {url!r}")
    raw = matches[-1].replace("-", "").lower()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _headers(cfg: Config) -> dict[str, str]:
    if not cfg.notion_token:
        raise NotionTokenError("missing required env: NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {cfg.notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _get(path: str, cfg: Config, *, params: dict[str, str] | None = None) -> dict:
    """GET {NOTION_API}{path} and return the parsed JSON. Maps 404 -> not-shared.

    Prefers httpx (ships transitively with the service deps); falls back to the
    stdlib so this module needs no hard third-party dependency."""
    headers = _headers(cfg)
    url = f"{NOTION_API}{path}"
    try:
        import httpx  # transitively available via the service deps
    except ImportError:
        httpx = None

    if httpx is not None:
        resp = httpx.get(url, headers=headers, params=params, timeout=30.0)
        if resp.status_code == 404:
            raise NotionNotSharedError(
                f"Notion 404 for {path} — is the integration granted access to the page?"
            )
        if resp.status_code >= 400:
            # Mirror the urllib branch: every non-404 error is a NotionError, so
            # /ingest maps it to a clean 4xx and the best-effort ancestor walk
            # (which catches NotionError) doesn't abort on a parent's non-404.
            raise NotionError(f"Notion API error {resp.status_code} for {path}")
        return resp.json()

    # stdlib fallback
    if params:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: PERF203
        if e.code == 404:
            raise NotionNotSharedError(
                f"Notion 404 for {path} — is the integration granted access to the page?"
            ) from e
        raise NotionError(f"Notion API error {e.code} for {path}") from e


# ---- title + rich-text helpers ----------------------------------------------

def _rich_text(parts: list[dict]) -> str:
    """Flatten a Notion rich_text array to plain text."""
    return "".join(p.get("plain_text", "") for p in (parts or []))


def _page_title(page: dict) -> str:
    """Extract a page's title from its properties (the title-typed property)."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _rich_text(prop.get("title", []))
    # Fallback: some objects carry a top-level title array (e.g. databases).
    if isinstance(page.get("title"), list):
        return _rich_text(page["title"])
    return ""


# ---- block tree -> markdown --------------------------------------------------

def _block_children(block_id: str, cfg: Config) -> list[dict]:
    """All children of a block/page, following pagination."""
    out: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"page_size": "100"}
        if cursor:
            params["start_cursor"] = cursor
        data = _get(f"/blocks/{block_id}/children", cfg, params=params)
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return out


def _block_to_md(block: dict, cfg: Config, depth: int = 0) -> list[str]:
    """Render a single block (and its children) to markdown lines."""
    btype = block.get("type", "")
    body = block.get(btype, {}) if btype else {}
    text = _rich_text(body.get("rich_text", [])) if isinstance(body, dict) else ""
    indent = "  " * depth
    lines: list[str] = []

    if btype == "heading_1":
        lines.append(f"# {text}")
    elif btype == "heading_2":
        lines.append(f"## {text}")
    elif btype == "heading_3":
        lines.append(f"### {text}")
    elif btype == "bulleted_list_item":
        lines.append(f"{indent}- {text}")
    elif btype == "numbered_list_item":
        lines.append(f"{indent}1. {text}")
    elif btype == "to_do":
        checked = "x" if body.get("checked") else " "
        lines.append(f"{indent}- [{checked}] {text}")
    elif btype == "quote":
        lines.append(f"> {text}")
    elif btype == "code":
        lang = body.get("language", "")
        lines.append(f"```{lang}\n{text}\n```")
    elif btype == "divider":
        lines.append("---")
    elif btype in ("child_page", "child_database"):
        # A nested sub-page/-database is a SEPARATE document (its own source). Emit
        # a reference, never inline its body — its `children` are the child's whole
        # block tree, which would bleed into this page's chunk under the wrong path.
        ref = body.get("title", "")
        if ref:
            lines.append(f"{indent}- [[{ref}]]")
    elif btype == "table_row":
        # A row's content is in `cells` (a list of rich_text arrays), not rich_text —
        # render it so table data isn't silently dropped (whole tables would vanish).
        row = " | ".join(_rich_text(cell) for cell in body.get("cells", []))
        if row.strip():
            lines.append(f"{indent}{row}")
    elif btype == "equation":
        expr = body.get("expression", "")
        if expr:
            lines.append(f"{indent}{expr}")
    elif btype in ("image", "file", "video", "pdf", "bookmark", "embed", "link_preview"):
        # The substance of a media/link block is its caption (+ url), not rich_text.
        caption = _rich_text(body.get("caption", []))
        url = (
            body.get("url")
            or (body.get("external") or {}).get("url")
            or (body.get("file") or {}).get("url")
            or ""
        )
        ref = " ".join(p for p in (caption, url) if p)
        if ref:
            lines.append(f"{indent}{ref}")
    elif text:
        # paragraph, callout, toggle, and anything else with rich_text
        lines.append(f"{indent}{text}")

    # Recurse into IN-PAGE children (toggle/list/column/synced bodies) — but never
    # into child_page/child_database, whose children are a separate document.
    if block.get("has_children") and btype not in ("child_page", "child_database"):
        for child in _block_children(block["id"], cfg):
            lines.extend(_block_to_md(child, cfg, depth + 1))
    return lines


def _page_text(page_id: str, cfg: Config) -> str:
    """Walk the page's block tree and flatten it to markdown."""
    lines: list[str] = []
    for block in _block_children(page_id, cfg):
        lines.extend(_block_to_md(block, cfg))
    return "\n".join(lines).strip()


# ---- ancestry / path ---------------------------------------------------------

def _ancestor_titles(page: dict, cfg: Config) -> list[str]:
    """Walk the parent-page chain (closest-first), returning ancestor titles
    ordered root -> ... -> immediate parent. Stops at a workspace/database/block
    parent (no further page to walk)."""
    titles: list[str] = []
    parent = page.get("parent", {})
    # Guard against pathological cycles (Notion shouldn't produce them).
    for _ in range(50):
        if parent.get("type") != "page_id":
            break
        parent_id = parent.get("page_id")
        if not parent_id:
            break
        try:
            ancestor = _get(f"/pages/{parent_id}", cfg)
        except NotionError:
            # An ancestor the integration can't read (only the leaf page was
            # shared, not its parents). Stop the walk and use the partial path —
            # the page content is what matters; the path is best-effort.
            break
        titles.append(_page_title(ancestor))
        parent = ancestor.get("parent", {})
    titles.reverse()  # root -> immediate parent
    return titles


# ---- public entrypoint -------------------------------------------------------

def fetch_page(url: str) -> dict:
    """Fetch a Notion page as {id, title, text, path, last_edited_time}.

    - id:    the dashed Notion page uuid (used as the stable source id).
    - title: the page title.
    - text:  blocks flattened to markdown (the canonical content to chunk/embed).
    - path:  ancestor titles + this page's title joined by '/'.
    - last_edited_time: Notion's real last-edited timestamp (ISO 8601), or None.

    Raises NotionTokenError / NotionURLError / NotionNotSharedError for the three
    distinct failure modes. Synchronous (stdlib- or httpx-backed) — wrap with
    asyncio.to_thread in async callers.
    """
    cfg = Config()
    if not cfg.notion_token:
        raise NotionTokenError("missing required env: NOTION_TOKEN")
    page_id = parse_page_id(url)  # raises NotionURLError on a bad URL

    page = _get(f"/pages/{page_id}", cfg)  # raises NotionNotSharedError on 404
    title = _page_title(page)
    last_edited = page.get("last_edited_time")  # Notion's real edit time (ISO 8601)
    text = _page_text(page_id, cfg)
    # Drop blank segments (an untitled page/ancestor) so we never store path=''
    # — which the scope predicate would mishandle — or an 'A//B' double slash that
    # wouldn't match a clean 'A/B' scope. Fall back to the page id if none remain.
    parts = [t.strip() for t in [*_ancestor_titles(page, cfg), title] if t and t.strip()]
    path = "/".join(parts) or page_id
    # `id` is the dashed Notion page uuid — the caller uses it as the stable
    # source id so re-ingesting the same page wipe-replaces rather than duplicates.
    return {
        "id": page_id,
        "title": title,
        "text": text,
        "path": path,
        "last_edited_time": last_edited,
    }
