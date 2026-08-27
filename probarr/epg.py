"""XMLTV guide loading and "what should be on right now" lookup.

The point of this module is a check no probe can perform: whether the picture
arriving is the programme the guide claims. A stream can be alive, clean,
high-bitrate and completely wrong -- the guide says one film and a different
film is playing. That fault is invisible to every automated test and obvious
to a person looking at a thumbnail with the expected title printed under it.

Two details matter:

1. The expected programme is resolved **at probe time**, not at viewing time,
   and stored alongside the frame. A contact sheet opened the next morning
   must show what was supposed to be on when the frame was grabbed, not what
   is on now, or the comparison is meaningless.

2. Channel ids rarely line up. A playlist may use tvg-id "1" while the guide
   uses "BBC.One.Lon.HD.uk". So matching falls back to display names through
   the same normaliser used for stream matching.
"""
import datetime
import gzip
import io
import re
import urllib.request
import xml.etree.ElementTree as ET

_TIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-]\d{4})?")


def parse_xmltv_time(value):
    """'20260821080000 +0000' -> aware datetime. None if unparseable."""
    if not value:
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, se, off = m.groups()
    try:
        dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(se or 0))
    except ValueError:
        return None
    if off:
        sign = 1 if off[0] == "+" else -1
        delta = datetime.timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
        return dt.replace(tzinfo=datetime.timezone(sign * delta))
    return dt.replace(tzinfo=datetime.timezone.utc)


class _Chained(io.RawIOBase):
    """A stream that replays a few already-read bytes, then continues.

    Needed only because gzip has to be detected from the first two bytes of
    a NON-seekable HTTP response. Reading those two bytes consumes them, and
    without this they would be lost.
    """

    def __init__(self, prefix, stream):
        self._prefix, self._stream = prefix, stream

    def readable(self):
        return True

    def readinto(self, b):
        n = 0
        if self._prefix:
            n = min(len(b), len(self._prefix))
            b[:n] = self._prefix[:n]
            self._prefix = self._prefix[n:]
            if n == len(b):
                return n
        chunk = self._stream.read(len(b) - n)
        if not chunk:
            return n
        b[n:n + len(chunk)] = chunk
        return n + len(chunk)

    def close(self):
        try:
            self._stream.close()
        finally:
            super().close()


class _ClosingGzipFile(gzip.GzipFile):
    """A GzipFile that closes the stream it was handed.

    gzip.GzipFile only closes a file it opened ITSELF (by name); given a
    `fileobj` it deliberately leaves it open, on the assumption the caller
    owns it. Here the caller does not -- _open() constructs the underlying
    handle purely to feed this -- so without cascading the close, every
    gzipped guide load leaked a file descriptor, and for an http(s) source
    a live socket. Verified: after gzip.GzipFile(fileobj=raw).close(),
    raw.closed is False.
    """

    def __init__(self, fileobj):
        super().__init__(fileobj=fileobj)
        self._wrapped = fileobj

    def close(self):
        try:
            super().close()
        finally:
            self._wrapped.close()


def _open(source, timeout=120):
    """Open a local path or URL as a STREAM, transparently decompressing gzip.

    Detects gzip by magic bytes rather than by '.gz' in the name: these
    aggregator URLs frequently serve gzip from an extensionless path, and
    content-encoding is not reliable either.

    Streams rather than returning BytesIO over the whole document. It used
    to .read() the entire file into memory and hand back a BytesIO, which
    put a floor under peak memory equal to the (decompressed) file size --
    tens of MB per source, before parsing had even started, and the other
    half of the high-memory report that got this looked at. A real guide is
    consumed strictly front-to-back by iterparse, so it never needed to be
    resident all at once.
    """
    if re.match(r"^https?://", source, re.I):
        req = urllib.request.Request(source, headers={"User-Agent": "probarr/0.1",
                                                      "Accept-Encoding": "gzip"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        head = resp.read(2)
        stream = io.BufferedReader(_Chained(head, resp))
        return _ClosingGzipFile(stream) if head == b"\x1f\x8b" else stream
    f = open(source, "rb")
    # Local files are seekable, so sniffing costs nothing and needs no
    # replay -- just rewind.
    head = f.read(2)
    f.seek(0)
    return _ClosingGzipFile(f) if head == b"\x1f\x8b" else f


class Guide:
    """An XMLTV guide, indexed for lookup by channel id or display name."""

    def __init__(self):
        self.display_names = {}   # channel_id -> [names]
        self.programmes = {}      # channel_id -> [(start, stop, title, desc)]
        self.icons = {}           # channel_id -> icon url (first one seen)
        self._by_key = {}         # normalised name -> channel_id

    # -- loading ------------------------------------------------------------
    @classmethod
    def load(cls, source, window_hours=48, at=None, timeout=120):
        """Parse an XMLTV file or URL.

        Only programmes within +/- window_hours of `at` are retained. These
        aggregated guides carry a fortnight of listings for thousands of
        channels; keeping all of it would cost hundreds of MB to answer a
        question about one afternoon.
        """
        at = at or datetime.datetime.now(datetime.timezone.utc)
        lo = at - datetime.timedelta(hours=window_hours)
        hi = at + datetime.timedelta(hours=window_hours)

        g = cls()
        # Closed explicitly: _open now returns a real streaming handle
        # rather than an in-memory BytesIO, so leaking it leaks a file
        # descriptor on every guide load -- and these are loaded on a TTL,
        # repeatedly, for the life of the process.
        stream = _open(source, timeout=timeout)
        try:
            # iterparse + clear() + DETACHING from the root. That last part is
            # the load-bearing bit, and its absence was a real reported bug: in
            # stdlib ElementTree, elem.clear() empties an element but leaves it
            # attached to its parent, so the root accumulates one empty element
            # per <channel> AND per <programme> in the whole file -- including
            # every programme outside the window that is deliberately discarded.
            # Measured on a synthetic 63MB guide: 104MB peak to retain 9MB of
            # useful data, scaling with file size, under a comment that claimed
            # peak stayed flat. Clearing the root as well takes the identical
            # parse to 0.3MB. lxml does this by deleting previous siblings;
            # stdlib has no parent pointer, so the root is cleared instead --
            # safe here because nothing below reads back a previous element.
            ctx = ET.iterparse(stream, events=("start", "end"))
            _, root = next(ctx)
            for event, elem in ctx:
                if event != "end":
                    continue
                tag = elem.tag.lower()
                if tag == "channel":
                    cid = elem.get("id") or ""
                    names = [(e.text or "").strip()
                             for e in elem.findall("display-name") if (e.text or "").strip()]
                    if cid and names:
                        g.display_names.setdefault(cid, []).extend(names)
                    # Only ever used as a FALLBACK when a channel's own M3U
                    # carries no tvg-logo at all -- an XMLTV aggregator's icon
                    # is frequently a generic placeholder or simply absent, so
                    # this is never preferred over what the provider itself
                    # supplied. First one seen wins; a channel id repeated
                    # across feeds in the same file is not expected to disagree
                    # with itself on its own icon.
                    if cid and cid not in g.icons:
                        icon_el = elem.find("icon")
                        src = (icon_el.get("src") or "").strip() if icon_el is not None else ""
                        if src:
                            g.icons[cid] = src
                elif tag == "programme":
                    start = parse_xmltv_time(elem.get("start"))
                    stop = parse_xmltv_time(elem.get("stop"))
                    # A programme that fully SPANS the window (starts
                    # before lo, ends after hi -- a long placeholder/all-day
                    # block some aggregators emit for sparsely-listed
                    # channels) satisfied neither half of the old test and
                    # was silently dropped even though it genuinely covers
                    # `at`. The third clause catches that case directly.
                    if start and (lo <= start <= hi or (stop and lo <= stop <= hi)
                                 or (stop and start < lo and stop > hi)):
                        cid = elem.get("channel") or ""
                        title_el = elem.find("title")
                        desc_el = elem.find("desc")
                        g.programmes.setdefault(cid, []).append((
                            start, stop,
                            (title_el.text or "").strip() if title_el is not None else "",
                            (desc_el.text or "").strip() if desc_el is not None else "",
                        ))
                else:
                    continue
                # Both branches above are done with this element. Emptying it is
                # not enough on its own -- it stays in the root's child list --
                # so the root goes too. See the note at the top of this loop.
                elem.clear()
                root.clear()
            for cid in g.programmes:
                g.programmes[cid].sort(key=lambda p: p[0])
        finally:
            stream.close()
        return g

    # -- indexing -----------------------------------------------------------
    def build_name_index(self, normalizer):
        """Index display names through the same normaliser used for streams."""
        self._by_key = {}
        for cid, names in self.display_names.items():
            for n in names:
                k = normalizer.key(n)
                if k:
                    self._by_key.setdefault(k, cid)
        return self

    MIN_FUZZY_LEN = 6

    def resolve(self, tvg_id=None, name=None, normalizer=None, fuzzy=True):
        """Find the guide's channel id for a stream. None when unmatched.

        Falls back to prefix matching because guides and playlists abbreviate
        differently -- a guide's "BBC One Lon HD" is a playlist's "BBC One
        London", and "Bloomberg HD" is "Bloomberg TV".

        Ambiguity is refused rather than guessed. A bare "BBC One" is a prefix
        of seventeen regional variants in a UK guide, and attaching the wrong
        region's listings to a channel is worse than showing none: it would
        make the picture look like it disagreed with the schedule when the
        schedule was simply the wrong one.
        """
        if tvg_id and (tvg_id in self.programmes or tvg_id in self.display_names):
            return tvg_id
        if not (name and normalizer):
            return None
        key = normalizer.key(name)
        if not key:
            return None
        hit = self._by_key.get(key)
        if hit or not fuzzy or len(key) < self.MIN_FUZZY_LEN:
            return hit
        cands = [k for k in self._by_key
                 if len(k) >= self.MIN_FUZZY_LEN and (k.startswith(key) or key.startswith(k))]
        if len(cands) != 1:
            return None
        return self._by_key[cands[0]]

    def search(self, query, limit=25):
        """Every channel whose display name contains `query` (substring,
        case-insensitive) -- for a person to browse when the automatic
        resolve() either found nothing or, worse, found the wrong entry
        while still returning a plausible-looking programme. A human
        scanning a short list of real names beats trusting a fuzzy-match
        algorithm on a channel that turned out to be filed under an odd
        or unexpected name.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        out = []
        for cid, names in self.display_names.items():
            hit = next((n for n in names if q in n.lower()), None)
            if hit:
                out.append((cid, hit))
                if len(out) >= limit:
                    break
        return out

    # -- lookup -------------------------------------------------------------
    def now_playing(self, channel_id, at):
        """The programme scheduled on `channel_id` at `at`. None if unknown."""
        if not channel_id:
            return None
        for start, stop, title, desc in self.programmes.get(channel_id, ()):
            if start <= at and (stop is None or at < stop):
                return {
                    "title": title,
                    "desc": desc,
                    "start": start.isoformat(),
                    "stop": stop.isoformat() if stop else None,
                    "window": f"{start.astimezone().strftime('%H:%M')}"
                              f"-{stop.astimezone().strftime('%H:%M')}" if stop else
                              start.astimezone().strftime('%H:%M'),
                }
        return None

    def stats(self):
        return {"channels": len(self.display_names),
                "with_programmes": len(self.programmes),
                "programmes": sum(len(v) for v in self.programmes.values())}
