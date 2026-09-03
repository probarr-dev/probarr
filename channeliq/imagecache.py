"""Local, on-disk cache for every remote image the UI displays.

Nothing the browser loads may point off this container. Two reasons, and
both were reported for real:

PRIVACY. Channel logos come from a provider's own CDN and from
raw.githubusercontent.com. Rendering those URLs straight into <img src>
meant the VIEWER's browser fetched them -- so the provider's CDN and GitHub
each received the viewer's home IP plus, from the filenames alone, a precise
list of which channels they were curating. On an install deliberately run
behind a VPN that is worse than untidy: the container's traffic is tunnelled
and the browser's is not, so the one component that was supposed to be
anonymous was the one leaking. Measured on a single real Curate load: 42
off-origin requests across three hosts.

RELIABILITY. The container can reach those hosts; the browser frequently
cannot -- different network, different DNS, no VPN route, or the CDN simply
refusing it. That is the "channel logos sometimes don't load" report, and no
amount of retrying in the browser could ever have fixed it.

So the browser is never given a remote URL at all. It gets "/img/<digest>",
an opaque local path; the digest is the key into an index this module owns,
and the bytes are fetched ONCE by the container and kept on disk. A logo
survives the source going away, and repeat views cost nothing.

Handing out a digest rather than proxying "/img?u=<url>" is deliberate: a
pass-through proxy on an unauthenticated LAN service (see README's Security
note) is an open SSRF relay -- anyone reaching the UI could make the
container fetch arbitrary internal addresses and read the result. Here the
browser can only ever name something the server itself already put in the
index from real run data. _fetchable() is the second line of defence.
"""
import hashlib
import ipaddress
import json
import mimetypes
import os
import socket
import urllib.parse
import urllib.request

CACHE_DIR = "image_cache"
INDEX_FILE = "index.json"

# A logo is a few KB. Anything wildly past that is not a logo, and this is
# the only bound between a hostile/broken URL and the container's disk.
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 15


def _dir(root):
    return os.path.join(root, CACHE_DIR)


def _index_path(root):
    return os.path.join(_dir(root), INDEX_FILE)


def _read_index(root):
    try:
        with open(_index_path(root), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(root, data):
    os.makedirs(_dir(root), exist_ok=True)
    tmp = _index_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _index_path(root))


def digest(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def local_url(root, url):
    """The local path the browser should use for `url`.

    Returns "" for a falsy url, and passes an ALREADY-local one straight
    through (run thumbnails are served from the run directory and were
    never remote). Registering is cheap and idempotent: the index maps
    digest -> url so a later /img/<digest> request knows what to fetch,
    and the bytes are only downloaded when something actually asks.
    """
    if not url or not isinstance(url, str):
        return ""
    if not url.startswith(("http://", "https://")):
        return url          # already local, or a data: URI -- leave alone
    d = digest(url)
    index = _read_index(root)
    if index.get(d) != url:
        index[d] = url
        _write_index(root, index)
    return f"/img/{d}"


def _fetchable(url):
    """Reject anything that isn't a plain remote image fetch.

    Defence in depth: URLs reaching here came from the index, so they came
    from real run data rather than from a request -- but a provider
    controls its own playlist, and a tvg-logo of "http://192.168.0.1/" is
    entirely within its power to write. Resolving the host and refusing
    private space stops a hostile playlist turning this into an internal
    port scanner.
    """
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    return True


def _blob_path(root, d):
    return os.path.join(_dir(root), d + ".blob")


def _meta_path(root, d):
    return os.path.join(_dir(root), d + ".json")


def get(root, d):
    """(bytes, content_type) for a digest, fetching once if needed.

    Returns None when the digest is unknown, the URL is not fetchable, or
    the fetch failed -- every one of which the caller renders as a plain
    404 rather than an error, because a missing logo is not a problem
    worth interrupting anyone over.
    """
    if not d or not d.isalnum():
        return None
    blob, meta = _blob_path(root, d), _meta_path(root, d)
    if os.path.exists(blob) and os.path.exists(meta):
        try:
            with open(meta, encoding="utf-8") as f:
                ctype = json.load(f).get("content_type") or "image/png"
            with open(blob, "rb") as f:
                return f.read(), ctype
        except OSError:
            pass
    url = _read_index(root).get(d)
    if not url or not _fetchable(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "channeliq"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            body = r.read(MAX_BYTES + 1)
    except Exception:
        return None
    if len(body) > MAX_BYTES:
        return None
    if not ctype.startswith("image/"):
        # Some CDNs serve images as octet-stream; fall back to the URL's own
        # extension rather than refusing something that plainly is one.
        guessed = mimetypes.guess_type(urllib.parse.urlparse(url).path)[0] or ""
        if not guessed.startswith("image/"):
            return None
        ctype = guessed
    try:
        os.makedirs(_dir(root), exist_ok=True)
        with open(blob + ".tmp", "wb") as f:
            f.write(body)
        os.replace(blob + ".tmp", blob)
        with open(meta + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"content_type": ctype, "url": url, "bytes": len(body)}, f)
        os.replace(meta + ".tmp", meta)
    except OSError:
        pass        # serving it matters more than caching it
    return body, ctype
