"""Which Dispatcharr channels probarr already considers its own.

A wantlist entry's `number` decides WHERE a push writes; this decides
WHETHER it is allowed to. Before this existed, push() matched purely by
`channel_number` (see dispatcharr_export.py) -- so a curated channel
pushed at number 101 would silently update whatever Dispatcharr channel
already happened to sit at 101, even if that channel had nothing to do
with probarr at all (added by hand, imported from somewhere else, or
just numbered the same by coincidence). Confirmed live: an established
Dispatcharr instance already has its own numbering, and a first push
against it can and does collide with real, unrelated channels.

A Dispatcharr channel's own `id` never changes just because a push
renumbers or renames it, so that id -- not the number, which is only a
locally-meaningful label -- is the identity this module tracks. Once a
channel's id is claimed here, every future push is free to update it
however much it needs to (see dispatcharr_export.py's push() gate); until
then, a number collision with an untagged id is refused rather than
silently overwritten.

Deliberately its OWN file, not folded into lineups.json: a claim is a
statement about a Dispatcharr INSTANCE ("id 42 there is ours"), not about
any one lineup's configuration, and needs to be checked before a push
even knows which lineup it belongs to.
"""
import json
import os
import time

STORE_FILE = "claims.json"


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


def read_all(root):
    """{dispatcharr_id (int): {key, name, source, claimed_at}}.

    Keys come back as ints (JSON object keys are always strings on disk)
    so callers can compare directly against the ids client.channels()
    returns without every caller re-doing the int(...) cast.
    """
    return {int(k): v for k, v in _read(root).items()}


def claimed_by_key(root):
    """{channel_key: {dispatcharr_id, name, source, claimed_at}} -- the
    reverse of read_all()'s id-keyed shape, for Curate's own debugging
    display (see web.py's _curate/_channel_json): a curator looking at
    ONE channel wants to know "is this thing tagged, and as what", which
    is a lookup by channel key, not by Dispatcharr id.

    A channel_key claimed under more than one Dispatcharr id (should not
    happen in practice) keeps whichever claim was recorded last -- good
    enough for a debugging display, and claim() itself is the only writer
    so there is exactly one path that could ever produce it.
    """
    out = {}
    for did, info in read_all(root).items():
        key = info.get("key")
        if key:
            out[key] = {"dispatcharr_id": did, **info}
    return out


def is_claimed(root, dispatcharr_id):
    return str(dispatcharr_id) in _read(root)


def claim(root, dispatcharr_id, channel_key=None, name=None, source=None):
    """Record that Dispatcharr channel `dispatcharr_id` is probarr's.

    Idempotent and cheap to call on every successful push -- see
    dispatcharr_export.push()'s `touched` return value, which is exactly
    the "we just wrote this, and Dispatcharr just confirmed the id"
    moment that makes this safe to record with total certainty, not a
    guess.
    """
    data = _read(root)
    data[str(dispatcharr_id)] = {"key": channel_key, "name": name,
                                 "source": source, "claimed_at": time.time()}
    _write(root, data)


def unclaim(root, dispatcharr_id):
    data = _read(root)
    if data.pop(str(dispatcharr_id), None) is not None:
        _write(root, data)
        return True
    return False
