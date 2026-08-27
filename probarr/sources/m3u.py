"""M3U / M3U8 extended playlist parsing and writing.

Handles the extended (#EXTINF) form every IPTV provider emits, including
attribute quirks: unquoted values, attributes after the comma, duplicate
tvg-name/tvg-id, and #EXTGRP lines for group membership.
"""
import hashlib
import re
import urllib.request

from .base import Stream, register

_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*("(?:[^"]*)"|\'(?:[^\']*)\'|[^\s,]+)')

# A stream entry line has to look like an address -- some scheme://, or an
# absolute filesystem path. Without this, any non-comment line at all is
# accepted as a "stream", which is a real problem when the fetched content
# was never a playlist to begin with: a typo'd provider URL commonly 404s to
# an HTML error page (or, seen for real against Dispatcharr, an SPA that
# serves index.html for any unmatched route with HTTP 200). Every plain-text
# line of that HTML -- `<meta charset="UTF-8" />` and the like -- is neither
# blank nor "#"-prefixed, so it was silently accepted as a channel. A "Test
# connection" feature whose entire purpose is catching a wrong URL must not
# report a bogus 32-channel success for exactly that mistake.
_URL_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.-]*://|/)')


def _stream_id(url: str) -> str:
    return "m3u:" + hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:16]


def looks_like_m3u(text: str) -> bool:
    """True if the text is plausibly a playlist rather than some other document."""
    head = text.lstrip("﻿ \t\r\n")[:4096]
    return bool(re.match(r'(?i)^#EXTM3U', head))


def parse(text: str, source_name: str = "m3u"):
    """Parse playlist text into Stream objects."""
    streams = []
    pending = None
    pending_group = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTM3U"):
            continue
        if line.upper().startswith("#EXTINF"):
            # #EXTINF:-1 tvg-id="x" tvg-logo="y" group-title="z",Display Name
            body = line.split(":", 1)[1] if ":" in line else ""
            title = body.split(",", 1)[1].strip() if "," in body else ""
            attr_part = body.split(",", 1)[0]
            attrs = {}
            for k, v in _ATTR_RE.findall(attr_part):
                attrs[k.lower()] = v.strip("\"'")
            pending = (title, attrs)
            continue
        if line.upper().startswith("#EXTGRP"):
            pending_group = line.split(":", 1)[1].strip() if ":" in line else ""
            continue
        if line.startswith("#"):
            continue  # any other directive (#EXTVLCOPT, #KODIPROP, ...)
        if not _URL_RE.match(line) or "<" in line or ">" in line:
            # Not an address -- almost always a sign the fetched content was
            # never a playlist (see the note on _URL_RE above), not a real
            # channel entry. A genuine relative-path playlist line is rare
            # enough on real providers that erring toward rejection is the
            # safer default.
            #
            # The '<'/'>' check catches a case _URL_RE alone does not: a
            # self-closing HTML tag whose attributes span multiple lines
            # leaves a bare '/>' on its own line, which satisfies "starts
            # with /" despite being HTML wreckage, not a path. Confirmed for
            # real against an SPA's index.html served for an unmatched route.
            pending, pending_group = None, ""
            continue

        title, attrs = pending if pending else ("", {})
        name = title or attrs.get("tvg-name") or line
        streams.append(Stream(
            id=_stream_id(line),
            name=name,
            url=line,
            group=attrs.get("group-title") or pending_group,
            logo=attrs.get("tvg-logo", ""),
            tvg_id=attrs.get("tvg-id", ""),
            source=source_name,
            attrs=attrs,
        ))
        pending, pending_group = None, ""
    return streams


@register("m3u")
def load(spec: str, timeout: int = 60, **_):
    if re.match(r"^https?://", spec, re.I):
        req = urllib.request.Request(spec, headers={"User-Agent": "probarr/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
        label = spec.split("?")[0]
    else:
        path = spec[7:] if spec.lower().startswith("file://") else spec
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            # A bare FileNotFoundError/PermissionError ("[Errno 2] No such
            # file or directory: '/config/x.m3u'") means nothing to someone
            # looking at it in the UI -- it doesn't say the one thing that
            # actually explains it: probarr runs in a container, so a local
            # M3U provider has to be a path INSIDE that container's own
            # mounted config volume, not just anywhere on the host. Losing
            # track of that (the file sitting one directory up on the host,
            # or only ever copied into one of two separate environments --
            # test and production commonly use different config mounts)
            # is the actual, real, reported cause every time this fires.
            raise ValueError(
                f"can't read local file {path!r}: {e.strerror or e}. "
                "A local M3U source has to be a path inside this "
                "container's own mounted config directory -- check the "
                "file was actually copied there (test and production "
                "commonly use separate config folders, so a file present "
                "in one is not automatically present in the other).") from e
        label = path
    streams = parse(text, source_name=label)
    if not streams and not looks_like_m3u(text):
        # Distinguishes "a real, empty playlist" (rare, but legitimate) from
        # "this was never a playlist" (a wrong URL, an auth wall, a 404 page
        # served as HTTP 200 -- all real things a provider address gets wrong
        # in practice). The latter deserves a clear error, not a silent
        # zero-channel result that looks identical to the former.
        snippet = text.strip().replace("\n", " ")[:120]
        raise ValueError(
            f"response from '{label}' does not look like an M3U playlist "
            f"(no #EXTM3U header, no channel lines found) -- got: {snippet!r}")
    return streams


def write(streams_with_numbers, path, name_key="name"):
    """Write an M3U. Items are (number, name, group, logo, tvg_id, url) tuples."""
    lines = ['#EXTM3U']
    for num, name, group, logo, tvg_id, url in streams_with_numbers:
        attrs = []
        if tvg_id:
            attrs.append(f'tvg-id="{tvg_id}"')
        if num is not None:
            attrs.append(f'tvg-chno="{num}"')
        if logo:
            attrs.append(f'tvg-logo="{logo}"')
        attrs.append(f'group-title="{group or "probarr"}"')
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(url)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
