"""Xtream Codes provider as a stream source.

Most 'IPTV subscription' panels speak this. Reading the structured API rather
than the flat M3U gives real category names and stream ids, and avoids pulling
a 50k-line playlist to find one channel.
"""
import urllib.parse

from .. import http
from .base import Stream, register


class Xtream:
    def __init__(self, base_url, username, password, timeout=60):
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    def _api(self, action, **params):
        q = {"username": self.username, "password": self.password, "action": action}
        q.update(params)
        url = f"{self.base}/player_api.php?" + urllib.parse.urlencode(q)
        return http.request(url, timeout=self.timeout)

    def live_streams(self):
        # Both sides cast to str. Real bug: this dict used to be keyed by
        # category_id's NATIVE JSON type (some panels emit it as a number,
        # not a numeric string) while the per-stream lookup always cast to
        # str -- a panel serving numeric category ids meant every lookup
        # missed and every stream silently lost its group, with categories
        # and streams both fetched correctly but never actually joined.
        cats = {str(c["category_id"]): c["category_name"]
                for c in (self._api("get_live_categories") or [])}
        out = []
        for s in (self._api("get_live_streams") or []):
            sid = s["stream_id"]
            out.append(Stream(
                id=f"xtream:{sid}",
                name=s.get("name", ""),
                url=f"{self.base}/{self.username}/{self.password}/{sid}.ts",
                group=cats.get(str(s.get("category_id")), ""),
                logo=s.get("stream_icon") or "",
                tvg_id=s.get("epg_channel_id") or "",
                source="xtream",
                attrs={"xtream_id": sid},
            ))
        return out


@register("xtream")
def load(spec: str, **_):
    """xtream://user:pass@host:8080"""
    u = urllib.parse.urlparse(spec)
    scheme = "https" if u.scheme == "xtreams" else "http"
    base = f"{scheme}://{u.hostname}" + (f":{u.port}" if u.port else "")
    client = Xtream(base, urllib.parse.unquote(u.username or ""),
                    urllib.parse.unquote(u.password or ""))
    return client.live_streams()
