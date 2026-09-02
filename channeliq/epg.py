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


def _open(source, timeout=120):
    """Open a local path or URL as a STREAM, transparently decompressing gzip.

    Streams throughout: the caller (iterparse) pulls bytes as it parses
    rather than the whole file/response being buffered in memory up front,
    which matters for aggregated XMLTV feeds that can run into the
    gigabytes uncompressed.

    Detects gzip by magic bytes rather than by '.gz' in the name: these
    aggregator URLs frequently serve gzip from an extensionless path, and
    content-encoding is not reliable either. Magic-byte detection needs the
    first two bytes, so we peek them via a small buffered read and
    reconstruct a stream that still yields those bytes first.

    Streams rather than returning BytesIO over the whole document. It used
    to .read() the entire file into memory and hand back a BytesIO, which
    put a floor under peak memory equal to the (decompressed) file size --
    tens of MB per source, before parsing had even started, and the other
    half of the high-memory report that got this looked at. A real guide is
    consumed strictly front-to-back by iterparse, so it never needed to be
    resident all at once.
    """
    if re.match(r"^https?://", source, re.I):
        req = urllib.request.Request(source, headers={"User-Agent": "channeliq/0.1",
                                                      "Accept-Encoding": "gzip"})
        raw = urllib.request.urlopen(req, timeout=timeout)
    else:
        raw = open(source, "rb")
    head = raw.read(2)
    stream = io.BufferedReader(_ChainedStream(head, raw))
    if head == b"\x1f\x8b":
        # gzip.GzipFile only closes a fileobj it opened itself (by name);
        # given an existing fileobj it deliberately leaves it open, on the
        # assumption the caller owns it. The caller here does not -- _open()
        # built `stream` purely to feed this -- so without cascading the
        # close, every gzipped guide load leaks the underlying handle, and
        # for an http(s) source a live socket.
        gz = gzip.GzipFile(fileobj=stream)
        gz.close = lambda: (gzip.GzipFile.close(gz), stream.close())
        return gz
    return stream


class _ChainedStream(io.RawIOBase):
    """A raw stream that yields `head` before continuing to read `tail`."""

    def __init__(self, head, tail):
        self._head = head
        self._tail = tail

    def readable(self):
        return True

    def readinto(self, b):
        if self._head:
            n = min(len(b), len(self._head))
            b[:n] = self._head[:n]
            self._head = self._head[n:]
            return n
        data = self._tail.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self):
        self._tail.close()
        super().close()


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
            g._parse(stream, lo, hi)
        finally:
            stream.close()
        for cid in g.programmes:
            g.programmes[cid].sort(key=lambda p: p[0])
        return g

    def _parse(self, stream, lo, hi):
        # iterparse + clear() only empties an element's own text/children --
        # it stays attached to its parent (the root), so the root's child
        # list would otherwise grow by one stub per channel/programme ever
        # seen. We track the root via the "start" event and explicitly
        # remove each element from it once consumed, so peak memory stays
        # flat regardless of file size.
        g = self
        root = None
        for event, elem in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = elem
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
                elem.clear()
                if elem is not root and root is not None:
                    root.remove(elem)
            elif tag == "programme":
                start = parse_xmltv_time(elem.get("start"))
                stop = parse_xmltv_time(elem.get("stop"))
                # A programme that fully SPANS the window (starts before lo,
                # ends after hi -- a long placeholder/all-day block some
                # aggregators emit for sparsely-listed channels) satisfies
                # neither of the first two clauses and was silently dropped
                # even though it genuinely covers `at`. The third clause
                # catches that case directly.
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
                elem.clear()
                if elem is not root and root is not None:
                    root.remove(elem)

    # -- indexing -----------------------------------------------------------
    def build_name_index(self, normalizer):
        """Index display names through the same normaliser used for streams.

        Real reported bug: a combined guide routinely carries an SD and an
        HD row for the SAME channel as two entirely separate <channel>
        elements with distinct ids and their own independent programme
        lists ("Sky Atlantic" / "Sky Atlantic HD", confirmed live in the
        sheffield_hd.xml feed) -- and once "HD" strips as a quality tag,
        both normalise to the identical key. A bare setdefault() kept
        whichever one happened to parse first and silently discarded the
        other, with no signal that a choice was even made. If Dispatcharr
        (or a fresh install) ends up linked to the OTHER one of the pair,
        every comparison against this guide reports a permanent, false
        "wrong programme" mismatch for that channel -- not because either
        link is actually wrong, but because the SD and HD copies just
        happen to be showing something different at THIS particular
        moment, same as any two live variants of one broadcast naturally
        drift out of sync from feed processing.

        resolve()'s own docstring already commits to refusing ambiguity
        rather than guessing -- previously true only on the fuzzy-prefix
        path. A key two DIFFERENT channel ids both genuinely earn is
        exactly that same ambiguity, and gets the same refusal here --
        UNLESS the colliding raw names differ by nothing but a quality
        tag (an SD/HD pair naming the one real channel, the exact shape
        confirmed live), in which case the HD copy is kept automatically
        instead of throwing the whole channel away. Two names that
        collide for any OTHER reason (different regions, a genuine
        coincidence) still refuse exactly as before -- this is narrower
        than "was ambiguous, pick one somehow", not a replacement for it.
        """
        self._by_key = {}
        # key -> {cid: one representative raw name for that cid} -- several
        # display-name aliases for the SAME cid must not inflate this into
        # a false collision, so only the first name seen per cid is kept.
        groups = {}
        for cid, names in self.display_names.items():
            for n in names:
                k = normalizer.key(n)
                if not k:
                    continue
                groups.setdefault(k, {}).setdefault(cid, n)
        for k, by_cid in groups.items():
            if len(by_cid) == 1:
                self._by_key[k] = next(iter(by_cid))
                continue
            resolved = self._resolve_quality_duplicate(by_cid, normalizer)
            if resolved:
                self._by_key[k] = resolved
            # else: genuinely ambiguous -- left out of the index entirely,
            # same as before, so resolve() reports "unmatched" rather than
            # guessing.
        return self

    @staticmethod
    def _resolve_quality_duplicate(by_cid, normalizer):
        """`by_cid`: {channel_id: raw_name} for every id sharing one key.

        Returns the HD one's id if every name in the group is identical
        once quality words are stripped (see Normalizer.
        quality_stripped_identity()) AND exactly one of them is tagged
        HD -- None otherwise, which leaves the caller's ambiguity refusal
        in force. "Exactly one" deliberately: a group carrying both an
        "HD" and an "FHD" entry (or two separately-tagged HD rows from a
        merged feed) is not a clean SD/HD pair, and guessing between two
        HD-tier candidates is exactly the kind of guess this was built
        to avoid making.
        """
        names = list(by_cid.values())
        identities = {normalizer.quality_stripped_identity(n) for n in names}
        if len(identities) != 1:
            return None
        qre = normalizer._quality_word_re
        if qre is None:
            return None
        hd_cids = [cid for cid, n in by_cid.items()
                  if any(w.strip().upper() == "HD" for w in qre.findall(n))]
        return hd_cids[0] if len(hd_cids) == 1 else None

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

        Real reported bug: fuzzy prefix matching had no timeshift awareness,
        so once an ambiguous SD/HD pair correctly refused to resolve by
        exact name (see build_name_index()), the ONLY remaining candidate
        left in a startswith scan was routinely the channel's own "+1"
        entry ("SKY ATLANTIC" is a prefix of normalizer.key()'s own
        "SKY ATLANTIC TIMESHIFT1") -- a single candidate, so the ambiguity
        check never triggered, and a channel silently got linked to its own
        hour-shifted sibling. normalize.py already treats a '+1' channel as
        "a genuinely different channel, not a variant of the same one" for
        exactly this reason; fuzzy matching here now honours that instead
        of only guarding against it on the exact-match path.
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
        # A timeshift query only ever matches another timeshift key, and a
        # plain query only ever matches another plain key -- never mixed,
        # so "Sky Atlantic" can never fuzzy-resolve to its own "+1" sibling
        # (or vice versa) purely because one is a prefix of the other.
        query_is_timeshift = "TIMESHIFT" in key
        cands = [k for k in self._by_key
                 if len(k) >= self.MIN_FUZZY_LEN and (k.startswith(key) or key.startswith(k))
                 and ("TIMESHIFT" in k) == query_is_timeshift]
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
    def search_programmes_at(self, query, at, tolerance_minutes=90, limit=25):
        """Every programme, on ANY channel, whose title contains `query`
        (substring, case-insensitive) and whose scheduled window falls
        within `tolerance_minutes` of `at`.

        The other lookups here answer "what's on THIS channel" -- this
        answers the opposite question: a captured picture obviously does
        not match the channel it was probed as (a human recognised the
        film on screen), so which channel's own schedule actually explains
        it? Real, if rare, cause: a provider's playlist entry pointing at
        the wrong upstream feed under a channel name that has nothing to
        do with what it actually serves.

        A programme with no `stop` (some feeds omit it) is treated as
        running 3 hours -- long enough to cover any real broadcast slot,
        short enough that an all-day placeholder does not swallow every
        query regardless of `at`.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        tol = datetime.timedelta(minutes=tolerance_minutes)
        lo, hi = at - tol, at + tol
        out = []
        for cid, progs in self.programmes.items():
            for start, stop, title, desc in progs:
                if q not in title.lower():
                    continue
                end = stop or (start + datetime.timedelta(hours=3))
                if start <= hi and end >= lo:
                    names = self.display_names.get(cid) or []
                    out.append({
                        "guide_id": cid, "guide_name": names[0] if names else cid,
                        "title": title,
                        "start": start.isoformat(), "stop": stop.isoformat() if stop else None,
                        "window": (f"{start.astimezone().strftime('%H:%M')}"
                                  f"-{stop.astimezone().strftime('%H:%M')}" if stop else
                                  start.astimezone().strftime('%H:%M')),
                    })
                    if len(out) >= limit:
                        return out
        return out

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
