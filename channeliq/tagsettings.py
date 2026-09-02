"""User-editable region/quality tag vocabulary, persisted across runs.

normalize.py ships two hardcoded lists -- DEFAULT_REGION_TAGS (country
markers: "UK", "US", "NL"...) and QUALITY_TAGS ("HD", "RAW", "4K"...) --
that every run's Normalizer strips as packaging before matching a stream
to a wantlist entry. Real, reported gap: a provider's own prefixes that
aren't a country at all ("OD:", "PLAY+:", "ZG:", "BE-VIP:") or a quality
label this list has never seen ("GOLD", seen for real in a Dispatcharr
group name) had no way in except retyping them into the New Run form's
one-off "Custom prefixes" field on every single run -- nothing was ever
remembered, and nothing let an operator manage a durable list of their
own the way they can providers, wantlists, or lineups.

This module is that durable list. Deliberately NOT a copy of the
built-in lists baked in at first use: as long as an operator has never
customised a category, reading it returns the CURRENT code constant, so
a future channeliq release that adds new built-in tags reaches every
installation automatically. Customising a category (add/remove) freezes
it to an explicit saved list from that point on; "restore defaults"
un-freezes it by simply deleting the saved override, reverting to
whatever the running code's constant says right now, not a stale
snapshot from whenever it was first customised.
"""
import json
import os

from .normalize import DEFAULT_REGION_TAGS, QUALITY_TAGS

STORE_FILE = "tagsettings.json"
_CATEGORIES = {
    "region": DEFAULT_REGION_TAGS,
    "quality": QUALITY_TAGS,
}


def _path(root):
    return os.path.join(root, STORE_FILE)


def _read(root):
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(root, data):
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _path(root))


def _defaults(kind):
    if kind not in _CATEGORIES:
        raise ValueError(f"unknown tag category: {kind!r}")
    return list(_CATEGORIES[kind])


def tags(root, kind):
    """The CURRENT effective list for `kind` ("region" or "quality") --
    the saved override if this category has ever been customised, else a
    fresh copy of the built-in constant (see module docstring on why that
    distinction matters)."""
    saved = _read(root).get(kind)
    return list(saved) if saved is not None else _defaults(kind)


def is_customised(root, kind):
    return _read(root).get(kind) is not None


def add(root, kind, tag):
    tag = (tag or "").strip().upper()
    if not tag:
        raise ValueError("tag cannot be blank")
    current = tags(root, kind)
    if tag not in current:
        current.append(tag)
    data = _read(root)
    data[kind] = current
    _write(root, data)
    return current


def remove(root, kind, tag):
    tag = (tag or "").strip().upper()
    current = [t for t in tags(root, kind) if t != tag]
    data = _read(root)
    data[kind] = current
    _write(root, data)
    return current


def restore_defaults(root, kind):
    """Un-freeze `kind` back to following the built-in constant live."""
    _defaults(kind)  # validates kind before touching the file
    data = _read(root)
    if data.pop(kind, None) is not None:
        _write(root, data)
    return _defaults(kind)
