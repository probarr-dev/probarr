"""Channel logo search against the tv-logo/tv-logos catalogue.

channeliq never downloads or redistributes a single logo image. Every result
this module returns is a `raw.githubusercontent.com` URL pointing straight
at that repository's own hosting -- the browser (or Dispatcharr, once a
choice is pushed) fetches the bytes directly from GitHub, and channeliq's own
disk cache only ever holds the two small JSON directory listings (country
names and per-country filenames), never image data. tv-logo/tv-logos is
CC BY-SA 4.0 -- linking to the maintainers' own hosting, rather than
mirroring the files ourselves, is the deliberate reason this stays on the
safe side of that license instead of becoming a redistribution.

Fetch approach (country listing -> per-country filename listing -> raw URL)
follows the same shape used by PiratesIRC's Lineuparr plugin
(Lineuparr/logo_matcher.py) for the same repository. The matching itself is
reimplemented on channeliq's own Normalizer (normalize.py) plus stdlib
difflib, rather than reusing that code or adding a fuzzy-matching
dependency -- channeliq ships with no pip dependencies at all (see the
Dockerfile and dhash.py) and that stays true here too.
"""
import difflib
import hashlib
import json
import os
import re
import time
import urllib.request

REPO = "tv-logo/tv-logos"
BRANCH = "main"
_API_BASE = f"https://api.github.com/repos/{REPO}/contents/countries"
_RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/countries"

_IMAGE_EXTS = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp")

# Directory listings on a stable public repo change rarely -- long TTLs
# keep this to essentially one request per cold cache, not one per search.
_COUNTRIES_TTL = 7 * 24 * 3600
_FILES_TTL = 24 * 3600
_CACHE_DIR = "logo_cache"

_mem = {}  # cache key -> (value, loaded_at)


def _cache_dir(root):
    d = os.path.join(root, _CACHE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _disk_path(root, key):
    return os.path.join(_cache_dir(root),
                         hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")


def _cached_json(root, key, ttl, fetch):
    """Memory cache in front of a disk cache in front of `fetch()`.

    Same two-tier shape as epgcheck.py's guide cache, for the same reason:
    the in-memory copy survives for the life of the process, the disk copy
    survives a restart -- and a directory listing is exactly the kind of
    thing worth not re-fetching from GitHub's (rate-limited) API on every
    container restart.
    """
    now = time.time()
    hit = _mem.get(key)
    if hit and now - hit[1] < ttl:
        return hit[0]
    path = _disk_path(root, key)

    def from_disk():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    if os.path.exists(path) and now - os.path.getmtime(path) < ttl:
        value = from_disk()
        if value is not None:
            _mem[key] = (value, now)
            return value

    # A FAILED fetch must never be cached. It used to be: the fetchers
    # swallowed every exception and returned [], which was then written to
    # disk and memory for the full TTL -- so one blip (a VPN reconnect, a
    # GitHub rate limit) left the logo picker showing an empty country list
    # for SEVEN DAYS, with no error and no way to refresh. Indistinguishable
    # from the feature being broken.
    try:
        value = fetch()
    except Exception:
        # A stale copy beats nothing: a week-old directory listing of a
        # stable public repo is still perfectly usable, and this is exactly
        # the moment it earns its keep. Returned WITHOUT re-caching, so the
        # next call tries the network again rather than being locked out.
        stale = from_disk()
        return stale if stale is not None else []

    _mem[key] = (value, now)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f)
        os.replace(tmp, path)
    except OSError:
        # Persisting is an optimisation, not the answer -- an unwritable
        # config dir must not break the picker.
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return value


def _get_json(url):
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.v3+json",
                      "User-Agent": "channeliq/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_countries(root):
    """Every country/region folder name in the repo, alphabetical.

    Best-effort at the caller's level: a failure falls back to the last
    cached copy if there is one, and otherwise an empty list -- but is
    never itself cached. See _cached_json.
    """
    def do_fetch():
        data = _get_json(_API_BASE)
        if not isinstance(data, list):
            raise ValueError("unexpected response from the GitHub API")
        return sorted(item["name"] for item in data
                      if item.get("type") == "dir")
    return _cached_json(root, "countries", _COUNTRIES_TTL, do_fetch)


def fetch_country_logos(root, country_dir):
    """Every image filename in one country folder.

    Falls back to a stale cached copy on failure, and never caches the
    failure itself -- see _cached_json.
    """
    def do_fetch():
        data = _get_json(f"{_API_BASE}/{country_dir}")
        if not isinstance(data, list):
            raise ValueError("unexpected response from the GitHub API")
        return sorted(item["name"] for item in data
                      if item.get("name", "").lower().endswith(_IMAGE_EXTS))
    return _cached_json(root, f"country:{country_dir}", _FILES_TTL, do_fetch)


def build_url(country_dir, filename):
    return f"{_RAW_BASE}/{country_dir}/{filename}"


def _filename_key(filename, normalizer):
    """A logo filename reduced to the same kind of bare identity key
    Normalizer.key() produces for a channel name -- strip the extension and
    the trailing '-<country>' suffix tv-logos filenames always carry, turn
    the remaining hyphens into word breaks, then fold it exactly like a
    channel title so the two are comparable at all.
    """
    stem = re.sub(r"\.(png|svg|jpg|jpeg|gif|webp)$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"-[a-z]{2,3}$", "", stem, flags=re.IGNORECASE)
    return normalizer.key(stem.replace("-", " "))


def search(root, query, country_dir, normalizer, limit=25):
    """Fuzzy-match `query` against one country's logo filenames.

    Returns a list of {filename, url, score} sorted best-first, score in
    [0, 1]. Matching runs entirely on channeliq's own Normalizer.key() (folds
    case/accents/punctuation away, the same treatment a stream title gets)
    plus stdlib difflib -- no fuzzy-matching dependency, no network beyond
    the (cached) filename listing itself.
    """
    query = (query or "").strip()
    if not query or not country_dir:
        return []
    qkey = normalizer.key(query)
    if not qkey:
        return []
    scored = []
    for filename in fetch_country_logos(root, country_dir):
        fkey = _filename_key(filename, normalizer)
        if not fkey:
            continue
        score = difflib.SequenceMatcher(None, qkey, fkey).ratio()
        scored.append((score, filename))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"filename": f, "url": build_url(country_dir, f), "score": round(s, 3)}
            for s, f in scored[:limit]]
