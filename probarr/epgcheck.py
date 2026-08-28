"""Compare a channel against every saved EPG source, live.

The run-time `expected` field on a probe result answers "what did the guide
say was on AT THE MOMENT this stream was probed" -- useful for spotting a
mismatched feed, but frozen the instant the run finished. It answers nothing
about whether that guide is still the right one to trust, or whether a
different saved EPG source would have matched the channel more precisely
(a real, motivating case: a household adds a second EPG source specifically
because the run's original one turned out unreliable for some channels, and
then has no way in Curate to see the alternative's opinion side by side).

This module answers "what does each saved source say is on RIGHT NOW",
checked live rather than only at probe time, across every source at once so
a curator can pick the one that actually lines up with the picture.
"""
import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.request

from .epg import Guide
from .normalize import Normalizer
from . import epgsources as epgsources_mod

# Some XMLTV sources declare a <display-name> that's really their internal
# channel id with a country code glued on ("4Seven.uk", "5Star.uk") rather
# than a real display name -- real data seen from open-epg.com's UK feed.
# Cosmetic only: stripped from what's SHOWN and what gets written into a
# wantlist, never from guide_id/tvg_id, so EPG matching is unaffected.
_TRAILING_CC_RE = re.compile(r"\.[a-z]{2}$")

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _word_set(name):
    """Significant words in a name, for the "how much do these two names
    actually agree" question -- deliberately cruder than Normalizer.key(),
    which folds a name down to ONE glued identity string built for exact
    matching, not for counting how many words two DIFFERENT names share.
    Numbers are kept (not just letters): "ESPN 2" vs "ESPN" should score
    lower than "ESPN 2" vs "ESPN 2", and stripping digits would hide that.
    """
    return {w.upper() for w in _WORD_RE.findall(name or "")}


def _trust_path(root):
    return os.path.join(root, "epg_source_trust.json")


def read_trust(root):
    """{source_name: {"wins": N, "seen": M}} -- how often each saved EPG
    source's pick has agreed with the word-overlap consensus winner across
    every channel this has been computed for, versus how often it was in
    the running at all. Missing or corrupt file reads as empty: this is an
    advisory tiebreaker, never something a bad read should be allowed to
    break resolution over.
    """
    try:
        with open(_trust_path(root), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _bump_trust(root, winner_source, all_sources):
    """Record that `winner_source` won this channel's consensus, and that
    every source in `all_sources` was in the running for it.

    Best-effort only: a write failure here must never surface as an error
    to whatever caller triggered a resolution (a page load, an export) --
    this is a slowly-accumulating hint for future tie-breaks, not data
    anything currently depends on being correct.
    """
    try:
        trust = read_trust(root)
        for name in all_sources:
            entry = trust.setdefault(name, {"wins": 0, "seen": 0})
            entry["seen"] = entry.get("seen", 0) + 1
        trust.setdefault(winner_source, {"wins": 0, "seen": 0})
        trust[winner_source]["wins"] = trust[winner_source].get("wins", 0) + 1
        tmp = _trust_path(root) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trust, f)
        os.replace(tmp, _trust_path(root))
    except OSError:
        pass


def _display_clean(name):
    stripped = _TRAILING_CC_RE.sub("", name)
    return stripped if len(stripped) >= 2 else name

# XMLTV files are typically refreshed by their publisher on the order of
# hours, not seconds -- caching each parsed Guide keeps a "check every
# channel against every source" pass from re-fetching and re-parsing a
# multi-MB file (seconds each, see runner.py's own EPG load) on every single
# click. Raised from 10 minutes: a real Verify run against a real lineup
# routinely takes longer than that, so by the time it finished, Curate's
# own persistent EPG badge (loadEpgNow(), fired automatically for the
# first channel on every page load) paid the full cold-parse cost anyway
# -- confirmed live, ~19s across four real saved sources, on a page whose
# own HTML/data load in milliseconds. 30 minutes is still comfortably
# inside "the guide might have changed" territory (see the note above,
# hours not seconds) while covering the actual gap between normal visits.
# See prewarm_all_sources() below for the other half of the fix -- this
# alone does not help a genuinely cold cache right after a restart.
_CACHE_TTL = 1800
_cache = {}  # url -> (Guide, loaded_at)

# KNM fix (probarr-vz7): Curate's per-channel "what's on now" badge fires
# one _epg_check per channel on page load, concurrently -- a 6-channel
# lineup means 6 threads calling load_cached() for the SAME url at once.
# Without a lock, every one of them sees the same cold/expired cache entry
# and independently downloads and parses the multi-MB feed in parallel:
# confirmed live, six threads simultaneously inside ElementTree parsing
# (py-spy dump), pegging the container at 100%+ CPU for the full duration
# instead of one parse with five callers waiting on it. Keyed per-url so
# different sources still warm concurrently -- only same-url callers
# should serialize.
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(url):
    # RLock, not Lock: _indexed_guide() holds this lock across its own call
    # into load_cached(), which takes the same per-url lock again on the
    # same thread -- a plain Lock would deadlock there.
    with _locks_guard:
        lock = _locks.get(url)
        if lock is None:
            lock = _locks[url] = threading.RLock()
        return lock

# How long a downloaded XMLTV file is reused from disk. Deliberately hours,
# not minutes: a real aggregator rate-limits downloads (open-epg allows 20
# per file per day and returns an HTML "download limit reached" page after
# that, which parses as junk rather than failing cleanly). The in-memory
# cache alone could not protect against this -- it dies with the process,
# so every container restart re-downloaded every source, and a day of
# ordinary deploys was enough to exhaust the allowance.
_DISK_TTL = 6 * 3600
_DISK_DIR = "epg_cache"


def _disk_path(root, url):
    d = os.path.join(root, _DISK_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, hashlib.sha256(url.encode()).hexdigest()[:16] + ".xml")


def _fetch_to_disk(root, url):
    """Download an XMLTV source to the on-disk cache, reusing a recent copy.

    Returns the local path. Written via a temp file and atomic replace so an
    interrupted download can never leave a truncated file that later parses
    as junk.
    """
    path = _disk_path(root, url)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < _DISK_TTL:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "probarr/0.1"})
    raw = urllib.request.urlopen(req, timeout=120).read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    head = raw[:400].lstrip()
    if not head.startswith(b"<?xml") and not head.startswith(b"<tv"):
        # A rate-limit or error page, not a guide. Kept OUT of the cache and
        # reported with what the server actually said, rather than surfacing
        # later as an opaque XML parse error on every single channel.
        txt = " ".join(head.decode("utf-8", "replace").split())
        import re as _re
        txt = _re.sub(r"<[^>]+>", " ", txt)
        raise ValueError("source did not return XMLTV: "
                         + " ".join(txt.split())[:180])
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, path)
    return path


def load_cached(url, window_hours=6, root=None):
    """A small-window Guide for `url`, reused across calls within the TTL.

    window_hours is deliberately narrow (vs runner.py's 48h probing window)
    -- this only ever needs to answer "what's on right now", so there is no
    reason to parse or hold two days of programmes in memory for it.

    KNM fix (probarr-vz7): locked per-url. Curate's per-channel "what's on
    now" badge fires one call per channel on page load, concurrently -- a
    6-channel lineup means 6 threads calling this for the SAME url at once.
    Without the lock, every one of them sees the same cold/expired entry
    and independently downloads and parses the multi-MB feed in parallel
    (confirmed live: six threads simultaneously inside ElementTree parsing,
    container pegged at 100%+ CPU for the duration). The lock makes the
    first caller do the real work and the rest wait for it, then reuse it
    -- one parse instead of six.
    """
    with _lock_for(url):
        now = time.time()
        hit = _cache.get(url)
        if hit and (now - hit[1]) < _CACHE_TTL:
            return hit[0]
        src = _fetch_to_disk(root, url) if root else url
        g = Guide.load(src, window_hours=window_hours)
        _cache[url] = (g, now)
        return g


# The Guide object itself is cached, but its name index is a normalised
# view over it (folded, aliased) and used to be rebuilt from scratch on
# every single check -- walking and normalising every channel name in the
# file, for every saved source, on every click. Real cost on a 6,000-entry
# guide, thrown away for nothing since neither the file nor the aliases had
# changed since the last click. Indexed once per (url, aliases) pair here.
_indexed = {}   # url -> (aliases signature, indexed Guide)


def _indexed_guide(url, normalizer, root):
    # Same per-url serialization as load_cached, and for the same reason:
    # build_name_index() walks every channel in the guide and is real cost
    # on a 6,000-entry feed, so concurrent callers should wait for the
    # first index rather than each redoing it.
    with _lock_for(url):
        g = load_cached(url, root=root)
        sig = tuple(sorted(normalizer.aliases.items()))
        hit = _indexed.get(url)
        if hit and hit[0] == sig and hit[1] is g:
            return g
        g.build_name_index(normalizer)
        _indexed[url] = (sig, g)
        return g


def prewarm_all_sources(root, normalizer):
    """Parse and index every saved EPG source once, so the FIRST real
    check_all() call after this (whoever makes it, whatever channel) hits a
    warm cache instead of paying the ~5-20s-per-source cold parse live.

    Meant to be called from a background thread at the two moments that
    actually leave the cache cold: server startup, and the end of a
    completed Verify run (see web.py's serve() and runner.py's _run()) --
    a run routinely outlasts _CACHE_TTL, so without this, the very next
    person to open Curate paid for it synchronously through the page's own
    persistent EPG badge. Best-effort throughout: one source failing to
    parse (network hiccup, a rate-limited aggregator) must not stop the
    others from warming, and this must never raise into whatever caller
    triggered it.
    """
    for src in epgsources_mod.list_all(root):
        try:
            _indexed_guide(src["url"], normalizer, root)
        except Exception:
            pass


def search_programmes_across_sources(root, query, at, normalizer,
                                     tolerance_minutes=90, limit=25):
    """Every saved EPG source's answer to "what channel was actually
    showing `query` around `at`" -- see Guide.search_programmes_at() for
    why this exists. A source that fails to load is skipped, same as
    check_all()'s own per-source try/except: one broken source must not
    hide a working one's answer.
    """
    out = []
    for src in epgsources_mod.list_all(root):
        try:
            g = _indexed_guide(src["url"], normalizer, root)
        except Exception:
            continue
        for hit in g.search_programmes_at(query, at, tolerance_minutes, limit):
            out.append({**hit, "source": src["name"]})
    out.sort(key=lambda h: h["start"])
    return out[:limit]


def search_source(root, source_name, query, normalizer, limit=25):
    """Search one saved EPG source's channel names for `query`, live --
    the manual counterpart to resolve(): a person filtering a real list of
    names instead of trusting a fuzzy match. Returns
    [{"guide_id", "guide_name", "now": programme-dict-or-None}, ...].
    Raises if the source name isn't saved or its guide can't be loaded --
    the caller is expected to turn that into an error response, same as
    every other EPG lookup in this module.
    """
    src = epgsources_mod.get(root, source_name)
    if not src:
        raise ValueError(f"no such EPG source: {source_name}")
    g = _indexed_guide(src["url"], normalizer, root)
    at = datetime.datetime.now(datetime.timezone.utc)
    return [{"guide_id": cid, "guide_name": name, "now": g.now_playing(cid, at)}
            for cid, name in g.search(query, limit=limit)]


# UK regional-opt-out abbreviations, as broadcasters actually abbreviate
# them in a channel list (BBC One/Two, ITV each carry ~15 of these; Sky's
# own guide names are the confirmed source for several of these exact
# spellings). Best-effort and expandable, not exhaustive -- a family this
# doesn't recognise just falls back to one row per variant, same as before
# this existed, rather than failing.
_REGION_WORDS = [
    "CHANNEL ISLANDS", "CI", "EAST MIDLANDS", "EMID", "EAST", "LONDON", "LON",
    "NORTH EAST", "NORTHEAST", "NE", "NORTHERN IRELAND", "NI", "NORTH WEST",
    "NORTHWEST", "NW", "SCOTLAND", "SCOT", "SOUTH EAST", "SOUTHEAST", "SE",
    "SOUTH WEST", "SOUTHWEST", "SW", "SOUTH", "STH", "WALES", "WAL",
    "WEST MIDLANDS", "WM", "WEST", "WST", "YORKS AND LINCS", "Y&L",
    "YORKSHIRE", "YORKS", "YKS",
]
_REGION_RE = None   # built lazily, once, from _REGION_WORDS
_QUALITY_RE = None  # built lazily, once, from normalize.QUALITY_TAGS


def _strip_region(name):
    """`name` with a trailing quality tag and/or UK regional-variant word
    removed, if present.

    Real guides glue these onto the name with NO separator at all
    ("BBC One ScotHD", "BBC One EastHD") as often as they space them out
    ("BBC One CI HD") -- confirmed against a live source, not a
    hypothetical. A plain word-boundary match refuses "ScotHD" outright
    (there is no boundary between "Scot" and "HD", both are word
    characters), so both tag lists are matched WITHOUT a leading boundary
    requirement here, unlike Normalizer's own identity key -- the failure
    mode of over-stripping is a slightly-off grouping default a person can
    still correct via the picker, not a wrong stream landing on a channel,
    so this can afford to be looser than the matching-identity code is.

    Order matters in _REGION_WORDS -- longer, more specific phrases must be
    tried before the short abbreviations they contain (e.g. "SOUTH EAST"
    before "SE", so "BBC One South East" doesn't strip down to "BBC One
    South" and land in the wrong family).
    """
    global _REGION_RE, _QUALITY_RE
    if _REGION_RE is None:
        import re
        from .normalize import QUALITY_TAGS
        # A boundary that accepts a camelCase transition ("east" -> "HD" in
        # "EastHD") as well as a normal word boundary, but rejects matching
        # partway through an ordinary word -- "One" must never let "NE"
        # match its own trailing two letters just because they happen to
        # spell a region code. Holds when the preceding character is
        # anything but a letter (start-of-string, space, punctuation), OR
        # when it's specifically a LOWERCASE letter (the camelCase case) --
        # "One"'s trailing "ne" is preceded by an uppercase "O", so this
        # correctly refuses it. The lowercase check is wrapped in `(?-i:)`
        # to force case-sensitivity locally -- these patterns compile with
        # IGNORECASE overall (so "hd" matches "HD"), and under IGNORECASE a
        # bare [a-z] class ALSO matches uppercase, which silently turns
        # this whole check into "preceded by any letter or not" -- true
        # unconditionally, which is exactly what caused the "One" bug.
        boundary = r"(?:(?<![A-Za-z])|(?-i:(?<=[a-z])))"
        r_alt = "|".join(w.replace(" ", r"\s+") for w in
                         sorted(_REGION_WORDS, key=len, reverse=True))
        q_alt = "|".join(sorted(QUALITY_TAGS, key=len, reverse=True))
        _REGION_RE = re.compile(rf"\s*{boundary}(?:{r_alt})\s*$", re.IGNORECASE)
        _QUALITY_RE = re.compile(rf"\s*{boundary}(?:{q_alt})\s*$", re.IGNORECASE)
    # Quality first ("ScotHD" -> "Scot"), then region on what's left
    # ("Scot" -> ""), so a glued region+quality suffix strips fully either
    # order they were applied in the source name.
    stripped = _QUALITY_RE.sub("", name)
    stripped = _REGION_RE.sub("", stripped)
    return stripped.strip() or name


def list_channels(root, source_name, normalizer=None):
    """Every DISTINCT channel one saved EPG source declares, grouped by
    real identity -- {guide_id, guide_name, alts} for each, sorted by
    name. The bulk counterpart to search_source(): this exists so a
    wantlist can be BUILT from a guide's own channel list (tick what you
    want) instead of only checked against one, reusing a guide someone
    else has already kept current rather than hand-typing a text file
    from scratch.

    Two kinds of "same channel, listed twice" are collapsed here, for two
    different reasons:

    1. Quality variants ("BBC One" / "BBC One HD") -- not two channels at
       all, probarr already picks the best available quality among a
       channel's candidates once streams are matched, so offering both as
       separate tickable rows just means one gets ticked twice under two
       different keys. Folded with the SAME normaliser that already treats
       them as one key everywhere else in probarr, so this agrees with the
       rest of the tool rather than doing its own, different thing.
    2. Regional variants ("BBC One London" / "BBC One Scotland") -- these
       ARE genuinely different broadcasts, not a bug to collapse away, but
       a UK-wide guide can carry 15+ of them per channel and ticking
       through all of them one at a time to find your own region is real
       friction. These keep their real distinctness -- returned as ONE row
       (a chosen representative) with every other region listed under
       `alts`, so the picker can show a single line with a region dropdown
       instead of a wall of near-identical rows. Nothing is discarded;
       `alts` carries the rest through untouched.
    """
    src = epgsources_mod.get(root, source_name)
    if not src:
        raise ValueError(f"no such EPG source: {source_name}")
    g = load_cached(src["url"], root=root)
    norm = normalizer or Normalizer()

    # Pass 1: fold quality variants (SD/HD/etc) to one row per key, exactly
    # as before -- unrelated to regional grouping, done first so the
    # region pass below only ever sees one representative per real feed.
    by_key = {}
    for cid, names in g.display_names.items():
        if not names:
            continue
        name = _display_clean(names[0])
        key = norm.key(name) or name
        existing = by_key.get(key)
        if existing is None or len(name) < len(existing["guide_name"]):
            by_key[key] = {"guide_id": cid, "guide_name": name}

    # Pass 2: group what's left by "name with any trailing region word
    # removed". A family of one is just that channel; a family of more
    # than one is a genuine set of regional variants of the same channel.
    families = {}
    for entry in by_key.values():
        fam_key = norm.key(_strip_region(entry["guide_name"])) or entry["guide_name"]
        families.setdefault(fam_key, []).append(entry)

    out = []
    for members in families.values():
        members.sort(key=lambda c: len(c["guide_name"]))
        rep, rest = members[0], members[1:]
        if rest:
            rep = {**rep, "alts": rest}
        out.append(rep)
    out.sort(key=lambda c: c["guide_name"].lower())
    return out


def check_all(root, name, tvg_id, normalizer, overrides=None):
    """{source_name: {"matched": bool, "now": programme-dict-or-None}} for
    every saved EPG source, plus a "matched" flag so a source that doesn't
    carry this channel at all is visibly distinct from one that does but has
    nothing scheduled at this exact moment.

    Also scores each match: how many significant words the matched guide
    entry's own name shares with `name` (see _word_set()) -- e.g. "UK: BBC
    Two" against a guide's "BBC Two Lon" scores 2 ("BBC", "TWO"). This is
    what lets a caller with more than one saved source prefer whichever one
    actually agrees with what the channel is called, rather than trusting
    whichever source happens to be listed first (resolve()'s own ambiguity
    refusal already rules out the worst guesses, but says nothing about
    which of several PLAUSIBLE matches is the best one).

    `overrides` is an optional {source_name: guide_channel_id} map -- a
    person's manual pick from Check EPG's search, made when the automatic
    resolve() guessed wrong or missed a channel filed under an odd name.
    A source named in it uses that exact id directly instead of resolving,
    as long as the id still exists in that source (a source can be
    refreshed and drop an id between the pick and this call).
    """
    sources = epgsources_mod.list_all(root)
    overrides = overrides or {}
    at = datetime.datetime.now(datetime.timezone.utc)
    own_words = _word_set(name)
    out = []
    for src in sources:
        entry = {"source": src["name"], "matched": False, "now": None, "error": None,
                "guide_id": None, "guide_name": None, "score": 0, "logo": None}
        try:
            g = _indexed_guide(src["url"], normalizer, root)
            override_id = overrides.get(src["name"])
            cid = (override_id if override_id and override_id in g.display_names
                   else g.resolve(tvg_id, name, normalizer))
            if cid:
                entry["matched"] = True
                entry["now"] = g.now_playing(cid, at)
                # WHICH channel entry a source actually matched, not just
                # what is airing on it -- a fuzzy or ambiguous match can
                # easily land on the wrong entry while still returning a
                # perfectly plausible programme, so the entry itself has to
                # be checkable, not just its schedule.
                entry["guide_id"] = cid
                names = g.display_names.get(cid) or []
                entry["guide_name"] = names[0] if names else cid
                entry["score"] = len(own_words & _word_set(entry["guide_name"]))
                entry["logo"] = g.icons.get(cid)
        except Exception as e:
            entry["error"] = str(e)[:200]
        out.append(entry)
    return out


def consensus_winner(sources, root=None, bump_trust=False):
    """The single best-matched entry from check_all()'s output, when more
    than one saved source is configured -- picked by word-overlap score
    first, then by each source's accumulated trust (see read_trust()) as a
    tiebreak, then by name for stability.

    `consensus` is true only when at least TWO independently resolving
    sources agree there is a real match (score >= 1, i.e. they share at
    least one actual word, not just both nominally "matching" via a bare
    fuzzy prefix) -- a single source's opinion, however it scored, is never
    labelled a consensus on its own; there was nothing for it to agree
    with. With only one saved source at all, there is likewise no
    consensus to reach -- its answer is simply the only one there is.

    `bump_trust`, when true and `root` is given, records this outcome into
    the persisted trust file -- callers doing this for real curation
    decisions (an export, a persistent UI check) should pass it; one-off
    exploratory calls should not, so a person idly re-checking the same
    channel five times does not inflate one source's trust five times over
    for a single real judgement.
    """
    matched = [s for s in sources if s.get("matched")]
    if not matched:
        return None
    trust = read_trust(root) if root else {}

    def trust_of(s):
        t = trust.get(s["source"]) or {}
        seen = t.get("seen", 0)
        return (t.get("wins", 0) / seen) if seen else 0.0

    matched.sort(key=lambda s: (-s["score"], -trust_of(s), s["source"]))
    best = dict(matched[0])
    agreeing = [s for s in matched if s["score"] >= 1]
    best["consensus"] = len(agreeing) >= 2
    best["sources_checked"] = len(sources)
    if bump_trust and root and len(matched) >= 2:
        _bump_trust(root, best["source"], [s["source"] for s in matched])
    return best
