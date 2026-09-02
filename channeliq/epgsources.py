"""Saved EPG (XMLTV) sources.

The gap this closes: Providers and Wantlists both had a dedicated page to
save and reuse them, but the New Run form's "Guide (EPG)" field was a bare
text box you had to retype every single run -- the third input a run needs,
with no home of its own. Structurally near-identical to providers.py
(a name plus a URL), kept as a separate module rather than folded into
Providers because the two are used in different roles: a Provider supplies
STREAMS, an EPG source supplies GUIDE DATA, and conflating them in one
dropdown would be confusing on the New Run form where both appear side by
side.
"""
import json
import os
import time

from .wantlist import safe_name  # identical constraint: becomes a filename

STORE_FILE = "epg_sources.json"


def _path(root):
    return os.path.join(root, STORE_FILE)


def list_all(root):
    """Saved sources in PRIORITY order -- this is the order "first match
    wins" actually resolves in, everywhere: Check EPG, a re-probe's
    captured guide entry, and the export all iterate this exact list.

    Sources saved before priority existed have none recorded, and used to
    fall back to alphabetical -- which is how mybunny-epg ended up as the
    silent default ahead of open-epg and uk-guide on a real lineup, purely
    because 'm' sorts before 'o' and 'u', not because anyone chose it.
    Missing priority now sorts last rather than alphabetically, so an old
    source needs an explicit position rather than an accidental one.
    """
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    data = data if isinstance(data, list) else []
    data.sort(key=lambda s: (s.get("priority", 10 ** 6), s["name"].lower()))
    return data


def get(root, name):
    n = safe_name(name)
    return next((s for s in list_all(root) if s["name"] == n), None)


def save(root, name, url):
    n = safe_name(name)
    if not n:
        raise ValueError("invalid EPG source name")
    if not (url or "").strip():
        raise ValueError("url cannot be empty")
    items = list_all(root)
    existing = next((s for s in items if s["name"] == n), None)
    # A new source joins at the end of the priority order rather than
    # wherever it would land alphabetically -- appending is the only
    # choice that cannot silently promote something ahead of a source
    # already trusted to resolve first.
    priority = existing["priority"] if existing else len(items)
    items = [s for s in items if s["name"] != n]
    items.append({"name": n, "url": url.strip(), "saved": time.time(),
                 "priority": priority})
    _write(root, items)
    return n


def reorder(root, names):
    """Reassign priority 0..n-1 to match `names`' order. Anything not
    named keeps its relative order, appended after -- so reordering the
    three sources shown on a page does not silently drop a fourth."""
    items = list_all(root)
    by_name = {s["name"]: s for s in items}
    ordered = [by_name[safe_name(n)] for n in names if safe_name(n) in by_name]
    rest = [s for s in items if s not in ordered]
    for i, s in enumerate(ordered + rest):
        s["priority"] = i
    _write(root, ordered + rest)


def _write(root, items):
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))


def delete(root, name):
    n = safe_name(name)
    items = list_all(root)
    kept = [s for s in items if s["name"] != n]
    if len(kept) == len(items):
        return False
    _write(root, kept)
    return True
