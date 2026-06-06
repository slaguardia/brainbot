#!/usr/bin/env python3
"""Check that every relative markdown link in the repo resolves to a real file.

Run from the repo root (CI or pre-commit):  python3 scripts/check_doc_links.py
Exits 1 and lists the broken links if any markdown file points at a path that
doesn't exist (anchors are not validated, only file targets).
"""
import glob
import os
import re
import sys

LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:")


def main() -> int:
    bad: list[str] = []
    for md in glob.glob("**/*.md", recursive=True):
        if "node_modules" in md or md.startswith((".git/", ".claude/worktrees/")):
            continue
        base = os.path.dirname(md)
        with open(md, encoding="utf-8") as f:
            text = f.read()
        for m in LINK.finditer(text):
            target = m.group(1)
            if target.startswith(SKIP_PREFIXES):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, target))):
                bad.append(f"{md}: {target}")
    if bad:
        print("Broken markdown links:", *bad, sep="\n  ")
        return 1
    print("All markdown links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
