"""Channel-name normalisation and candidate grouping.

The core problem: a provider lists the same channel dozens of times under
cosmetically different names --

    UK: Meridian Sports 1
    UKFHD | Meridian Sports 1
    UKUHD: Meridian Sports 1 UHD
    UK 4K Meridian Sports 1
    HEVC FHD Meridian Sports 1
    Meridian Sports 1 HD [Multi-Audio]

-- and all of them are candidates for one logical channel.

This module is deliberately data-driven rather than hardcoded to one
provider's conventions. A regex that was too narrow ('^UK:' only) once hid a
genuine 4K feed that had been in the catalogue the whole time, so the tag
vocabulary lives in one editable place and `explain()` exists to show exactly
what got stripped.
"""
import re
import unicodedata

# Quality / format / delivery tags. Stripped wherever they appear, because
# they describe the *encode*, not the channel identity. Probing measures the
# real resolution anyway -- these labels are frequently lies.
QUALITY_TAGS = [
    "UHD", "FHD", "QHD", "HD", "SD", "4K", "8K", "1080P", "1080I", "720P",
    "576P", "480P", "2160P", "3840P", "7680P", "HEVC", "H265", "H264", "X265", "X264", "AVC",
    "MPEG2", "RAW", "LQ", "HQ", "MULTIAUDIO", "MULTI", "BACKUP", "ALT",
    "VIP", "PLUS", "PREMIUM", "SOURCE", "FEED", "TEST",
]

# Country / region markers. Present as a prefix on most providers' listings.
# Kept as a set so a source can be restricted to one region without the
# regex-authoring mistake that caused the original bug.
DEFAULT_REGION_TAGS = [
    "UK", "GB", "IE", "US", "USA", "CA", "AU", "NZ", "DE", "FR", "ES", "IT",
    "NL", "PT", "PL", "SE", "NO", "DK", "FI", "TR", "IN", "PK", "AR", "BR",
    "MX", "ZA", "EX", "EXYU", "AF", "ASIA", "LATINO", "ARB", "INT",
]

# Separators a provider might use between the tag block and the real name.
_SEP = r"[\s:|/\-–—\.]"


def _unifold(s: str) -> str:
    """NFKD-decompose stylised Unicode to its plain-ASCII equivalent,
    keeping spacing/punctuation intact -- unlike _fold(), which also
    collapses everything down to bare alphanumerics.

    Real reported case: a provider naming its variants in small-caps/
    superscript Unicode ("NPO 1 ᴿᴬᵂ" -- 'RAW' in small caps, "NPO 1
    ᵁᴴᴰ ³⁸⁴⁰ᵖ" -- 'UHD 3840p' in small caps/superscript). Those
    decompose to plain "RAW"/"UHD 3840P" under NFKD, so must be folded
    to that BEFORE the tag-stripping regexes below run -- they only ever
    match literal ASCII tag text, and were blind to the stylised originals
    entirely. Folding only at the very end (inside _fold(), as this used
    to) meant the disguised tag survived every strip and got baked into
    the final key instead of removed -- "NPO 1" and its own "RAW" variant
    normalised to two different, unmatching keys.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper()


def _fold(s: str) -> str:
    """Uppercase, strip accents, drop anything that isn't alphanumeric."""
    s = _unifold(s).replace("&", " AND ")
    return re.sub(r"[^A-Z0-9]+", "", s)


class Normalizer:
    """Turns a raw stream title into a stable matching key.

    region_tags=None means 'accept any region'. Pass an explicit list to
    restrict matching to one country -- important because loose prefix
    matching across a multi-country catalogue produces real false positives
    (a channel called 'W' once matched a Ukrainian channel because 'UKRAINE'
    starts with 'UK').
    """

    def __init__(self, region_tags=None, quality_tags=None, aliases=None,
                 drop_timeshift=True):
        self.region_tags = list(region_tags) if region_tags else list(DEFAULT_REGION_TAGS)
        self.quality_tags = list(quality_tags) if quality_tags else list(QUALITY_TAGS)
        self.aliases = {_fold(k): v for k, v in (aliases or {}).items()}
        self.drop_timeshift = drop_timeshift

        tagset = sorted(set(self.region_tags + self.quality_tags), key=len, reverse=True)
        alt = "|".join(re.escape(t) for t in tagset)
        # A leading run of tag tokens, in any order, optionally glued together
        # with no separator at all ("UKFHD", "UKUHD"), but the run as a whole
        # MUST terminate on a separator or end-of-string.
        #
        # That trailing requirement is load-bearing, not tidiness: without it
        # "UKRAINE: Futbol 1" matches the tag "UK", reports region UK, and
        # yields the key "RAINEFUTBOL1" -- a real cross-country false positive
        # of exactly the kind that puts a Ukrainian feed on a British channel.
        self._prefix_re = re.compile(
            rf"^(?:(?:{alt}){_SEP}*)*(?:{alt})(?:{_SEP}+|$)", re.IGNORECASE)
        # The same convention, trailing instead of leading -- "Cartoon
        # Network | US", "Discovery HD - UK". Idea from Lineuparr (another
        # open-source Dispatcharr tool): its region tagging covers both ends
        # of the name, not just the front. Requires a LEADING separator
        # before the tag run, the mirror of the prefix pattern's trailing
        # one, for the same reason -- without it "...Ukraine" would present
        # a bare "UK" substring with no boundary to refuse it on.
        self._suffix_re = re.compile(
            rf"(?:{_SEP}+(?:{alt}))+$", re.IGNORECASE)
        # The same tokens appearing as standalone words anywhere else.
        self._inline_re = re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])",
                                     re.IGNORECASE)
        self._bracket_re = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
        self._timeshift_re = re.compile(r"(?<![A-Za-z0-9])[+\-]\s?\d{1,2}\s?(H|HR|HRS)?(?![A-Za-z0-9])",
                                        re.IGNORECASE)

    def is_timeshift(self, name: str) -> bool:
        """True for '+1' style catch-up variants, which are a different channel."""
        return bool(self._timeshift_re.search(name))

    def region_of(self, name: str):
        """The region this title is marked with, if any. None when unmarked.

        Unmarked titles are common and legitimate ('HEVC FHD Meridian Sports 1'
        carries no country marker at all), so callers should decide whether to
        include them rather than have the matcher silently drop them.

        Two conventions, checked in order:

        1. A leading UK:/UKHD:/etc prefix (the common case).
        2. A 2-3 letter country code inside a bracketed segment anywhere in
           the name -- '(Claro) (CO) Cartoon Network', '(IT) (DZ) Discovery'.
           Real, evidenced case: a reseller brand like "Claro" or "DirecTV
           GO" is not itself a country, so the ONLY place the actual country
           lives is this bracket code -- the plain UK:-prefix check finds
           nothing and would otherwise let a Latin-American feed through as
           "unmarked".

        This is deliberately the single authoritative answer for a name --
        group_candidates() only falls back to the group-title field when
        THIS returns None, never to override it. Confirmed against real
        data: a genuinely UK:-prefixed stream can sit in an oddly-named group
        ('UK: TLC' filed under 'Discovery Plus'), and the explicit name
        marker should win, not get second-guessed by the group.
        """
        head = self._prefix_re.match(name)
        if head:
            folded = _fold(head.group(0))
            for tag in sorted(self.region_tags, key=len, reverse=True):
                if folded.startswith(_fold(tag)):
                    return tag.upper()
        tail = self._suffix_re.search(name)
        if tail:
            folded = _fold(tail.group(0))
            for tag in sorted(self.region_tags, key=len, reverse=True):
                if folded.endswith(_fold(tag)):
                    return tag.upper()
        for bracket in self._bracket_re.findall(name):
            code = re.sub(r"[^A-Za-z]", "", bracket).upper()
            if code in _BRACKET_COUNTRY_CODES:
                return _BRACKET_COUNTRY_CODES[code]
        return None

    def strip(self, name: str) -> str:
        """Packaging-stripped, folded identity -- WITHOUT the alias lookup.

        Split out of key() so aliases.py can fold a name through exactly
        the same pipeline key() itself uses before consulting the alias
        dict. Real bug this fixes: aliases.save() used to fold the raw
        typed text with plain _fold(), while key() strips region/quality
        prefixes, brackets and inline tags FIRST and only folds what's
        left -- so an alias saved for a name that still carried a prefix
        (e.g. "UK: Dave") was stored under a key ("UKDAVE") that key()'s
        own lookup, computed from the stripped name ("DAVE"), could never
        produce. Only alias names with nothing to strip in the first place
        happened to work.
        """
        # Folded to plain ASCII FIRST, not last: a provider that renders its
        # own tags in small-caps/superscript Unicode ("ᴿᴬᵂ" for "RAW") is
        # otherwise invisible to every regex below, which only ever matches
        # literal ASCII tag text -- see _unifold()'s own docstring for the
        # real case this fixes.
        s = _unifold(name)
        # A '+1' channel is a genuinely different channel, not a variant of the
        # same one, so it gets its own key rather than being stripped. Rewrite
        # the marker to a word so "Meridian Sports 1 +1" cannot collide with a
        # hypothetical "Meridian Sports 1 1".
        s = self._timeshift_re.sub(lambda m: " TIMESHIFT" + re.sub(r"\D", "", m.group(0)) + " ", s)
        s = self._prefix_re.sub(" ", s)
        s = self._bracket_re.sub(" ", s)
        s = self._inline_re.sub(" ", s)
        return _fold(s)

    def key(self, name: str) -> str:
        """The matching key: identity only, all packaging stripped."""
        folded = self.strip(name)
        return self.aliases.get(folded, folded)

    def explain(self, name: str) -> dict:
        """Show what normalisation did to a title. Used by `probarr explain`.

        Exists because the failure mode here is silent: a too-narrow rule
        doesn't error, it just quietly yields fewer candidates.
        """
        return {
            "raw": name,
            "region": self.region_of(name),
            "prefix_stripped": (m.group(0) if (m := self._prefix_re.match(name)) else ""),
            "timeshift": self.is_timeshift(name),
            "key": self.key(name),
        }


# Full-form country/region names as seen in real M3U group-title fields --
# a genuinely common, separate convention from the UK:/UKHD: name-prefix
# style Normalizer.region_of() already handles. Found for real: a
# multi-country provider whose foreign entries carried NO region marker in
# the name at all (often wrapped in brackets probarr already strips as
# decoration, e.g. "(PT) (Meo) TLC"), but a reliable full country name in
# group-title ("Portugal", "Poland", "Russia", "Austria", "Romania"...).
# Checking name alone let every one of those through as "unmarked" once
# --regions UK was applied, and a generically-named channel like "TLC"
# collapsed 23 different countries' TLC feeds into one candidate pool.
#
# Deliberately NOT exhaustive -- a provider using a platform/reseller brand
# as its group ("CLARO", "DirecTV GO") rather than a country name will not
# be caught by this, and that is a real, stated limitation, not a bug: no
# list can cover every provider's group-title convention. The contact
# sheet's frame is still the actual backstop for whatever slips through.
_LONG_REGION_NAMES = {
    "UNITED KINGDOM": "UK", "UK ENTERTAINMENT": "UK", "GREAT BRITAIN": "UK",
    "UNITED STATES": "US", "US ENTERTAINMENT": "US", "USA ENTERTAINMENT": "US",
    "PORTUGAL": "PT", "POLAND": "PL", "AUSTRIA": "AT", "ROMANIA": "RO",
    "MEXICO": "MX", "ARGENTINA": "AR", "VIETNAM": "VT", "RUSSIA": "RU",
    "GERMANY": "DE", "FRANCE": "FR", "SPAIN": "ES", "ITALY": "IT",
    "NETHERLANDS": "NL", "SWEDEN": "SE", "NORWAY": "NO", "DENMARK": "DK",
    "FINLAND": "FI", "TURKEY": "TR", "INDIA": "IN", "PAKISTAN": "PK",
    "BRAZIL": "BR", "SOUTH AFRICA": "ZA", "CANADA": "CA", "AUSTRALIA": "AU",
    "NEW ZEALAND": "NZ", "LATINO": "LATINO", "ASIA": "ASIA", "ARABIC": "ARB",
    "CHILE": "CL",
}
# Sorted longest-first so "NEW ZEALAND" is tried before a shorter accidental
# substring match, and so multi-word names match correctly as whole words.
_LONG_REGION_NAMES_SORTED = sorted(_LONG_REGION_NAMES, key=len, reverse=True)

# Reseller/platform brands that are themselves not a country name but are, in
# practice, exclusively used for one region's catalogue. Evidenced case: group
# titles like "CLARO" and "DirecTV GO" carry no country name at all (Claro and
# DirecTV GO are Latin-America-only platforms), so a channel filed under them
# with no other marker would otherwise pass through --regions UK as
# "unmarked". Deliberately NOT extended to brands with genuine UK presence
# ("SamsungTV", "PLEX") -- those really are multi-region and would produce
# false rejections.
_PLATFORM_BRAND_REGIONS = {
    "CLARO": "LATINO",
    "DIRECTV GO": "LATINO",
    "DIRECTVGO": "LATINO",
}

# 2-3 letter country codes as seen inside bracketed segments of a channel
# name, e.g. "(CO) Cartoon Network", "(Claro) (AR) TLC". A separate, real
# convention from both the name-prefix and the group-title conventions above
# -- evidenced directly from labeled examples where the ONLY country signal
# anywhere on the stream was this bracket code.
_BRACKET_COUNTRY_CODES = {
    "UK": "UK", "GB": "UK", "US": "US", "USA": "US", "CA": "CA", "CAN": "CA",
    "MX": "MX", "AR": "AR", "BR": "BR", "CO": "CO", "CL": "CL", "PE": "PE",
    "EC": "EC", "VE": "VE", "PA": "PA", "UY": "UY", "PY": "PY", "BO": "BO",
    "DO": "DO", "PT": "PT", "ES": "ES", "IT": "IT", "FR": "FR", "DE": "DE",
    "NL": "NL", "PL": "PL", "AT": "AT", "RO": "RO", "RU": "RU", "SE": "SE",
    "NO": "NO", "DK": "DK", "FI": "FI", "TR": "TR", "IN": "IN", "PK": "PK",
    "ZA": "ZA", "AU": "AU", "NZ": "NZ", "DZ": "DZ",
}


def group_of(group_title):
    """Region implied by an M3U group-title.

    Complements Normalizer.region_of() (name-prefix / bracket-code based)
    with the other common convention: the group-title field naming the
    country (or a country-exclusive platform brand), independent of whatever
    the channel name itself says.

    Uses substring matching, not an exact whole-title match -- real group
    titles embed the country name inside a longer string ("Meridian New Zealand",
    "US Sports", "US Locals & Regional", "CA Amazon Prime Linear"), so an
    exact-match check silently missed all of these.
    """
    if not group_title:
        return None
    folded = re.sub(r"[^A-Z ]", "", group_title.upper()).strip()
    if not folded:
        return None
    for name in _LONG_REGION_NAMES_SORTED:
        if re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", folded):
            return _LONG_REGION_NAMES[name]
    for brand, region in _PLATFORM_BRAND_REGIONS.items():
        if brand in folded:
            return region
    # Short 2-3 letter country code as a leading standalone word, e.g.
    # "US Sports", "US Locals & Regional", "CA Amazon Prime Linear" -- real
    # group-title convention distinct from the full-name one above.
    first_word = folded.split(" ", 1)[0]
    if first_word in _BRACKET_COUNTRY_CODES:
        return _BRACKET_COUNTRY_CODES[first_word]
    return None


# Delimiters seen between a country marker and the rest of a group-title --
# Dispatcharr's own convention pipes them ("UK | Amazon Events"), other
# panels use a colon or bare space. Reuses the same separator set region_of()
# builds its prefix/suffix regexes from, so a new delimiter never needs
# provider-specific configuration -- see the module docstring.
_GROUP_SEP_RE = re.compile(rf"^{_SEP}+")


def split_group_title(group_title):
    """(country, category) for Browse Channels' two-level filter.

    country is a normalised code (e.g. "UK", "US") or None when the
    group-title carries no recognisable country marker at all -- the
    category is then the whole original string, unchanged. Complements
    group_of() (country only) by also returning the leftover text once the
    matched country token and its adjacent separator are stripped, so a
    provider's category name ("Amazon Events", "Sports HD") survives
    whichever delimiter convention it uses.
    """
    if not group_title:
        return None, ""
    folded = re.sub(r"[^A-Z ]", "", group_title.upper()).strip()
    if not folded:
        return None, group_title

    # Full country name, e.g. "Canada Amazon Prime Linear" -- strip the
    # matched name itself (which may be multiple words) plus one leading
    # separator run from the rest of the ORIGINAL string, not the folded
    # one, so punctuation/casing in the category survives untouched.
    for name in _LONG_REGION_NAMES_SORTED:
        m = re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", folded)
        if m and m.start() == 0:
            # Only a LEADING full-name match is stripped into a category --
            # locating an arbitrary mid-string match in the original
            # (unfolded) text by offset isn't reliable once folding has
            # dropped punctuation, so a non-leading match still reports the
            # country but leaves the category as the untouched original.
            country = _LONG_REGION_NAMES[name]
            category = _strip_leading_token(group_title, len(name.split()))
            return country, category
        if m:
            return _LONG_REGION_NAMES[name], group_title

    for brand, region in _PLATFORM_BRAND_REGIONS.items():
        if brand in folded:
            return region, group_title

    # Short 2-3 letter country code as a leading OR trailing standalone
    # word -- the other real convention, distinct from the full-name one
    # above (see group_of()'s own docstring for evidenced examples).
    words = folded.split(" ")
    if words and words[0] in _BRACKET_COUNTRY_CODES:
        return _BRACKET_COUNTRY_CODES[words[0]], _strip_leading_token(group_title, 1)
    if len(words) > 1 and words[-1] in _BRACKET_COUNTRY_CODES:
        return _BRACKET_COUNTRY_CODES[words[-1]], _strip_trailing_token(group_title)

    return None, group_title


def _strip_leading_token(text, n_words):
    """`text` with its first `n_words` words and one following separator run
    removed -- used to turn "UK | Amazon Events" / "US Sports HD" /
    "Canada Amazon Prime Linear" into just the category half, keeping
    whatever separator style and casing the category itself used."""
    m = re.match(rf"^\s*\S+(?:{_SEP}+\S+){{{n_words - 1}}}", text)
    if not m:
        return text.strip()
    return _GROUP_SEP_RE.sub("", text[m.end():]).strip()


def _strip_trailing_token(text):
    """`text` with its last word and one preceding separator run removed --
    the mirror of _strip_leading_token, for a trailing country marker
    ("Cartoon Network | US")."""
    m = re.search(rf"{_SEP}+\S+$", text)
    if not m:
        return text.strip()
    return text[:m.start()].strip()


def group_candidates(streams, normalizer, include_timeshift=False,
                     regions=None, include_unmarked=True):
    """Bucket streams into {key: [stream, ...]} candidate pools.

    regions: restrict to these region tags (list of upper-case strings).
    include_unmarked: also keep streams carrying no region marker at all.
    """
    pools = {}
    for s in streams:
        name = s.name
        if not include_timeshift and normalizer.is_timeshift(name):
            continue
        if regions is not None:
            r = normalizer.region_of(name)
            # The name-based marker is authoritative when present: an
            # explicit "UK:" prefix (or bracket country code) on the name
            # wins even if the group-title looks like a different or
            # confusing region ("UK: TLC" filed under group "Discovery
            # Plus" must not be rejected just because "Discovery Plus"
            # carries no recognisable country). Only fall back to the
            # group-title signal when the name gives no signal at all.
            if r is not None:
                if r not in regions:
                    continue
            else:
                g = group_of(getattr(s, "group", ""))
                if g is not None:
                    if g not in regions:
                        continue
                elif not include_unmarked:
                    continue
        k = normalizer.key(name)
        if not k:
            continue
        pools.setdefault(k, []).append(s)
    return pools


# Coarse best-declared-first ordering, used to decide which candidates to
# probe FIRST -- not a quality verdict. Declared labels are frequently wrong
# about identity (the whole reason this tool probes at all), but as a
# pre-probe ordering hint they beat the M3U file's arbitrary listing order,
# and trying the plausibly-best candidate first means an adaptive probe run
# can often stop after 2 tries instead of working through a whole pool.
# Declared bitrate is deliberately not part of this: it is almost never
# present in a stream's NAME (only occasionally in metadata, which requires
# actually connecting to read -- see probe.py's probe_metadata()), so there
# is no free pre-probe bitrate signal to rank on the way there is for
# resolution tags.
_DECLARED_QUALITY_RANK = {
    "8K": 100, "4320P": 100, "7680P": 100,
    "UHD": 90, "4K": 90, "2160P": 90, "3840P": 90,
    "QHD": 70, "1440P": 70,
    "FHD": 60, "1080P": 60, "1080I": 55,
    "HD": 40, "720P": 40,
    "SD": 10, "576P": 10, "480P": 8,
}
_DECLARED_QUALITY_RE = re.compile(
    r"(?<![A-Z0-9])(" + "|".join(_DECLARED_QUALITY_RANK) + r")(?![A-Z0-9])")


def declared_quality_rank(name: str) -> int:
    """Best-effort pre-probe ordering score from the name's own quality tags.
    Higher is "plausibly better". 0 for a name with no recognisable tag --
    sorts after anything labelled, but stably (Python's sort is stable, so
    unlabelled candidates keep their original relative order among themselves).
    """
    if not name:
        return 0
    folded = name.upper()
    hits = _DECLARED_QUALITY_RE.findall(folded)
    return max((_DECLARED_QUALITY_RANK[h] for h in hits), default=0)
