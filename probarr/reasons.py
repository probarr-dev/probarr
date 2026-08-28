"""User-editable list of preset reasons for deleting a stream.

Curate's "Delete stream" always asked why (see web.py's candidate-remove
handler, which stores it as this run's own excluded-stream note) but only
ever offered a blank text box -- every operator retyping "wrong aspect
ratio" or "wrong channel" by hand, every single time, on every provider
with the same recurring handful of reasons. This is the durable list those
picks come from: a small built-in starting set, and whatever an operator
adds shows up as a one-click choice from then on, on every future delete,
not just this run's.

Unlike tagsettings.py's region/quality vocabulary, a reason is free text a
human reads later, not a normalised code a matcher folds case on -- so
this module keeps whatever casing was typed rather than uppercasing it.
"""
import json
import os

DEFAULT_REASONS = ["Wrong channel", "Wrong aspect ratio"]
STORE_FILE = "delete_reasons.json"


def _path(root):
    return os.path.join(root, STORE_FILE)


def _read(root):
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _write(root, items):
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))


def list_all(root):
    """The current effective list -- the saved one if ever customised,
    else a fresh copy of the built-in defaults."""
    saved = _read(root)
    return list(saved) if saved is not None else list(DEFAULT_REASONS)


def is_customised(root):
    return _read(root) is not None


def add(root, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("reason cannot be blank")
    current = list_all(root)
    if reason not in current:
        current.append(reason)
        _write(root, current)
    return current


def remove(root, reason):
    reason = (reason or "").strip()
    current = [r for r in list_all(root) if r != reason]
    _write(root, current)
    return current


def restore_defaults(root):
    """Delete the saved override entirely -- back to tracking
    DEFAULT_REASONS live, same as tagsettings.py's own restore."""
    if os.path.exists(_path(root)):
        os.remove(_path(root))
    return list(DEFAULT_REASONS)
