"""A lineup: the durable thing a run is a snapshot OF.

The object-model gap this closes. Everything in channeliq was scoped to a
`run`, but nobody thinks in runs -- you think in "my UK lineup", a
persistent thing that gets re-verified periodically. Runs are events
against that thing, not the thing itself.

That mismatch caused a whole family of real bugs rather than just being
untidy:

  * A push from a second run of the same conceptual lineup had no memory
    of the group the first run pushed into, and invented a new one.
  * A per-channel EPG-source choice made while curating one run was
    invisible to the next run, so the same decision had to be made again
    with nothing indicating it had ever been made.
  * The same provider + wantlist + EPG had to be re-selected on every New
    Run, because there was no object holding "these three go together".

A lineup owns the configuration (provider, wantlist, EPG source, export
target) AND the accumulated per-channel decisions. A run references its
lineup, inherits its decisions as the starting point, and contributes new
ones back. Nothing here is required -- a run started without a lineup
behaves exactly as before, which is what keeps this additive rather than
a migration.
"""
import json
import os
import time

from .wantlist import safe_name  # identical constraint: becomes a filename

STORE_FILE = "lineups.json"


def _path(root):
    return os.path.join(root, STORE_FILE)


def _read(root):
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(root, items):
    items.sort(key=lambda x: x["name"].lower())
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))


def list_all(root):
    return _read(root)


def get(root, name):
    n = safe_name(name)
    return next((x for x in _read(root) if x["name"] == n), None)


def save(root, name, **fields):
    """Create or update a lineup. Only the fields given are touched, so a
    caller updating one setting cannot blank the rest by omission -- the
    same partial-update semantics the Dispatcharr export learned the hard
    way it needed.
    """
    n = safe_name(name)
    if not n:
        raise ValueError("invalid lineup name")
    items = _read(root)
    existing = next((x for x in items if x["name"] == n), None)
    if existing is None:
        existing = {"name": n, "created": time.time(), "preferences": {}}
        items.append(existing)
    for k, v in fields.items():
        # `is not None`, not truthiness: schedule_days=0 means "stop
        # re-verifying this lineup", and a falsy check would silently
        # refuse to turn a schedule back off.
        if v is not None:
            existing[k] = v
    existing["updated"] = time.time()
    _write(root, items)
    return existing


def delete(root, name):
    n = safe_name(name)
    items = _read(root)
    kept = [x for x in items if x["name"] != n]
    if len(kept) == len(items):
        return False
    _write(root, kept)
    return True


# -- per-channel decisions ------------------------------------------------
#
# The durable half. A run's selection.json is a snapshot of one
# verification pass and is legitimately thrown away with it; these are the
# judgements that should outlive any particular run ("Comedy Central's
# guide comes from open-epg, not the provider's") and be inherited by the
# next one automatically.

def set_preference(root, lineup, channel_key, **prefs):
    """Record a durable per-channel decision on a lineup.

    The lineup is `lineup`, NOT `name` -- `name` is itself one of the
    preferences a channel can carry (a rename), and while this parameter was
    called `name` every rename raised TypeError("multiple values for
    argument 'name'") straight into the caller's bare except, so renames
    looked saved and were silently discarded. Caught by the test suite on
    its first run, months of manual testing having missed it.
    """
    lu = get(root, lineup)
    if lu is None:
        return False
    items = _read(root)
    for x in items:
        if x["name"] == lu["name"]:
            entry = x.setdefault("preferences", {}).setdefault(channel_key, {})
            for k, v in prefs.items():
                if v is None:
                    entry.pop(k, None)
                else:
                    entry[k] = v
            if not entry:
                x["preferences"].pop(channel_key, None)
            x["updated"] = time.time()
            break
    _write(root, items)
    return True


def preferences(root, name):
    """{channel_key: {...}} for a lineup. Empty dict when unknown, so
    callers can apply it unconditionally without branching on existence."""
    lu = get(root, name) if name else None
    return (lu or {}).get("preferences", {}) or {}
