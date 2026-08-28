"""Saved provider connections.

The thing probarr had no obvious home for at all: where do you tell it about
your IPTV subscription? Wantlists and settings both had a visible page; the
provider address had nowhere to live except a CLI flag or an unlabelled text
box on the settings page that did nothing on its own.

A provider is just a name plus a source spec (the same strings load_source()
already accepts: a plain M3U URL, or xtream://user:pass@host:port, or
dispatcharr://user:pass@host:port) -- saved so it can be picked from a list
instead of retyped, and so credentials live in one place rather than pasted
into every run.
"""
import os
import re
import time

from .wantlist import safe_name  # identical constraint: becomes a filename

STORE_FILE = "providers.json"


def _path(root):
    return os.path.join(root, STORE_FILE)


def _scheme(spec):
    m = re.match(r"^([a-z][a-z0-9+.-]*)://", spec or "", re.I)
    if not m:
        return "m3u"
    s = m.group(1).lower()
    return {"http": "m3u", "https": "m3u", "file": "m3u",
            "xtreams": "xtream", "dispatcharrs": "dispatcharr"}.get(s, s)


def list_all(root):
    import json
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = data if isinstance(data, list) else []
    for p in out:
        p["scheme"] = _scheme(p.get("spec", ""))
    return out


def get(root, name):
    n = safe_name(name)
    return next((p for p in list_all(root) if p["name"] == n), None)


def save(root, name, spec, concurrency=None, as_source=None):
    """`concurrency`: this provider's own probe connection limit, if it
    differs from the global default in Settings -- e.g. a second provider
    on a 3-connection plan sitting alongside the main one's 1-connection
    limit. None means "use the global default", which is every provider's
    behaviour before this existed.

    `as_source`: whether this provider is offered as something a RUN can
    probe from (New Run / Lineups' provider dropdowns) -- as opposed to
    a Dispatcharr connection saved purely to push curated channels back
    into, never probed from directly. None (the default) means "leave
    it as whatever it already was, or true for a brand new provider" --
    every provider saved before this existed, every plain M3U/Xtream one,
    and a fresh Dispatcharr connection from the Providers page's "Connect
    Dispatcharr" card (its own checkbox defaults on) all default to being
    a source; only an explicit uncheck turns a Dispatcharr connection into
    a push-target-only one. Always
    ignored for whether a Dispatcharr provider can be an EXPORT target --
    that's a separate concern this flag deliberately never touches (see
    web.py's push-target provider list, which lists every dispatcharr:
    scheme provider regardless).
    """
    import json
    n = safe_name(name)
    if not n:
        raise ValueError("invalid provider name")
    if not (spec or "").strip():
        raise ValueError("spec cannot be empty")
    # list_all() computes "scheme" fresh on every read and mutates the
    # dicts it returns to carry it -- stripped again here before writing,
    # or every OTHER existing provider gets a stale "scheme" baked into
    # providers.json on every single save, not just the one being edited
    # (confirmed live: exactly this had already happened on a real
    # instance before this fix).
    existing = next((p for p in list_all(root) if p["name"] == n), None)
    items = [{k: v for k, v in p.items() if k != "scheme"}
             for p in list_all(root) if p["name"] != n]
    entry = {"name": n, "spec": spec.strip(), "saved": time.time()}
    if concurrency:
        entry["concurrency"] = max(1, int(concurrency))
    if as_source is not None:
        entry["as_source"] = bool(as_source)
    elif existing is not None and "as_source" in existing:
        entry["as_source"] = existing["as_source"]
    items.append(entry)
    items.sort(key=lambda p: p["name"].lower())
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))
    return n


def set_last_group_name(root, name, group_name):
    """Remember the Dispatcharr group a push into this provider last used.

    Deliberately attached to the PROVIDER (the actual persistent Dispatcharr
    destination), not to whichever probarr run happened to trigger the
    push. Real bug this fixes: group-name memory was originally kept on the
    run instead, so a channel re-pushed from a DIFFERENT, newer probarr run
    of the same conceptual lineup (re-verifying the same channels a
    second time, say) had no memory of the group the FIRST run's push had
    used, and defaulted to a brand new group instead -- even though from
    the operator's perspective there is only one real destination, "my
    lineup in Dispatcharr", regardless of which run produced today's picks.
    """
    import json
    n = safe_name(name)
    try:
        with open(_path(root), encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(items, list):
        return False
    for p in items:
        if p.get("name") == n:
            p["last_group_name"] = group_name
            break
    else:
        return False
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))
    return True


def rename(root, old_name, new_name):
    """Rename a saved provider in place -- same spec, concurrency and
    remembered push group, just a new name.

    Callers (see web.py's _rename_provider) are responsible for cascading
    the new name into every lineup and run that references the OLD one by
    name (lineups.json's `provider` field, a run's own `provider_name`) --
    this function only touches providers.json itself, the same narrow
    scope save() and delete() already keep.
    """
    import json
    old = safe_name(old_name)
    new = safe_name(new_name)
    if not new:
        raise ValueError("invalid provider name")
    items = list_all(root)
    if not any(p["name"] == old for p in items):
        raise ValueError(f"no provider named {old_name!r}")
    if old != new and any(p["name"] == new for p in items):
        raise ValueError(f"a provider named {new_name!r} already exists")
    for p in items:
        if p["name"] == old:
            p["name"] = new
        # list_all() computes this fresh on every read; carrying it through
        # to a write would freeze a stale value into providers.json.
        p.pop("scheme", None)
    items.sort(key=lambda p: p["name"].lower())
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _path(root))
    return new


def delete(root, name):
    import json
    n = safe_name(name)
    items = list_all(root)
    kept = [p for p in items if p["name"] != n]
    if len(kept) == len(items):
        return False
    os.makedirs(root, exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(kept, f, indent=2)
    os.replace(tmp, _path(root))
    return True


def redact(spec):
    """Spec safe to display in a list view -- never the raw credentials."""
    spec = spec or ""
    # user:pass@host style (xtream://, dispatcharr://)
    spec = re.sub(r"(?i)^([a-z]+://)[^:/@]+:[^@]+@", r"\1***:***@", spec)
    # query-string credentials on a plain M3U/Xtream URL
    spec = re.sub(r"(?i)([?&](?:username|password|user|pass|u|p|token|key)=)[^&]*",
                  r"\1***", spec)
    return spec
