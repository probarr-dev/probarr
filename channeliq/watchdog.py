"""Ongoing maintenance for channels Dispatcharr has reported real trouble on.

Everything else in channeliq that judges stream quality does it from a probe --
a deliberate 10-25s sample, decoded once. This module instead reacts to
Dispatcharr's OWN system-events log: a channel_error or channel_reconnect
there is not a guess, it is a real viewer's player actually failing over
(see sources/dispatcharr.py's failed_streams() for the same log, used
elsewhere only for a read-only display).

A single such event is enough to put a channel on the watchlist AND demote
its currently-live stream in ranking immediately -- not wait for a re-probe
to confirm what Dispatcharr just told us directly. From there this is an
escalating check-in: re-probe the channel at a starting interval, and every
time it comes back clean, double the wait (capped) rather than hammering a
channel that has settled down. Any renewed trouble resets straight back to
the start. Once a channel has been clean for the configured stability
window, it graduates off the watchlist entirely -- back to however often it
would ordinarily be re-verified, no different from any other channel.

Deliberately its OWN file, not folded into selection.json: like claims.py,
this is a statement about ongoing MONITORING, not a curator's decision, and
needs to be readable/writable without touching the selection a human is
actively editing in Curate.
"""
import json
import os
import time

STORE_FILE = "watchlist.json"

DEFAULT_START_MINUTES = 30
DEFAULT_MAX_HOURS = 48
DEFAULT_STABLE_HOURS = 72
DEFAULT_THRESHOLD = 1

WATCHED_EVENT_TYPES = ("channel_error", "channel_reconnect")


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
    """{channel_key: entry}. See flag() for an entry's shape."""
    return _read(root)


def for_run(root, run_id):
    """{channel_key: entry} restricted to one run -- what build_payload's
    ranking needs, since a channel_key is only meaningful within the run
    that produced its candidates.
    """
    return {k: v for k, v in _read(root).items() if v.get("run_id") == run_id}


def last_event_id(root):
    """High-water mark of the newest Dispatcharr system-event already
    processed, so a tick only ever reacts to events it hasn't seen yet --
    without this, every tick would re-flag every channel with a
    channel_error anywhere in Dispatcharr's whole retained log, forever.
    """
    return _read(root).get("_last_event_id", 0)


def set_last_event_id(root, event_id):
    data = _read(root)
    data["_last_event_id"] = event_id
    _write(root, data)


def flag(root, channel_key, run_id, demoted_stream_id, settings=None, now=None):
    """Put a channel on the watchlist, or renew it after fresh trouble.

    Called once per NEW qualifying event (see last_event_id/correlate_event
    in web.py's watchdog tick). Resets escalation back to the start
    interval and clears any accumulated stability, whether the channel was
    already being watched or not -- a renewed failure means whatever
    "stable" period had been building no longer counts.
    """
    settings = settings or {}
    now = now if now is not None else time.time()
    start = int(settings.get("watchdog_start_minutes", DEFAULT_START_MINUTES)) * 60
    data = _read(root)
    entry = data.get(channel_key) or {}
    entry.update({
        "run_id": run_id,
        "demoted_stream_id": demoted_stream_id,
        "flagged_at": entry.get("flagged_at") or now,
        "last_event_at": now,
        "interval_seconds": start,
        "next_check": now + start,
        "stable_since": None,
    })
    data[channel_key] = entry
    _write(root, data)
    return entry


def due(entry, now=None):
    now = now if now is not None else time.time()
    return now >= entry.get("next_check", 0)


def defer_check(root, channel_key, now=None):
    """Not enough usable candidates to meaningfully check yet (see
    web.py's tick: fewer than 2 ok/dirty candidates means there is no
    fallback to promote even if the current pick is bad). Tried again at
    the SAME interval rather than escalating on a check that never
    actually happened -- escalating here would silently stop watching a
    channel that has no fallback at all, which is exactly the case this
    is meant to keep an eye on.
    """
    now = now if now is not None else time.time()
    data = _read(root)
    entry = data.get(channel_key)
    if not entry:
        return None
    entry["next_check"] = now + entry.get("interval_seconds",
                                          DEFAULT_START_MINUTES * 60)
    data[channel_key] = entry
    _write(root, data)
    return entry


def record_check(root, channel_key, ok, settings=None, now=None):
    """Record one completed recheck. Returns the updated entry, or None
    if the channel just graduated off the watchlist (removed).

    ok=True -- the channel's top-ranked candidate (demotion still
    applied) is currently clean. Doubles the interval, capped, and
    starts/continues the stability clock; once that clock has run for
    watchdog_stable_hours, the channel graduates off the watchlist and
    its demotion is lifted.
    ok=False -- same as a fresh flag(): back to the start interval, and
    the stability clock is cleared.
    """
    settings = settings or {}
    now = now if now is not None else time.time()
    start = int(settings.get("watchdog_start_minutes", DEFAULT_START_MINUTES)) * 60
    cap = int(settings.get("watchdog_max_hours", DEFAULT_MAX_HOURS)) * 3600
    stable_needed = int(settings.get("watchdog_stable_hours",
                                     DEFAULT_STABLE_HOURS)) * 3600
    data = _read(root)
    entry = data.get(channel_key)
    if not entry:
        return None
    if not ok:
        entry["interval_seconds"] = start
        entry["stable_since"] = None
        entry["next_check"] = now + start
        data[channel_key] = entry
        _write(root, data)
        return entry
    entry["stable_since"] = entry.get("stable_since") or now
    if now - entry["stable_since"] >= stable_needed:
        del data[channel_key]
        _write(root, data)
        return None
    entry["interval_seconds"] = min(cap, entry.get("interval_seconds", start) * 2)
    entry["next_check"] = now + entry["interval_seconds"]
    data[channel_key] = entry
    _write(root, data)
    return entry


def unflag(root, channel_key):
    """Remove a channel from the watchlist outright -- e.g. it was
    deleted, excluded, or manually cleared. Idempotent.
    """
    data = _read(root)
    if data.pop(channel_key, None) is not None:
        _write(root, data)
        return True
    return False


def correlate_event(event, claims_by_name):
    """One Dispatcharr system-event -> (channel_key, run_id), or None.

    `claims_by_name`: {dispatcharr_channel_name: claim} -- the reverse of
    claims.py's own id-keyed shape, built by the caller from
    claims.read_all() (see web.py's watchdog tick). Only a claim recorded
    by a RUN's own push (source starting "run:", see claims.claim()'s call
    site in web.py) is matchable -- a channel claimed some other way has
    no run to re-probe or push through.
    """
    if event.get("event_type") not in WATCHED_EVENT_TYPES:
        return None
    name = event.get("channel_name")
    if not name:
        return None
    claim = claims_by_name.get(name)
    if not claim:
        return None
    source = claim.get("source") or ""
    if not source.startswith("run:"):
        return None
    key = claim.get("key")
    if not key:
        return None
    return key, source[len("run:"):]
