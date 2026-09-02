"""Common stream record and source dispatch."""
import dataclasses
import re
from typing import Optional


@dataclasses.dataclass
class Stream:
    """One playable entry as offered by a provider.

    `id` is a source-stable identifier used to resume runs and to address the
    stream when exporting. For M3U inputs there is no provider id, so a hash
    of the URL is used.
    """
    id: str
    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    source: str = ""
    attrs: dict = dataclasses.field(default_factory=dict)

    def redacted_url(self) -> str:
        """URL safe to print or write into a shared HTML file.

        Provider URLs routinely carry account credentials as query parameters
        or path segments. The contact sheet is a file people will screenshot
        and paste into forum threads, so it must never carry a working
        subscription in it.
        """
        u = re.sub(r"(?i)([?&](?:username|password|user|pass|u|p|token|key)=)[^&]*",
                   r"\1***", self.url)
        # Xtream path form: http://host:port/USERNAME/PASSWORD/12345.ts
        u = re.sub(r"(?i)^(https?://[^/]+)/[^/]+/[^/]+/(\d+)", r"\1/***/***/\2", u)
        return u


_REGISTRY = {}


def register(scheme):
    def deco(fn):
        _REGISTRY[scheme] = fn
        return fn
    return deco


def load_source(spec: str, **kwargs):
    """Load streams from a source spec.

    Accepted forms:
      /path/to/list.m3u                 local playlist
      https://host/list.m3u             remote playlist
      dispatcharr://user:pass@host:9191 Dispatcharr instance
      xtream://user:pass@host:8080      Xtream Codes provider
    """
    m = re.match(r"^([a-z][a-z0-9+.-]*)://", spec, re.I)
    scheme = m.group(1).lower() if m else "file"
    if scheme in ("http", "https", "file"):
        scheme = "m3u"
    if scheme not in _REGISTRY:
        raise ValueError(f"no source handler for '{scheme}' "
                         f"(have: {', '.join(sorted(_REGISTRY))})")
    return _REGISTRY[scheme](spec, **kwargs)
