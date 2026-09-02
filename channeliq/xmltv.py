"""XMLTV output for a curated lineup.

The other half of Export M3U. A playlist gives a player the streams; without
a guide it shows a wall of channel names and nothing else, and every
consumer-side IPTV app expects the two to arrive together. channeliq already
knows which guide each channel was matched to -- including a per-channel
override made in Curate -- so it can emit a guide containing exactly the
curated channels and nothing else, keyed by the same tvg-id the M3U writes.

Deliberately re-emits rather than proxies: the file is a snapshot, self
contained, and carries no provider credentials, so it can be handed to a
player or dropped on a share like the M3U next to it.
"""
import datetime
import xml.sax.saxutils as sax


def _esc(s):
    return sax.escape(str(s or ""))


def _fmt(dt):
    """XMLTV wants 20260822183000 +0000."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def build(channels, resolve):
    """XMLTV text for `channels`.

    channels: [{"id", "name", "logo"}] -- id is the tvg-id the M3U used, so
              the two files line up in a player with no further mapping.
    resolve:  callable(channel) -> (guide, guide_channel_id) or (None, None).
              Kept as a callback so this module needs to know nothing about
              EPG sources, per-channel overrides or caching.
    """
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<tv generator-info-name="channeliq">']
    matched, programmes = 0, 0
    for ch in channels:
        out.append(f'  <channel id="{_esc(ch["id"])}">')
        out.append(f'    <display-name>{_esc(ch["name"])}</display-name>')
        if ch.get("logo"):
            out.append(f'    <icon src="{_esc(ch["logo"])}" />')
        out.append("  </channel>")
    for ch in channels:
        guide, cid = resolve(ch)
        if not guide or not cid:
            continue
        matched += 1
        for start, stop, title, desc in guide.programmes.get(cid, ()):
            programmes += 1
            out.append(f'  <programme start="{_fmt(start)}" '
                       f'stop="{_fmt(stop)}" channel="{_esc(ch["id"])}">')
            out.append(f'    <title>{_esc(title)}</title>')
            if desc:
                out.append(f'    <desc>{_esc(desc)}</desc>')
            out.append("  </programme>")
    out.append("</tv>")
    return "\n".join(out) + "\n", {"channels": len(channels),
                                   "matched": matched,
                                   "programmes": programmes}
