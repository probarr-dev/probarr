"""Minimal web front end.

This is the seed of the *arr-style UI, not the finished article. Right now it
does the one thing that is awkward without it: browse and open contact sheets
from any device on the network, rather than copying HTML files around.

Deliberately stdlib http.server -- no framework, nothing to install, and the
container needs no extra layer to run it.
"""
import dataclasses
import datetime
import hashlib
import html
import json
import time
import os
import posixpath
import subprocess
import tarfile
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import backup as backup_mod
from . import curate, decisions, pages, probequeue, providers as providers_mod
from . import epgcheck as epgcheck_mod
from . import logos as logos_mod
from . import aliases as aliases_mod
from . import lineups as lineups_mod
from . import epgsources as epgsources_mod
from . import rank as rank_mod
from . import runs as runs_mod
from . import settings as settings_mod
from . import wantlist as wl
from .contactsheet import render as render_sheet
from . import xmltv as xmltv_mod
from . import dispatcharr_export
from .sources import m3u, load_source
from .sources.base import Stream
from .sources import dispatcharr as dispatcharr_mod
from .sources.dispatcharr import client_from_spec, base_url_of
from .store import RunStore, InvalidRunId
from .normalize import Normalizer, group_candidates, declared_quality_rank
from .probe import ProbeOptions, probe
from .theme import CSS, topbar
from .verify import annotate_placeholders


def _reprobeable_url(record):
    """The URL to re-probe with, or None if none is safely usable.

    `url` is the raw address and is always right when present. It is missing
    on runs created before probarr started storing it (added alongside M3U
    export, in the same session as re-probing itself) -- those older runs
    only have `url_redacted`.

    Falling back to the redacted copy is safe exactly when redaction was a
    no-op: sources with no embedded credentials (most free-to-air playlists,
    Dispatcharr's own stream URLs) come out of redacted_url() byte-identical
    to the original, so re-probing them works with no loss. It is UNSAFE when
    the source really did carry credentials, because those are now literally
    replaced with "***" and probing that URL would hit the wrong address
    entirely -- silently producing a "dead" result that looks like a real
    finding rather than what it actually is, a stale run needing a re-verify.
    """
    url = record.get("url")
    if url:
        return url
    redacted = record.get("url_redacted") or ""
    return redacted if redacted and "***" not in redacted else None


INDEX = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr</title><style>__CSS__
.runs{max-width:900px;margin:20px auto;padding:0 16px}
.run{display:flex;gap:14px;align-items:center;background:var(--panel);
  border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px;margin-bottom:8px}
.run b{font-size:15px}.run .m{color:var(--dim);font-size:12px}
.run a{text-decoration:none}
.run button.danger{background:var(--panel2);border-color:var(--bad);color:var(--bad)}
.run button.danger:hover{background:var(--bad);color:#3a0000}
</style></head><body>
__TOPBAR__
<div class="runs">__ROWS__</div>
<script>
document.addEventListener("click", async e => {
  const cbtn = e.target.closest("[data-clear-images]");
  if (cbtn) {
    const id = cbtn.dataset.clearImages;
    if (!confirm("Clear every captured image for \"" + id + "\"?\n\n" +
                 "Probe results and curated picks are kept \u2014 only the " +
                 "pictures go, and candidates show \u201cno frame\u201d " +
                 "until next probed.")) return;
    cbtn.disabled = true; cbtn.textContent = "Clearing\u2026";
    const r = await fetch("/api/run/" + encodeURIComponent(id) + "/clear-images",
                          {method: "POST"});
    const d = await r.json();
    cbtn.disabled = false;
    cbtn.textContent = d.ok ? "Cleared (" + d.removed + ")" : "Clear images";
    if (!d.ok) alert(d.error || "Could not clear images for this run.");
    return;
  }
  const btn = e.target.closest("[data-del-run]");
  if (!btn) return;
  const id = btn.dataset.delRun;
  if (!confirm("Delete run \"" + id + "\"? This removes every captured " +
               "frame and probe result for it. This cannot be undone.")) return;
  btn.disabled = true; btn.textContent = "Deleting…";
  const r = await fetch("/api/run/" + encodeURIComponent(id) + "/delete",
                        {method: "POST"});
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert(d.error || "Could not delete this run."); btn.disabled = false; btn.textContent = "Delete"; }
});
</script>
</body></html>"""


# How many candidates an UNCURATED channel exports automatically, best
# ranked first. Deliberately not 1 -- a single guess exporting with nothing
# behind it meant the first failure was a dead channel until someone
# noticed and opened it by hand.
AUTO_FALLBACK_DEPTH = 4


class Handler(BaseHTTPRequestHandler):
    root = "/config"
    server_version = "probarr"
    # Default is HTTP/1.0, whose cache semantics predate Cache-Control and are
    # interpreted inconsistently. Every response here sets Content-Length, so
    # 1.1 is safe and gets keep-alive as a bonus.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass  # quiet; the CLI does its own logging

    def _send(self, body, ctype="text/html; charset=utf-8", code=200,
              cache=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Pages are generated per request from the run data, which changes as
        # probes land. Serving a cached page would show a stale lineup.
        cache = cache or "no-store, must-revalidate"
        self.send_header("Cache-Control", cache)
        if "no-store" in cache:
            # Belt and braces for caches that predate Cache-Control. Cheap, and
            # this content genuinely must never be reused.
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            return self._do_GET()
        except InvalidRunId as e:
            # A malformed run id is a bad request, not a server fault --
            # and letting it escape here dropped the connection outright,
            # which is a worse failure than the unbounded directory
            # creation the validation was added to stop.
            #
            # Deliberately NOT `except ValueError`: json.JSONDecodeError is
            # a ValueError, so that caught a truncated run.json (read_meta
            # parses it with no guard) and answered 400 "Expecting value:
            # line 1 column 1" -- telling the operator their request was
            # malformed when in fact their stored data is corrupt.
            return self._send(json.dumps({"error": str(e)[:200]}),
                              "application/json", 400)

    def _do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            # The runs list used to live here; it moved to /runs (still on
            # the Runs nav tab) so "/" itself can go straight to the thing
            # actually being worked on -- Curate for whichever run is most
            # recent. RunStore.latest() is the same "newest first" ordering
            # already used everywhere else a run needs picking without the
            # user naming one; new runs sort first because they're named
            # from a timestamp, same convention as the old list here.
            latest = RunStore.latest(self.root)
            if latest:
                return self._redirect(
                    f"/run/{urllib.parse.quote(latest.run_id)}/curate")
            return self._redirect("/runs")
        if path == "/runs":
            return self._index()
        if path == "/settings":
            return self._send(pages.settings_page())
        if path == "/api/settings":
            # source/epg may hold live provider credentials (e.g.
            # xtream://user:pass@host:port); redact before this leaves the
            # process, same reasoning as /api/providers below.
            return self._send(json.dumps(settings_mod.redact(settings_mod.read(self.root))),
                              "application/json")
        if path == "/lineups":
            return self._send(pages.lineups_page())
        if path == "/api/lineups":
            return self._send(json.dumps({"lineups": self._lineups()}),
                              "application/json")
        if path == "/api/decisions":
            return self._send(json.dumps(decisions.analyse(self.root)),
                              "application/json")
        if path == "/api/backup/export":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            include_images = qs.get("images", ["0"])[0] == "1"
            body = backup_mod.export_tar(self.root, include_images=include_images)
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{backup_mod.export_filename()}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/queue":
            return self._send(json.dumps(self._queue().snapshot()),
                              "application/json")
        if path == "/wantlists":
            return self._send(pages.wantlist_page())
        if path == "/wantlists/template.txt":
            return self._send(wl.TEMPLATE, "text/plain; charset=utf-8")
        if path == "/api/epg-list":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            src = qs.get("source", [""])[0]
            try:
                channels = epgcheck_mod.list_channels(self.root, src, self._norm())
            except Exception as e:
                return self._send(json.dumps({"error": str(e)[:200]}), "application/json", 404)
            return self._send(json.dumps({"channels": channels}), "application/json")
        if path == "/api/wantlists/reference-lineups":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            force = qs.get("refresh", ["0"])[0] == "1"
            try:
                items = wl.known_reference_lineups(self.root, force=force)
            except Exception as e:
                return self._send(json.dumps({"error": str(e)[:200]}), "application/json", 502)
            return self._send(json.dumps({"lineups": items}), "application/json")
        if path == "/api/wantlists/starters":
            return self._send(json.dumps({"starters": wl.list_starters()}),
                              "application/json")
        if path.startswith("/wantlists/starter/") and path.endswith(".txt"):
            name = path[len("/wantlists/starter/"):-len(".txt")]
            text = wl.get_starter(name)
            if text is None:
                return self._send("<h1>404</h1>", code=404)
            return self._send(text, "text/plain; charset=utf-8")
        if path == "/providers":
            return self._send(pages.providers_page())
        if path == "/api/providers":
            # The spec carries the subscription credentials and, for a
            # Dispatcharr target, its admin password. It is never sent to a
            # client: the UI displays the redacted form, and every operation
            # that needs the real address resolves it server-side from the
            # provider NAME. Handing it out here made the careful "***" in
            # the interface decorative -- anything on the network could read
            # the real thing straight out of the API.
            items = [{k: v for k, v in p.items() if k != "spec"}
                     for p in providers_mod.list_all(self.root)]
            for p, raw in zip(items, providers_mod.list_all(self.root)):
                p["redacted"] = providers_mod.redact(raw["spec"])
            return self._send(json.dumps({"providers": items}), "application/json")
        if path == "/api/epg-sources":
            return self._send(json.dumps({"epg_sources": epgsources_mod.list_all(self.root)}),
                              "application/json")
        if path == "/api/aliases":
            return self._send(json.dumps({"aliases": aliases_mod.list_all(self.root)}),
                              "application/json")
        if path == "/new":
            return self._send(pages.new_run_page())
        if path == "/browse":
            return self._send(pages.browse_page())
        parts = [p for p in path.split("/") if p]
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "export" and parts[4] == "dispatcharr" \
                and parts[5] == "status":
            return self._export_dispatcharr_status(parts[2])
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "progress":
            st = runs_mod.status(parts[2])
            if st is None:
                # No live job for this id -- either it finished in a previous
                # process lifetime, or the id is unknown. Fall back to the
                # on-disk record so the New Run page doesn't spin forever
                # after a container restart mid-run.
                store = RunStore(self.root, parts[2])
                meta = store.read_meta() if os.path.exists(store.meta_path) else None
                if meta is None:
                    return self._send('{"error":"unknown run"}', "application/json", 404)
                state = meta.get("run_state", "done")
                st = {"run_id": parts[2], "state": state, "error": meta.get("error"),
                     "log": [], "progress": None}
            return self._send(json.dumps(st), "application/json")
        if parts[:2] == ["api", "wantlists"]:
            if len(parts) == 2:
                return self._send(json.dumps({"wantlists": wl.list_saved(self.root)}),
                                  "application/json")
            text = wl.read_saved(self.root, parts[2])
            if text is None:
                return self._send('{"error":"not found"}', "application/json", 404)
            return self._send(json.dumps({"name": parts[2], "text": text}),
                              "application/json")
        if len(parts) >= 2 and parts[0] == "run":
            run_id = parts[1]
            if len(parts) == 2 or parts[2] == "sheet":
                return self._sheet(run_id)
            if parts[2] == "curate":
                return self._curate(run_id)
            if parts[2] == "export.m3u":
                return self._export_m3u(run_id)
            if parts[2] == "export.xmltv":
                return self._export_xmltv(run_id)
            if parts[2] == "channel":
                return self._channel_json(run_id,
                                          urllib.parse.parse_qs(
                                              urllib.parse.urlparse(self.path).query
                                          ).get("key", [""])[0])
            if parts[2] == "groups":
                return self._known_groups(run_id)
            if parts[2] == "catalog":
                return self._catalog_search(run_id,
                    urllib.parse.parse_qs(
                        urllib.parse.urlparse(self.path).query).get("q", [""])[0])
            if parts[2] == "candidates":
                qs = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                return self._channel_candidates(run_id,
                                                qs.get("key", [""])[0],
                                                qs.get("q", [""])[0])
            if parts[2] == "epg-check":
                return self._epg_check(run_id,
                                       urllib.parse.parse_qs(
                                           urllib.parse.urlparse(self.path).query
                                       ).get("key", [""])[0])
            if parts[2] == "epg-search":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                return self._epg_search(run_id, qs.get("source", [""])[0],
                                        qs.get("q", [""])[0])
            if parts[2] == "logo-countries":
                return self._logo_countries(run_id)
            if parts[2] == "logo-search":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                return self._logo_search(run_id, qs.get("country", [""])[0],
                                         qs.get("q", [""])[0])
            if parts[2] == "file":
                return self._file(run_id, parts[3:])
            if parts[2] == "thumbs":
                return self._file(run_id, ["thumbs"] + parts[3:])
            if parts[2] == "watermark":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                return self._watermark_crop(run_id, qs.get("key", [""])[0])
            if parts[2] == "results.json":
                store = RunStore(self.root, run_id)
                return self._send(json.dumps(store.load()), "application/json")
        self._send("<h1>404</h1>", code=404)

    def _json_body(self, limit=4 * 1024 * 1024):
        """Read a bounded JSON body. Returns (obj, error_response_sent)."""
        length = int(self.headers.get("Content-Length") or 0)
        # Bound it: this API is unauthenticated on a LAN, and an unbounded read
        # is a trivial way to exhaust memory.
        if length > limit:
            self._send('{"error":"too large"}', "application/json", 413)
            return None, True
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send('{"error":"bad json"}', "application/json", 400)
            return None, True
        if not isinstance(body, dict):
            self._send('{"error":"expected object"}', "application/json", 400)
            return None, True
        return body, False

    def _raw_body(self, limit):
        """Read a bounded raw binary body. Returns (bytes, error_response_sent).

        For an uploaded backup archive rather than a JSON API call -- same
        bound-it-first reasoning as _json_body(), just without assuming the
        content is text.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            self._send('{"error":"too large"}', "application/json", 413)
            return None, True
        return self.rfile.read(length), False

    def do_POST(self):
        try:
            return self._do_POST()
        except InvalidRunId as e:
            return self._send(json.dumps({"error": str(e)[:200]}),
                              "application/json", 400)

    def _do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]

        if path == "/api/settings":
            body, sent = self._json_body()
            if sent:
                return
            # Redacted on the way OUT as well as in, or the save
            # round-trip hands the credential straight back -- into the
            # response body, into any proxy log on that leg, and into the
            # field on screen until the next reload. The GET was fixed
            # first (PR #1); this is the other half. The page's own save
            # handler reads this response back into the field and into its
            # as-loaded comparison value, so both directions agreeing is
            # what stops an untouched field being saved over the secret.
            return self._send(
                json.dumps(settings_mod.redact(settings_mod.write(self.root, body))),
                "application/json")

        if path == "/api/backup/import":
            # A restore rewrites providers, lineups, wantlists and every
            # run's own state in place -- deliberately no merge, the backup
            # IS the new truth, same reasoning as any other restore. 200MB
            # covers a very large run history with images left out, which
            # is the whole point of leaving them out by default.
            data, sent = self._raw_body(limit=200 * 1024 * 1024)
            if sent:
                return
            try:
                backup_mod.import_tar(self.root, data)
            except (ValueError, OSError, EOFError, tarfile.TarError) as e:
                return self._send(json.dumps({"error": str(e)[:300]}),
                                  "application/json", 400)
            return self._send('{"ok": true}', "application/json")

        if path == "/api/wantlists/enrich":
            # Fills in channel numbers and groups from an operator-supplied
            # reference lineup (e.g. a Lineuparr-format JSON on GitHub) --
            # data XMLTV EPGs simply don't carry. Nothing about the
            # reference itself is stored or bundled; it's fetched fresh
            # each time, same BYO-URL pattern as an EPG source.
            body, sent = self._json_body()
            if sent:
                return
            url = (body.get("url") or "").strip()
            text = body.get("text") or ""
            if not url:
                return self._send(json.dumps({"error": "reference URL required"}),
                                  "application/json", 400)
            data, err = self._fetch_reference_json(url)
            if err:
                return self._send(json.dumps({"error": err}), "application/json", 400)
            norm = self._norm()
            try:
                ref_map = wl.reference_lineup_map(data, norm)
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)[:300]}),
                                  "application/json", 400)
            channels, warnings = wl.parse_detailed(text, norm)
            channels, matched = wl.enrich_with_reference(channels, ref_map)
            channels = wl.group_together(channels)
            still_unmatched = [c.name for c in channels if c.number is None]
            return self._send(json.dumps({
                "text": wl.render(channels),
                "matched": matched,
                "total": len(channels),
                # parse_detailed silently drops a line whose name normalises
                # to a key already seen earlier in the file (see its own
                # duplicate-of-line-N warning) -- surfaced here rather than
                # left invisible, since a channel that vanished entirely
                # looks identical, from the editor, to one that simply had
                # no match in the reference lineup.
                "warnings": [w["problem"] for w in warnings][:50],
                "unmatched": still_unmatched[:80],
            }), "application/json")

        if path == "/api/wantlists/from-reference":
            # Builds a wantlist directly from a reference lineup's own
            # name/number/group data, instead of matching it against
            # names an EPG happens to use -- see channels_from_reference()
            # for why that EPG-name matching step is often the weak link,
            # not the reference data itself.
            body, sent = self._json_body()
            if sent:
                return
            url = (body.get("url") or "").strip()
            if not url:
                return self._send(json.dumps({"error": "reference URL required"}),
                                  "application/json", 400)
            data, err = self._fetch_reference_json(url)
            if err:
                return self._send(json.dumps({"error": err}), "application/json", 400)
            norm = self._norm()
            try:
                channels = wl.channels_from_reference(data, norm)
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)[:300]}),
                                  "application/json", 400)
            channels = wl.group_together(channels)
            return self._send(json.dumps({
                "text": wl.render(channels),
                "count": len(channels),
            }), "application/json")

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "reprobe":
            return self._reprobe(parts[2])

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "stop":
            ok = runs_mod.request_stop(parts[2])
            return self._send(json.dumps({"ok": ok}), "application/json")

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "delete":
            live = runs_mod.status(parts[2])
            if live and live.get("state") in ("starting", "running"):
                # Deleting the directory out from under an active probe would
                # not stop it -- the background thread keeps running and its
                # next store.append() would recreate the directory mid-delete,
                # leaving an orphaned partial run behind. Ask it to stop first.
                return self._send(
                    '{"ok":false,"error":"run is still in progress -- stop it first"}',
                    "application/json", 409)
            ok = RunStore.delete(self.root, parts[2])
            return self._send(json.dumps({"ok": ok}), "application/json",
                              200 if ok else 404)

        if parts[:3] == ["api", "providers", "test"]:
            body, sent = self._json_body()
            if sent:
                return
            return self._test_provider(body.get("spec") or "")

        if path == "/api/browse":
            body, sent = self._json_body()
            if sent:
                return
            return self._browse(body)

        if parts[:2] == ["api", "providers"] and len(parts) >= 3:
            if len(parts) == 4 and parts[3] == "delete":
                ok = providers_mod.delete(self.root, parts[2])
                return self._send(json.dumps({"ok": ok}), "application/json")
            body, sent = self._json_body()
            if sent:
                return
            try:
                name = providers_mod.save(self.root, parts[2], body.get("spec") or "",
                                          concurrency=body.get("concurrency"))
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json", 400)
            return self._send(json.dumps({"ok": True, "name": name}),
                              "application/json")

        if path == "/api/epg-sources/reorder":
            body, sent = self._json_body()
            if sent:
                return
            epgsources_mod.reorder(self.root, body.get("names") or [])
            return self._send(json.dumps({"ok": True}), "application/json")

        if parts[:2] == ["api", "epg-sources"] and len(parts) >= 3:
            if len(parts) == 4 and parts[3] == "delete":
                ok = epgsources_mod.delete(self.root, parts[2])
                return self._send(json.dumps({"ok": ok}), "application/json")
            body, sent = self._json_body()
            if sent:
                return
            url = body.get("url") or ""
            # Verified before it's ever saved -- the Sky-Sheffield incident
            # was a GitHub "blob" HTML page instead of the raw XML, and
            # nothing caught it until a real run tried to use it and quietly
            # continued without expected-programme data. Same class of
            # mistake as pointing at the wrong export URL for any other EPG
            # host; catching it here means every FUTURE run is protected,
            # not just the one that happened to be watched closely enough
            # to notice the warning in its log.
            if url:
                try:
                    epgcheck_mod.load_cached(url, root=self.root)
                except Exception as e:
                    return self._send(json.dumps(
                        {"error": f"could not load this as an XMLTV guide: {e}"[:300]}),
                        "application/json", 400)
            try:
                name = epgsources_mod.save(self.root, parts[2], url)
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json", 400)
            return self._send(json.dumps({"ok": True, "name": name}),
                              "application/json")

        if path == "/api/aliases":
            body, sent = self._json_body()
            if sent:
                return
            try:
                if body.get("delete"):
                    ok = aliases_mod.delete(self.root, body.get("name") or "")
                    return self._send(json.dumps({"ok": ok}), "application/json")
                row = aliases_mod.save(self.root, body.get("name") or "",
                                       body.get("canonical") or "")
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json", 400)
            return self._send(json.dumps({"ok": True, **row}), "application/json")

        if path == "/api/lineups":
            body, sent = self._json_body()
            if sent:
                return
            try:
                lu = lineups_mod.save(self.root, body.pop("name", ""), **body)
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)}), "application/json", 400)
            return self._send(json.dumps(lu), "application/json")

        if len(parts) == 3 and parts[:2] == ["api", "lineups"] and parts[2]:
            body, sent = self._json_body()
            if sent:
                return
            if body.get("delete"):
                ok = lineups_mod.delete(self.root, parts[2])
                return self._send(json.dumps({"ok": ok}), "application/json")
            if body.get("clear_preference"):
                # Forgetting one channel's remembered decisions, without
                # deleting the lineup. set_preference drops a field when it
                # is given None, and drops the channel entirely once nothing
                # is left, so clearing every known field is the whole job.
                lu = lineups_mod.get(self.root, parts[2]) or {}
                key = body["clear_preference"]
                fields = (lu.get("preferences", {}).get(key) or {}).keys()
                lineups_mod.set_preference(self.root, parts[2], key,
                                           **{f: None for f in fields})
                return self._send(json.dumps({"ok": True}), "application/json")
            lu = lineups_mod.save(self.root, parts[2], **body)
            return self._send(json.dumps(lu), "application/json")

        if path == "/api/runs/start":
            body, sent = self._json_body()
            if sent:
                return
            return self._start_run(body)

        if len(parts) == 6 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "export" and parts[4] == "dispatcharr" \
                and parts[5] == "plan":
            body, sent = self._json_body()
            if sent:
                return
            return self._export_plan(parts[2], body)

        if len(parts) == 5 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "export" and parts[4] == "dispatcharr":
            body, sent = self._json_body()
            if sent:
                return
            return self._export_dispatcharr(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "channel-rename":
            body, sent = self._json_body()
            if sent:
                return
            return self._rename_channel(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "channel-duplicate":
            body, sent = self._json_body()
            if sent:
                return
            return self._duplicate_channel(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "channel-remove":
            body, sent = self._json_body()
            if sent:
                return
            return self._remove_channel(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "catalog-add":
            body, sent = self._json_body()
            if sent:
                return
            return self._catalog_add(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "clear-images":
            store = RunStore(self.root, parts[2])
            if not os.path.exists(store.results_path):
                return self._send('{"error":"no such run"}',
                                  "application/json", 404)
            n = store.clear_images()
            return self._send(json.dumps({"ok": True, "removed": n}),
                              "application/json")

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "candidate-remove":
            body, sent = self._json_body()
            if sent:
                return
            rec_key = (body.get("rec_key") or "").strip()
            if not rec_key:
                return self._send('{"error":"rec_key required"}',
                                  "application/json", 400)
            store = RunStore(self.root, parts[2])
            if not os.path.exists(store.results_path):
                return self._send('{"error":"no such run"}',
                                  "application/json", 404)
            # Recorded BEFORE the delete -- drop_stream removes the only
            # record of what channel_key/stream_id/name this rec_key was.
            record = next((r for r in store.load() if r.get("rec_key") == rec_key), None)
            removed = store.drop_stream(rec_key)
            if removed and record and record.get("channel_key") and record.get("stream_id"):
                store.add_excluded(record["channel_key"], record["stream_id"],
                                   record.get("stream_name") or "", body.get("reason") or "")
            return self._send(json.dumps({"ok": True, "removed": removed}),
                              "application/json")

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "probe-via-dispatcharr":
            body, sent = self._json_body()
            if sent:
                return
            return self._probe_via_dispatcharr(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "groups":
            body, sent = self._json_body()
            if sent:
                return
            return self._run_groups(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "reorder-group":
            body, sent = self._json_body()
            if sent:
                return
            return self._reorder_group(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "swap-numbers":
            body, sent = self._json_body()
            if sent:
                return
            return self._swap_numbers(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "candidate-add":
            body, sent = self._json_body()
            if sent:
                return
            return self._candidate_add(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "dispatcharr-import":
            body, sent = self._json_body()
            if sent:
                return
            return self._dispatcharr_import(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "diagnose":
            body, sent = self._json_body()
            if sent:
                return
            return self._diagnose_channel(parts[2], body)

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "diagnose-batch":
            body, sent = self._json_body(limit=512 * 1024)
            if sent:
                return
            return self._diagnose_batch(parts[2], body)

        if parts[:3] == ["api", "wantlists", "preview"]:
            body, sent = self._json_body()
            if sent:
                return
            norm = self._norm()
            channels, warnings = wl.parse_detailed(body.get("text") or "", norm)
            return self._send(json.dumps({
                "channels": [c.as_dict() for c in channels],
                "warnings": warnings}), "application/json")

        if parts[:2] == ["api", "wantlists"] and len(parts) >= 3:
            if len(parts) == 4 and parts[3] == "delete":
                ok = wl.delete_saved(self.root, parts[2])
                return self._send(json.dumps({"ok": ok}), "application/json")
            body, sent = self._json_body()
            if sent:
                return
            try:
                name = wl.write_saved(self.root, parts[2], body.get("text") or "")
            except ValueError as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json", 400)
            return self._send(json.dumps({"ok": True, "name": name}),
                              "application/json")

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "run" \
                and parts[3] == "selection":
            body, sent = self._json_body()
            if sent:
                return
            store = RunStore(self.root, parts[2])
            if not os.path.exists(store.results_path):
                return self._send('{"error":"no such run"}', "application/json", 404)
            self._log_overrides(store, body)
            self._persist_lineup_prefs(store, body)
            store.write_selection(body)
            return self._send('{"ok":true}', "application/json")
        self._send('{"error":"not found"}', "application/json", 404)

    def _persist_lineup_prefs(self, store, new_selection):
        """Promote the durable subset of a selection to the run's lineup.

        Only decisions that are genuinely about the CHANNEL rather than
        about this run's particular candidates are promoted -- an EPG
        source is a lasting property of a channel, whereas a chosen stream
        id is meaningful only within the run that probed it and would be
        actively wrong to inherit. Silently ignored when the run has no
        lineup, which keeps lineups opt-in.
        """
        lineup = store.read_meta().get("lineup")
        if not lineup:
            return
        try:
            for key, pick in (new_selection or {}).items():
                pick = pick or {}
                durable = {k: pick.get(k) for k in
                          ("epg_source", "group", "confirmed", "settled_on",
                           "watermark_box", "logo_override")
                          if pick.get(k)}
                if durable:
                    lineups_mod.set_preference(self.root, lineup, key, **durable)
        except Exception:
            pass  # never let a preference write break the actual save

    def _log_overrides(self, store, new_selection):
        """Diff the incoming selection against what was there before, and
        record any channel where the curator's primary pick now disagrees
        with the algorithm's own #1-ranked candidate.

        Compares against the previously *saved* selection, not against
        "no selection at all" -- the curate view autosaves the whole map on
        every change (debounced), so without this the same unchanged picks
        would get re-logged as "overrides" on every keystroke elsewhere on
        the page.
        """
        try:
            old_selection = store.read_selection()
            by_channel = annotate_placeholders(store)
            payload = curate.build_payload(by_channel, store,
                                           bool(store.read_meta().get("epg")))
            channels_by_key = {c["key"]: c for c in payload["channels"]}
            for key, new_pick in (new_selection or {}).items():
                new_primary = (new_pick or {}).get("primary")
                if not new_primary:
                    continue
                old_primary = (old_selection.get(key) or {}).get("primary")
                if new_primary == old_primary:
                    continue
                ch = channels_by_key.get(key)
                if not ch or not ch.get("candidates"):
                    continue
                algo_pick = ch["candidates"][0]
                curator_pick = next((c for c in ch["candidates"]
                                     if c["id"] == new_primary), None)
                if not curator_pick or curator_pick["id"] == algo_pick["id"]:
                    continue
                decisions.log_override(self.root, store.run_id, key,
                                       ch.get("title") or key, algo_pick,
                                       curator_pick)
        except Exception:
            # Never let the tuning log break the actual save.
            pass

    def _channel_json(self, run_id, channel_key):
        """One channel's freshly-rebuilt payload.

        Lets the curation view refresh a single card after a re-probe instead
        of reloading the whole page. A reload had to survive sessionStorage
        (which throws in Safari's private browsing), the browser's page cache,
        and scroll restoration; swapping one card in place avoids all of it.
        """
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        by_channel = annotate_placeholders(store)
        payload = curate.build_payload(by_channel, store,
                                       bool(store.read_meta().get("epg")),
                                       self._inherited(store), self._dropped_urls(store),
                                       self._epg_mismatches(store))
        ch = next((c for c in payload["channels"] if c["key"] == channel_key), None)
        if ch is None:
            return self._send('{"error":"no such channel"}', "application/json", 404)
        self._send(json.dumps(ch), "application/json")

    # A provider catalogue is large (55k+ entries is normal) and parsing it
    # costs seconds, so it is cached per source spec for the life of the
    # process. Searching it is an interactive action -- re-downloading the
    # whole playlist on every keystroke-driven query would make the feature
    # unusable for exactly the browsing it exists to support.
    _catalog_cache = {}

    def _norm(self):
        """A Normalizer that knows the saved aliases.

        Every construction in the request path goes through here, because an
        alias that applied to matching but not to searching (or to the run
        but not to the catalogue) would be worse than none at all -- the two
        halves of the tool would disagree about what a channel is called.
        """
        return Normalizer(aliases=aliases_mod.read(self.root))

    def _fetch_reference_json(self, url):
        """GET a reference-lineup URL and parse it as JSON. Returns (data, error)."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "probarr/0.1"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            return json.loads(raw), None
        except Exception as e:
            return None, f"could not fetch/parse reference: {e}"[:300]

    # A full provider catalogue (55k+ entries is normal) costs real seconds
    # to download and parse, and every deploy recreates this container --
    # which used to throw the in-memory cache away and pay that cost again
    # on the very next click. The RAW stream list is now also cached to
    # disk, so a restart re-reads a local file instead of re-fetching the
    # provider; only the derived, alias-dependent grouping stays memory-only.
    CATALOG_DISK_TTL = 1800

    def _catalog_disk_path(self, spec):
        d = os.path.join(self.root, "catalog_cache")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, hashlib.sha256(spec.encode()).hexdigest()[:16] + ".json")

    def _load_source_cached(self, spec):
        """The provider's whole catalogue, reusing a recent copy from disk.

        JSON, not pickle. This used to pickle.dump/pickle.load the Stream
        list, which hands arbitrary code execution to anyone able to write
        into the config directory -- a real finding from a reviewer, and an
        unnecessary risk for what this actually stores: Stream is a plain
        dataclass of strings plus a dict, so JSON carries it losslessly.
        """
        path = self._catalog_disk_path(spec)
        if os.path.exists(path) and \
                (time.time() - os.path.getmtime(path)) < self.CATALOG_DISK_TTL:
            try:
                with open(path, encoding="utf-8") as f:
                    return [Stream(**row) for row in json.load(f)]
            except (OSError, ValueError, TypeError):
                pass   # a corrupt or older-format cache is just a miss
        streams = load_source(spec)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([dataclasses.asdict(s) for s in streams], f)
            os.replace(tmp, path)
        except (OSError, TypeError):
            # Disk caching is a courtesy; never break the real fetch. But
            # take the partial file with us -- the usual trigger is a full
            # disk, which is the worst moment to leave a 12MB orphan
            # behind on every subsequent load.
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return streams

    def _catalog_pools(self, store):
        """{channel_key: [Stream]} for the run's ENTIRE source, unfiltered by
        the wantlist -- which is the point: this is for finding channels you
        did not think to ask for."""
        meta = store.read_meta()
        spec = None
        if meta.get("provider_name"):
            prov = providers_mod.get(self.root, meta["provider_name"])
            spec = (prov or {}).get("spec")
        spec = spec or meta.get("source")
        if not spec:
            raise ValueError("this run has no resolvable source to search")
        # Keyed by the aliases as well as the source: an alias changes what
        # KEY a stream is filed under, so a pool cached before one was added
        # would keep answering with the old grouping until the process
        # restarted -- the alias would look like it had done nothing.
        ck = (spec, json.dumps(aliases_mod.read(self.root), sort_keys=True))
        hit = self._catalog_cache.get(ck)
        if hit is None:
            self._catalog_cache.clear()   # only ever one source in play
            norm = self._norm()
            hit = group_candidates(self._load_source_cached(spec), norm, regions=None)
            self._catalog_cache[ck] = hit
        return hit

    def _catalog_search(self, run_id, query):
        """Search the provider's whole catalogue for channels to add."""
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        q = (query or "").strip().lower()
        if len(q) < 2:
            return self._send('{"error":"type at least 2 characters"}',
                              "application/json", 400)
        try:
            pools = self._catalog_pools(store)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)
        already = {r.get("channel_key") for r in store.load()}
        hits = []
        for key, streams in pools.items():
            names = [st.name for st in streams]
            if q not in key.lower() and not any(q in n.lower() for n in names):
                continue
            hits.append({"key": key, "candidates": len(streams),
                        "example": names[0] if names else "",
                        "groups": sorted({(st.group or "") for st in streams})[:3],
                        "in_run": key in already})
        # Fewest candidates first is the wrong instinct here: a channel the
        # provider carries many variants of is usually the real one, and a
        # one-off is usually a stray. Most-carried first surfaces the
        # genuine channel before its oddities.
        hits.sort(key=lambda h: (h["in_run"], -h["candidates"], h["key"]))
        return self._send(json.dumps({"query": q, "total": len(hits),
                                     "hits": hits[:60]}), "application/json")

    def _channel_candidates(self, run_id, key, q):
        """Every stream the provider offers for ONE channel, probed or not.

        The run itself only ever probes the first `max_candidates` of a pool,
        ordered by declared quality -- a necessary cap when a whole lineup is
        being verified over one connection, but it means a genuinely better
        stream can sit in the catalogue unprobed and invisible. Worse, the
        matcher decides the pool: a variant the provider labels differently
        enough ("HEVC FHD Meridian Sports 1" with no country marker) never
        reaches the channel at all, and no amount of re-running finds it.

        So this answers both questions in one place, for one channel: here is
        the whole matched pool with what is already known about each entry,
        and here is a free search over the entire catalogue for anything the
        matcher did not connect to this channel. What gets probed is then a
        human decision rather than a guess by the ranker.
        """
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        if not key:
            return self._send('{"error":"channel_key required"}',
                              "application/json", 400)
        try:
            pools = self._catalog_pools(store)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)

        known = {}
        for r in store.load():
            if r.get("channel_key") == key:
                known[str(r.get("stream_id"))] = r
        excluded = store.read_excluded()

        # Which URLs this channel has genuinely failed over FROM, in real
        # use -- resolved from Dispatcharr's own event log (see
        # Dispatcharr.failed_streams()), so a candidate that already burned
        # someone in production can say so right here, not just as a
        # channel-level badge. A channel_failover event names only the
        # channel and the raw Dispatcharr stream id, so each id is resolved
        # to the URL it actually pointed at -- capped by how many distinct
        # streams have ever failed for one channel, normally one or two.
        dropped_urls = {}
        entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                     if w.get("key") == key), {})
        dch = entry.get("dispatcharr") or {}
        if dch.get("channel_name") and \
                settings_mod.read(self.root).get("failover_display", "info") != "off":
            try:
                prov = next((p for p in providers_mod.list_all(self.root)
                            if p.get("scheme") == "dispatcharr"), None)
                if prov:
                    client = client_from_spec(prov["spec"])
                    failed = self._cached_failed_streams(client, client.base)
                    for sid, n in failed.get(dch["channel_name"], {}).items():
                        url = self._cached_stream_url(client, sid)
                        if url:
                            dropped_urls[url] = n
            except Exception:
                pass

        def item(st, matched):
            r = known.get(str(st.id))
            return {"stream_id": st.id, "name": st.name,
                    "group": st.group or "", "matched": matched,
                    "probed": r is not None,
                    "status": (r or {}).get("status", ""),
                    "why": (r or {}).get("reason", ""),
                    "w": (r or {}).get("width", 0), "h": (r or {}).get("height", 0),
                    "fps": (r or {}).get("fps", 0),
                    "kbps": (r or {}).get("measured_kbps", 0),
                    "vcodec": (r or {}).get("video_codec", ""),
                    "dropped": dropped_urls.get(st.url),
                    "excluded": excluded.get(f"{key}|{st.id}"),
                    "rank_hint": declared_quality_rank(st.name)}

        # A run probed BEFORE an alias existed has channel keys in the old
        # spelling, while the pool is now filed under the canonical one.
        # Resolving through the alias here is what makes adding one take
        # effect on the run you are looking at, instead of only on the next.
        alias_key = aliases_mod.read(self.root).get(key, key)
        pool = sorted((pools.get(key) or pools.get(alias_key) or []),
                      key=lambda st: (-declared_quality_rank(st.name), st.name))
        out = [item(st, True) for st in pool]

        # The free search deliberately ignores the matcher entirely and looks
        # at raw names, because its whole purpose is to reach streams the
        # matcher did not connect to this channel.
        hits = []
        needle = (q or "").strip().lower()
        if len(needle) >= 2:
            norm = self._norm()
            # Ignoring the matcher means ignoring its region filter too, and
            # on a multi-country catalogue that buries the answer: a search
            # for "drama" returns 216 streams, and ranking them by declared
            # quality alone puts a Canadian feed above "UK: Drama". So the
            # run's own regions -- inferred from what it has already probed
            # when nothing is configured -- order the results without
            # removing anything, since the whole point is to be able to
            # reach past what the matcher decided.
            prefer = {r.upper() for r in (store.read_meta().get("regions") or [])}
            if not prefer:
                seen_regions = {}
                for rec in store.load():
                    reg = norm.region_of(rec.get("stream_name") or "")
                    if reg:
                        seen_regions[reg] = seen_regions.get(reg, 0) + 1
                if seen_regions:
                    prefer = {max(seen_regions, key=seen_regions.get)}
            seen = {str(st.id) for st in pool}
            for k, streams in pools.items():
                for st in streams:
                    if str(st.id) in seen or needle not in st.name.lower():
                        continue
                    seen.add(str(st.id))
                    reg = norm.region_of(st.name)
                    h = item(st, False)
                    # 0 = this run's region, 1 = no region marker at all,
                    # 2 = explicitly somewhere else.
                    h["region"] = reg or ""
                    h["_r"] = 0 if (reg and reg in prefer) else (1 if not reg else 2)
                    hits.append(h)
            hits.sort(key=lambda h: (h["_r"], -h["rank_hint"], h["name"]))
            for h in hits:
                h.pop("_r", None)
        # A channel imported from Dispatcharr carries its own uuid -- the
        # one place a "probe via Dispatcharr" makes unambiguous sense, since
        # Dispatcharr proxies by CHANNEL, not by candidate. Offered as a
        # distinct action rather than folded into the pool: it tests the
        # actual delivery pipe (Dispatcharr's own transcode/relay), not one
        # more provider variant.
        entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                     if w.get("key") == key), {})
        dch = entry.get("dispatcharr") or {}
        via_dispatcharr = None
        if dch.get("uuid"):
            via_dispatcharr = {"uuid": dch["uuid"], "stream": dch.get("stream", ""),
                              "viewers": dch.get("viewers"),
                              "last_seen": dch.get("last_seen")}
        return self._send(json.dumps({"key": key, "pool": out,
                                     "hits": hits[:60],
                                     "hits_total": len(hits),
                                     "via_dispatcharr": via_dispatcharr}),
                          "application/json")

    def _probe_via_dispatcharr(self, run_id, body):
        """Probe the exact stream Dispatcharr is serving for this channel,
        through Dispatcharr's own proxy rather than the raw provider URL.

        The one unambiguous case for going through Dispatcharr: it proxies
        by CHANNEL, so this only makes sense for the channel's current,
        already-assigned stream -- not an arbitrary candidate, which
        Dispatcharr has no way to be asked to deliver.
        """
        channel_key = (body.get("channel_key") or "").strip()
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                     if w.get("key") == channel_key), None)
        dch = (entry or {}).get("dispatcharr") or {}
        if not dch.get("uuid"):
            return self._send(
                '{"error":"this channel has no Dispatcharr channel attached '
                '\u2014 import it first"}', "application/json", 400)
        try:
            prov = next((p for p in providers_mod.list_all(self.root)
                        if p.get("scheme") == "dispatcharr"), None)
            if not prov:
                raise ValueError("no Dispatcharr connection saved")
            client = client_from_spec(prov["spec"])
            url = client.proxy_stream_url(dch["uuid"])
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)
        stream_id = f"dispatcharr-live:{dch['uuid']}"
        rk = f"{channel_key}|{stream_id}"
        outcome = self._queue().submit(
            f"{run_id}|{rk}",
            {"run_id": run_id, "rec_key": rk, "lane": self._lane_for_run(store),
             "seed": {"channel_key": channel_key, "stream_id": stream_id,
                     "name": "Via Dispatcharr: " + (dch.get("stream") or ""),
                     "url": url, "redacted": url, "group": dch.get("group", ""),
                     "logo": "", "tvg_id": ""}})
        self._send(json.dumps({"ok": True, "rec_key": rk, **outcome}),
                  "application/json")

    def _run_groups(self, run_id, body):
        """Add or remove an EMPTY-capable group on this run.

        Group membership normally comes only from channels' own SEL.group
        field, so a group with zero members has nowhere to live -- it
        vanishes the moment its last channel leaves, and there was no way
        to create one ahead of dragging channels into it. Extra, empty
        groups are recorded on the run itself; removing one clears the
        group field of any channel still in it, moving them to no group.
        """
        name = (body.get("name") or "").strip()
        if not name:
            return self._send('{"error":"a group name is required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        meta = store.read_meta()
        extra = list(meta.get("extra_groups") or [])
        if body.get("action") == "remove":
            extra = [g for g in extra if g != name]
            sel = store.read_selection()
            touched = False
            for pick in sel.values():
                if pick.get("group") == name:
                    pick.pop("group", None)
                    touched = True
            if touched:
                store.write_selection(sel)
        elif name not in extra:
            extra.append(name)
        store.write_meta({**meta, "extra_groups": extra})
        self._send(json.dumps({"ok": True, "extra_groups": extra}), "application/json")

    def _reorder_group(self, run_id, body):
        """Reorder the channels of ONE group by reassigning that group's OWN
        existing numbers to match the new order.

        Deliberately bounded: the group's number SET is invariant before
        and after -- nothing is invented, and nothing outside the group is
        touched. A hand-built genre-banded scheme (100s Entertainment, 300s
        Movies...) survives a reorder instead of being renumbered away.
        """
        keys = [k for k in (body.get("keys") or []) if k]
        if len(keys) < 2:
            return self._send('{"error":"at least two keys required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        want = store.read_wantlist()
        wanted = want.get("wanted") or []
        by_key = {w.get("key"): w for w in wanted}

        # A key can be visibly sitting in this run's own group list (it has
        # real probe results, Curate shows it, Groups lets you drag it) while
        # missing from the wantlist -- an older workflow, or a wantlist entry
        # that was removed while its results were kept. That is missing
        # bookkeeping, not a reason a channel can't be reordered like any
        # other one already here, so it is added rather than rejected.
        missing = [k for k in keys if k not in by_key]
        if missing:
            records_by_key = {}
            for r in store.load():
                if r.get("channel_key") in missing:
                    records_by_key.setdefault(r["channel_key"], []).append(r)
            all_numbers = {w.get("number") for w in wanted if w.get("number") is not None}
            # Numbered right after the OTHER channels already in this same
            # group/reorder request, not the whole wantlist's max -- so a
            # genre-banded group (the 400s) gains a new member numbered into
            # its own band (408) instead of being shunted into the high end
            # used for channels added with no band context at all. Falls
            # back to the wantlist max only when nothing in this request has
            # a number yet to anchor to.
            local_numbers = [by_key[k]["number"] for k in keys
                             if k in by_key and by_key[k].get("number") is not None]
            base = (max(local_numbers) if local_numbers
                   else max(all_numbers) if all_numbers else 8999)
            still_missing = []
            for k in missing:
                recs = records_by_key.get(k)
                if not recs:
                    still_missing.append(k)
                    continue
                candidate = base + 1
                while candidate in all_numbers:
                    candidate += 1
                ranked = rank_mod.rank(recs)
                entry = {"number": candidate, "key": k,
                        "name": (ranked[0].get("stream_name") if ranked else k) or k,
                        "tvg_id": (ranked[0].get("tvg_id") if ranked else "") or ""}
                wanted.append(entry)
                by_key[k] = entry
                all_numbers.add(candidate)
                base = candidate
            if still_missing:
                return self._send('{"error":"channel not in this run"}',
                                  "application/json", 404)

        rows = [by_key.get(k) for k in keys]
        if any(r is None for r in rows):
            return self._send('{"error":"channel not in this run"}',
                              "application/json", 404)
        numbers = sorted((r.get("number") for r in rows
                          if r.get("number") is not None))
        if len(numbers) != len(rows):
            return self._send(
                '{"error":"every channel in a group must already have a number"}',
                "application/json", 400)
        for row, num in zip(rows, numbers):
            row["number"] = num
        store.write_wantlist_raw(wanted, want.get("missing") or [])
        self._send(json.dumps({"ok": True,
                              "numbers": {r["key"]: r["number"] for r in rows}}),
                  "application/json")

    def _swap_numbers(self, run_id, body):
        """Swap the channel NUMBER of two channels in this run's wantlist.

        The only reordering primitive offered, deliberately narrow: a
        channel's real position is its number, and this owner built a
        genre-banded numbering scheme by hand (100s Entertainment, 300s
        Movies, 400s Sports...) that a cascading renumber-everything-below
        could silently scramble. Swapping exactly the two numbers dropped
        against each other reorders without ever touching a third channel.
        """
        a, b = (body.get("key_a") or "").strip(), (body.get("key_b") or "").strip()
        if not a or not b or a == b:
            return self._send('{"error":"key_a and key_b, and they must differ"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        want = store.read_wantlist()
        wanted = want.get("wanted") or []
        wa = next((w for w in wanted if w.get("key") == a), None)
        wb = next((w for w in wanted if w.get("key") == b), None)
        if not wa or not wb:
            return self._send('{"error":"channel not in this run"}',
                              "application/json", 404)
        wa["number"], wb["number"] = wb.get("number"), wa.get("number")
        store.write_wantlist_raw(wanted, want.get("missing") or [])
        self._send(json.dumps({"ok": True, "a": wa["number"], "b": wb["number"]}),
                  "application/json")

    def _candidate_add(self, run_id, body):
        """Probe specific streams against one channel, and nothing else.

        The narrowest unit of work in the tool: no run, no whole-channel
        re-verify, just the streams that were ticked. That matters most
        exactly where re-running is most expensive -- one connection, a
        lineup that is otherwise already verified, and one channel worth a
        second look.

        A stream picked out of the free search is attached to THIS channel
        regardless of what the matcher thought it was, which is the point:
        the probe record carries the channel key, so a variant the matcher
        missed becomes a first-class candidate with no rule change and no
        re-run of anything else.
        """
        channel_key = (body.get("channel_key") or "").strip()
        ids = [str(i) for i in (body.get("stream_ids") or []) if str(i)]
        if not channel_key or not ids:
            return self._send('{"error":"channel_key and stream_ids required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        if not any(w.get("key") == channel_key
                   for w in (store.read_wantlist().get("wanted") or [])):
            return self._send('{"error":"channel not in this run"}',
                              "application/json", 404)
        try:
            pools = self._catalog_pools(store)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)
        norm = self._norm()
        index = {}
        for streams in pools.values():
            for st in streams:
                index[str(st.id)] = st

        already = {(r.get("rec_key") or "") for r in store.load()}
        queued, skipped, unknown = [], 0, 0
        for sid in ids:
            st = index.get(sid)
            if st is None:
                unknown += 1
                continue
            rk = f"{channel_key}|{st.id}"
            if rk in already and not body.get("reprobe"):
                skipped += 1
                continue
            outcome = self._queue().submit(
                f"{run_id}|{rk}",
                {"run_id": run_id, "rec_key": rk, "lane": self._lane_for_run(store),
                 "seed": {"channel_key": channel_key, "stream_id": st.id,
                         "name": st.name, "url": st.url,
                         "redacted": st.redacted_url(), "group": st.group,
                         "logo": st.logo, "tvg_id": st.tvg_id}})
            queued.append({"rec_key": rk, "name": st.name,
                          # The key this stream WOULD have matched on its
                          # own. When it differs from the channel's, the
                          # curator has just asserted that two names mean
                          # the same channel -- which is exactly an alias,
                          # and the only moment we can offer to remember it
                          # with both halves already known.
                          "stream_key": norm.key(st.name), **outcome})
        self._send(json.dumps({"ok": True, "queued": len(queued),
                              "skipped": skipped, "unknown": unknown,
                              "streams": queued}), "application/json")

    def _catalog_add(self, run_id, body):
        """Add catalogue channels to an existing run and probe them.

        Appends to the run's wantlist so the additions are first-class (they
        get a channel number and sort into the lineup) rather than showing
        up as unnumbered strays, then queues their candidates through the
        same ProbeQueue the re-probe and diagnose actions use -- so provider
        connection limits are respected exactly as they are everywhere else.
        """
        keys = [k for k in (body.get("keys") or []) if k]
        if not keys:
            return self._send('{"error":"no channels given"}', "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        try:
            pools = self._catalog_pools(store)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)

        want = store.read_wantlist()
        wanted = want.get("wanted") or []
        have = {w["key"] for w in wanted}
        numbers = [w.get("number") for w in wanted if w.get("number") is not None]
        # Added channels are numbered above everything existing, so they can
        # never collide with a wantlist number and never silently displace a
        # curated channel by landing on its number.
        next_num = (max(numbers) + 1) if numbers else 9000
        cfg = settings_mod.read(self.root)
        max_per = cfg.get("max_candidates") or 6

        queued, added = [], []
        for key in keys:
            streams = pools.get(key) or []
            if not streams:
                continue
            if key not in have:
                # Adding a channel back cancels any deletion staged for it.
                # Otherwise the next push would delete in Dispatcharr the
                # very channel just re-added here -- a staged removal is a
                # statement about the end state, and re-adding contradicts it.
                store.clear_removal(key)
                wanted.append({"number": next_num, "name": streams[0].name,
                              "tvg_id": streams[0].tvg_id or "", "key": key})
                added.append({"key": key, "number": next_num})
                next_num += 1
                have.add(key)
            for st in sorted(streams, key=lambda x: declared_quality_rank(x.name),
                            reverse=True)[:max_per]:
                rk = f"{key}|{st.id}"
                outcome = self._queue().submit(
                    f"{run_id}|{rk}",
                    {"run_id": run_id, "rec_key": rk, "lane": self._lane_for_run(store),
                     "seed": {"channel_key": key, "stream_id": st.id,
                             "name": st.name, "url": st.url,
                             "redacted": st.redacted_url(), "group": st.group,
                             "logo": st.logo, "tvg_id": st.tvg_id}})
                queued.append({"rec_key": rk, **outcome})
        store.write_wantlist_raw(wanted, want.get("missing") or [])
        self._send(json.dumps({"ok": True, "added": added,
                              "queued": len(queued)}), "application/json")

    def _dispatcharr_source(self, store, body):
        """The Dispatcharr connection an import should read from.

        Explicit provider name first, then the run's own source if that
        source IS a Dispatcharr instance -- which is the common case for
        "look at what I've already got and improve it", where the run was
        started against Dispatcharr in the first place.
        """
        name = (body.get("provider") or "").strip()
        spec = None
        if name:
            prov = providers_mod.get(self.root, name)
            if not prov:
                raise ValueError(f"no saved provider named {name!r}")
            spec = prov["spec"]
        else:
            meta = store.read_meta()
            for cand in (meta.get("source"),
                         (providers_mod.get(self.root, meta.get("provider_name") or "")
                          or {}).get("spec")):
                if str(cand or "").startswith("dispatcharr"):
                    spec = cand
                    break
        if not spec:
            raise ValueError("choose a saved Dispatcharr connection to import from")
        if not str(spec).startswith("dispatcharr"):
            raise ValueError(f"{name or 'that provider'} is not a Dispatcharr connection")
        return dispatcharr_mod.client_from_spec(spec)

    def _dispatcharr_read(self, store, body):
        """What Dispatcharr currently has, matched against this run.

        probarr could only ever PUSH, so a channel added by hand in
        Dispatcharr was invisible here and the two drifted apart with
        nothing able to see it. Reading the far side back is what makes the
        relationship two-way: every existing channel is matched to this
        run by the same normalised key everything else uses, so an import
        can say which are already curated here, which are new, and -- the
        actual point -- how many alternative candidates the provider
        carries for each one.
        """
        client = self._dispatcharr_source(store, body)
        groups = client.group_names()
        pools = self._catalog_pools(store)
        norm = self._norm()
        alias = aliases_mod.read(self.root)
        in_run = set()
        for w in (store.read_wantlist().get("wanted") or []):
            if w.get("key"):
                in_run.add(w["key"])
                in_run.add(alias.get(w["key"], w["key"]))
        failed = {}
        if settings_mod.read(self.root).get("failover_display", "info") != "off":
            failed = self._cached_failed_streams(client, client.base)
        failovers = {name: sum(v.values()) for name, v in failed.items()}
        out = []
        for ch in client.channels():
            name = ch.get("effective_name") or ch.get("name") or ""
            key = norm.key(name)
            sid = (ch.get("streams") or [None])[0]
            current = None
            if sid is not None:
                try:
                    st = client.stream(sid)
                    # Already fetched to get name/url -- current_viewers and
                    # last_seen ride along for free. Real playback evidence
                    # (has anyone actually watched this, recently) rather
                    # than the 6-25s sample a probe ever sees.
                    current = {"id": sid, "name": st.get("name") or "",
                               "url": st.get("url") or "",
                               "viewers": st.get("current_viewers"),
                               "last_seen": st.get("last_seen"),
                               "stale": st.get("is_stale")}
                except Exception:
                    current = {"id": sid, "name": "", "url": ""}
            gid = ch.get("effective_channel_group_id") or ch.get("channel_group_id")
            num = ch.get("effective_channel_number") or ch.get("channel_number")
            out.append({
                "dispatcharr_id": ch.get("id"), "name": name, "key": key,
                # Dispatcharr numbers are floats; a whole number reads as one.
                "number": int(num) if num is not None and float(num).is_integer()
                          else num,
                "group": groups.get(gid, ""),
                "in_run": key in in_run,
                "candidates": len(pools.get(key) or []),
                "current": current, "uuid": ch.get("uuid"),
                "failovers_7d": failovers.get(name),
            })
        out.sort(key=lambda c: (c["number"] is None, c["number"] or 0))
        return out, pools

    def _dispatcharr_import(self, run_id, body):
        """Pull Dispatcharr's existing channels into this run.

        `plan` reports what would happen and changes nothing. The import
        itself keeps Dispatcharr's OWN number, name and group -- importing
        is not an opportunity to renumber somebody's lineup -- and marks
        each channel as imported so Curate can say where it came from.

        The provider's candidates for that channel are then queued through
        the same ProbeQueue everything else uses, which is the whole
        purpose: an imported channel arrives with its current stream shown
        alongside real, probed alternatives, rather than as a name with
        nothing to compare.

        A channel Dispatcharr has that the provider carries no candidate
        for is still imported, deliberately -- it lands in the list as
        unmatched, which is the honest answer and the actionable one.

        Nothing already verified in this run is probed again. On a provider
        that permits one connection at a time, re-probing 150 channels that
        were validated last week to import a group name costs hours and
        tells you nothing new, so a candidate with a result already on disk
        is left alone unless `reprobe` explicitly asks otherwise. That makes
        importing an existing lineup cheap: the only connections spent are
        on genuinely new channels and streams.
        """
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        try:
            found, pools = self._dispatcharr_read(store, body)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:300]}),
                              "application/json", 502)
        cfg = settings_mod.read(self.root)
        max_per = cfg.get("max_candidates") or 6

        # Every candidate this run already has a probe result for. Checked
        # against rec_key, the same identity the queue and the results file
        # use, so "already verified" means exactly what it does everywhere
        # else in probarr -- and additionally against the URL, because
        # Dispatcharr's copy of a provider stream carries a different id
        # while being the very same address to probe.
        already_probed, probed_urls = set(), set()
        if not body.get("reprobe"):
            for r in store.load():
                already_probed.add(r.get("rec_key") or
                                   f"{r.get('channel_key')}|{r.get('stream_id')}")
                if r.get("url"):
                    probed_urls.add(r["url"])

        def seeds_for(ch):
            """The probes importing this channel would actually cost.

            `probe: false` makes an import a pure record of what Dispatcharr
            currently has -- its number, group and live stream, attached to
            the run -- with no probing at all. That is the right shape when
            the run is already verified and the question is "what has
            drifted", rather than "what could be better": the alternatives
            can be probed later, per channel, from the card itself.
            """
            if body.get("probe") is False:
                return [], 0
            key = ch["key"]
            picks = sorted(pools.get(key) or [],
                           key=lambda x: declared_quality_rank(x.name),
                           reverse=True)[:max_per]
            todo = [{"channel_key": key, "stream_id": st.id, "name": st.name,
                     "url": st.url, "redacted": st.redacted_url(),
                     "group": st.group, "logo": st.logo, "tvg_id": st.tvg_id}
                    for st in picks]
            # Dispatcharr's own current stream is probed too, even when the
            # provider pool already covers this channel: it is the one
            # candidate every alternative is implicitly compared against, so
            # leaving it unmeasured would make the comparison guesswork.
            cur = ch["current"] or {}
            urls = {st.url for st in picks}
            if cur.get("url") and cur["url"] not in urls \
                    and cur["url"] not in probed_urls:
                todo.append({"channel_key": key,
                            "stream_id": f"dispatcharr:{cur['id']}",
                            "name": cur.get("name") or ch["name"],
                            "url": cur["url"], "redacted": cur["url"],
                            "group": ch["group"], "logo": "", "tvg_id": ""})
            fresh = [t for t in todo
                     if f"{key}|{t['stream_id']}" not in already_probed]
            return fresh, len(todo) - len(fresh)

        if body.get("plan"):
            # The plan states the real cost up front, per channel and in
            # total. On a one-connection provider that is the number that
            # decides whether an import is a click or an overnight job, and
            # guessing it from the candidate count would overstate it wildly
            # for a lineup that is already verified.
            plan, cost = [], 0
            for c in found:
                fresh, _ = seeds_for(c)
                cost += len(fresh)
                plan.append(dict(c, current=(c["current"] or {}).get("name") or "",
                                 probes=len(fresh)))
            return self._send(json.dumps({"ok": True, "channels": plan,
                                         "probes": cost}), "application/json")

        wanted_keys = {k for k in (body.get("keys") or []) if k}
        want = store.read_wantlist()
        wanted = list(want.get("wanted") or [])
        by_key = {w.get("key"): w for w in wanted}
        sel = store.read_selection()
        lineup = store.read_meta().get("lineup")
        imported, queued, skipped = [], 0, 0
        for ch in found:
            key = ch["key"]
            if not key or (wanted_keys and key not in wanted_keys):
                continue
            entry = by_key.get(key)
            if entry is None:
                # Same reasoning as the catalogue add: importing a channel
                # from Dispatcharr plainly contradicts a staged deletion of
                # it, so the deletion is dropped rather than left to fire.
                store.clear_removal(key)
                entry = {"number": ch["number"], "name": ch["name"],
                         "tvg_id": "", "key": key}
                wanted.append(entry)
                by_key[key] = entry
            # Where it already exists, Dispatcharr's number and name are NOT
            # imposed over a curated decision -- only recorded, so the two
            # can be compared rather than one silently overwriting the other.
            entry["imported_from"] = "dispatcharr"
            cur = ch["current"] or {}
            entry["dispatcharr"] = {"id": ch["dispatcharr_id"],
                                    "number": ch["number"],
                                    "group": ch["group"],
                                    "stream": cur.get("name") or "",
                                    # The Dispatcharr-side channel NAME, not
                                    # this run's key -- system-events is
                                    # keyed by that name, and this is what
                                    # lets Find streams look failures back up
                                    # later without re-fetching them.
                                    "channel_name": ch.get("name") or "",
                                    "uuid": ch.get("uuid"),
                                    "viewers": cur.get("viewers"),
                                    "last_seen": cur.get("last_seen"),
                                    "stale": cur.get("stale"),
                                    "failovers_7d": ch.get("failovers_7d")}
            if ch["group"]:
                pick = dict(sel.get(key) or {})
                pick.setdefault("group", ch["group"])
                sel[key] = pick
                if lineup:
                    try:
                        lineups_mod.set_preference(self.root, lineup, key,
                                                   group=ch["group"])
                    except Exception:
                        pass
            imported.append({"key": key, "name": ch["name"],
                            "candidates": ch["candidates"]})

            fresh, done_already = seeds_for(ch)
            skipped += done_already
            for seed in fresh:
                rk = f"{key}|{seed['stream_id']}"
                self._queue().submit(f"{run_id}|{rk}",
                                     {"run_id": run_id, "rec_key": rk,
                                      "lane": self._lane_for_run(store), "seed": seed})
                queued += 1

        store.write_wantlist_raw(wanted, want.get("missing") or [])
        store.write_selection(sel)
        self._send(json.dumps({"ok": True, "imported": imported,
                              "queued": queued, "skipped": skipped}),
                   "application/json")

    def _remove_channel(self, run_id, body):
        """Remove a channel from this run, and stage its Dispatcharr deletion.

        The counterpart to adding one from the catalogue. Removing it from
        the run alone leaves the Dispatcharr channel behind -- the exporter
        only ever creates and updates, by design (see dispatcharr_export's
        module docstring), so nothing would ever clean it up.

        Deleting it there is therefore offered, but it is STAGED, not done
        here. Everything else in the tool is curate locally, review the
        diff, then push; this button reaching out and destroying a live
        channel the moment it was clicked was the single action that broke
        that model, with no preview and no chance to change your mind. The
        removal is now recorded against the run, shown in the push preview
        alongside every other change, and applied when you push -- which is
        what "remove it from Dispatcharr" was always taken to mean.
        """
        channel_key = (body.get("channel_key") or "").strip()
        if not channel_key:
            return self._send('{"error":"channel_key required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)

        # Capture the number BEFORE dropping it -- that is how the
        # Dispatcharr channel is identified, and it is about to be deleted
        # from the wantlist.
        entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                     if w.get("key") == channel_key), {})
        number, name = entry.get("number"), entry.get("name") or channel_key

        removed = store.drop_channel(channel_key)

        # A per-channel decision for a channel that no longer exists would
        # silently reapply if it were ever re-added.
        lineup = store.read_meta().get("lineup")
        if lineup:
            try:
                lineups_mod.set_preference(self.root, lineup, channel_key,
                                           epg_source=None, group=None)
            except Exception:
                pass

        staged = False
        if body.get("also_dispatcharr"):
            if number is None:
                # Nothing to delete BY: the exporter addresses a Dispatcharr
                # channel by its number, so without one there is no way to
                # say which channel is meant. Reported rather than staged,
                # so the push does not silently do nothing later.
                pass
            else:
                store.add_removal(channel_key, number, name)
                staged = True

        self._send(json.dumps({"ok": True, "removed_results": removed,
                              "number": number, "staged": staged,
                              "pending": len(store.read_removals())}),
                  "application/json")

    def _rename_channel(self, run_id, body):
        """Rename a channel's display name within this run.

        Written to the run's wantlist, because the wantlist name is what
        everything downstream already reads: the Curate title, the M3U
        export, and the name pushed to Dispatcharr all resolve from it, so
        one edit reaches all three without any of them needing to learn
        about a new override field.

        ALSO promoted to the run's lineup, when it has one. A rename is a
        judgement about the channel, not about this run's candidates -- the
        same class of decision as the per-channel EPG source and group. Left
        in the wantlist alone it was silently lost the moment the lineup was
        re-run, because a fresh run rebuilds its wantlist from the provider
        and gets the provider's name back.

        Especially useful alongside Duplicate, where two copies of the same
        feed would otherwise be indistinguishable in the channel list.
        """
        channel_key = (body.get("channel_key") or "").strip()
        name = (body.get("name") or "").strip()
        if not channel_key or not name:
            return self._send('{"error":"channel_key and name required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        want = store.read_wantlist()
        wanted = list(want.get("wanted") or [])
        for w in wanted:
            if w.get("key") == channel_key:
                w["name"] = name
                break
        else:
            return self._send('{"error":"channel not in this run\'s wantlist"}',
                              "application/json", 404)
        store.write_wantlist_raw(wanted, want.get("missing") or [])
        lineup = store.read_meta().get("lineup")
        if lineup:
            try:
                lineups_mod.set_preference(self.root, lineup, channel_key,
                                           name=name)
            except Exception:
                pass  # never let a preference write break the rename itself
        self._send(json.dumps({"ok": True, "name": name,
                              "durable": bool(lineup)}), "application/json")

    def _duplicate_channel(self, run_id, body):
        """Copy a channel within a run so it can sit in a second group."""
        channel_key = (body.get("channel_key") or "").strip()
        if not channel_key:
            return self._send('{"error":"channel_key required"}',
                              "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)

        want = store.read_wantlist()
        wanted = want.get("wanted") or []
        keys = {w.get("key") for w in wanted}
        if not any(r.get("channel_key") == channel_key for r in store.load()):
            return self._send('{"error":"channel has no results to copy"}',
                              "application/json", 404)

        n = 2
        while f"{channel_key}_COPY{n}" in keys:
            n += 1
        new_key = f"{channel_key}_COPY{n}"

        numbers = [w.get("number") for w in wanted if w.get("number") is not None]
        # Above everything existing, so the copy can never land on a number
        # another channel already owns -- Dispatcharr keys off the number, so
        # a collision would silently overwrite that channel instead.
        number = (max(numbers) + 1) if numbers else 9000

        copied = store.duplicate_channel(channel_key, new_key, number,
                                         group=(body.get("group") or "").strip() or None)
        self._send(json.dumps({"ok": True, "key": new_key, "number": number,
                              "copied": copied}), "application/json")

    # Dispatcharr's group list, cached per connection. Two separate costs
    # made the Set-group modal take a full second to populate, both of them
    # pure waste on a list that changes when a push creates a group and
    # essentially never otherwise:
    #
    #   * a NEW client per request meant a fresh JWT every time, and Django
    #     hashes the password on each login -- measured at 1.00s of pure CPU
    #     before a single byte of the actual answer was fetched
    #   * the group list itself was re-paged from Dispatcharr on every open
    #     (1.04s), for a list the curator is opening over and over while
    #     filing channels one after another
    #
    # The client is kept because it caches its own token for 20 minutes;
    # the names are cached briefly on top. Export deliberately keeps making
    # its own client -- its stream_url_map cache is scoped to one push and
    # must not outlive it.
    _groups_clients = {}
    _groups_cache = {}          # spec -> (names, fetched_at)
    GROUPS_TTL = 120

    @classmethod
    def _remote_groups(cls, spec):
        hit = cls._groups_cache.get(spec)
        if hit and (time.time() - hit[1]) < cls.GROUPS_TTL:
            return hit[0]
        client = cls._groups_clients.get(spec)
        if client is None:
            client = cls._groups_clients[spec] = client_from_spec(spec)
        names = set()
        for g in client.groups():
            # Only groups that actually CONTAIN channels. A Dispatcharr fed
            # from a big M3U accumulates hundreds of empty groups mirroring
            # the provider's own group-titles (every country, every VOD
            # series name); offering those as somewhere to file a channel
            # buries the handful of real ones and is never what is meant.
            # Confirmed live: 407 groups existed, 1 had channels in it.
            if g.get("name") and (g.get("channel_count") or 0) > 0:
                names.add(g["name"])
        cls._groups_cache[spec] = (names, time.time())
        return names

    @classmethod
    def _forget_remote_groups(cls):
        """Called after a push, which is the one thing that creates or
        empties a group -- so the next open shows the real state rather than
        a cached list that predates the change."""
        cls._groups_cache.clear()

    def _prefetch_groups(self, store):
        def warm():
            try:
                prov = providers_mod.get(self.root,
                                         store.read_meta().get("provider_name") or "")
                if not prov or prov.get("scheme") != "dispatcharr":
                    prov = next((p for p in providers_mod.list_all(self.root)
                                if p.get("scheme") == "dispatcharr"), None)
                if prov:
                    self._remote_groups(prov["spec"])
            except Exception:
                pass
        threading.Thread(target=warm, daemon=True).start()

    def _known_groups(self, run_id):
        """Group names already in use, so setting one is a pick rather than
        a recall-and-retype. Merges what Dispatcharr already has with what
        this run has assigned locally but not yet pushed -- a group you
        created five minutes ago and have not exported should obviously be
        offerable to the next channel.
        """
        names = set()
        store = RunStore(self.root, run_id)
        for pick in (store.read_selection() or {}).values():
            if (pick or {}).get("group"):
                names.add(pick["group"])
        # The run's own provider is usually the M3U it probed, not the
        # Dispatcharr it exports to, so falling back to any saved
        # Dispatcharr connection is what actually finds the groups -- the
        # export target is a separate concept from the probe source.
        meta = store.read_meta()
        prov = providers_mod.get(self.root, meta.get("provider_name") or "")
        if not prov or prov.get("scheme") != "dispatcharr":
            prov = next((p for p in providers_mod.list_all(self.root)
                        if p.get("scheme") == "dispatcharr"), None)
        if prov:
            try:
                # Only the REMOTE half is cached. The names this run has
                # assigned locally are read fresh every time, so a group
                # created seconds ago is offered to the next channel
                # immediately -- which is the case the local half exists for.
                names |= self._remote_groups(prov["spec"])
            except Exception:
                pass  # offering local names only is better than failing
        return self._send(json.dumps({"groups": sorted(names, key=str.lower)}),
                          "application/json")

    def _epg_check(self, run_id, channel_key):
        """Live 'what's on now' per saved EPG source, for one channel.

        Separate from the run's own captured `expected` (frozen at probe
        time): this re-resolves the channel against every saved EPG source
        RIGHT NOW, so a curator can see whether the source the run used is
        still accurate, and compare it against sources added after the run
        finished (the real case this exists for -- a household adding a
        second EPG source specifically because the first one turned out
        unreliable for some channels has no other way to compare them
        side by side).
        """
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        by_channel = annotate_placeholders(store)
        records = by_channel.get(channel_key)
        if not records:
            return self._send('{"error":"no such channel"}', "application/json", 404)
        ranked = rank_mod.rank(records)
        top = ranked[0]
        expected = next((r.get("expected") for r in ranked if r.get("expected")), None)
        norm = self._norm()
        # The CHANNEL's own name, if it has been curated (renamed), wins over
        # the raw stream's declared name -- a rename is exactly the operator
        # correcting what the provider called something, and export.xmltv
        # already resolves this way. Without this, renaming "DMAX" to
        # "DMAX +1" changed the export but left Check EPG still searching
        # for plain DMAX, which some sources genuinely file separately
        # (confirmed live: open-epg has a distinct DMAXPlus1.uk entry that
        # was invisible until the search term itself said "+1").
        entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                     if w.get("key") == channel_key), {})
        name = entry.get("name") or top.get("stream_name") or channel_key
        sel = (store.read_selection() or {}).get(channel_key) or {}
        overrides = ({sel["epg_channel_source"]: sel["epg_channel_id"]}
                    if sel.get("epg_channel_source") and sel.get("epg_channel_id") else None)
        sources = epgcheck_mod.check_all(self.root, name,
                                         top.get("tvg_id") or "", norm, overrides)
        # The consensus winner: which saved source's match actually agrees
        # in NAME with this channel, not just whichever is listed first --
        # this is what a persistent, always-visible badge on the channel
        # shows, alongside the per-source "what's on now" list that was
        # already here. bump_trust=True: this endpoint backs the page's own
        # per-channel display, a real curation signal, not idle exploration.
        winner = epgcheck_mod.consensus_winner(sources, root=self.root, bump_trust=True)
        self._send(json.dumps({"expected": expected, "sources": sources,
                              "winner": winner}),
                  "application/json")

    def _watermark_crop(self, run_id, rec_key):
        """The channel's marked watermark/logo area, cropped out of THIS
        candidate's already-captured frame -- never a fresh probe. The
        frame is already sitting on disk from whenever this candidate was
        last probed; cropping a small region out of a local JPEG costs a
        fraction of a second and touches the provider not at all.

        Deliberately a hard 404 (not an empty/placeholder image) when the
        channel has no marked area at all -- the whole point raised when
        this was scoped: a channel nobody has marked must never trigger
        any watermark work, not even a fast local one. This is the ONLY
        place that work happens, so this check is the entire enforcement
        of that.
        """
        store = RunStore(self.root, run_id)
        channel_key = rec_key.split("|", 1)[0] if rec_key else ""
        sel = (store.read_selection() or {}).get(channel_key) or {}
        box = sel.get("watermark_box")
        if not box:
            return self._send('{"error":"no watermark area marked for this channel"}',
                              "application/json", 404)
        frame_path = store.frame_path(rec_key)
        if not os.path.isfile(frame_path):
            return self._send('{"error":"no captured frame for this candidate"}',
                              "application/json", 404)
        try:
            x, y, w, h = (float(box["x"]), float(box["y"]),
                         float(box["w"]), float(box["h"]))
        except (KeyError, TypeError, ValueError):
            return self._send('{"error":"malformed watermark area"}',
                              "application/json", 500)
        # The output filename bakes in a hash of the box -- redrawing the
        # box naturally invalidates every previous crop without needing
        # explicit cache-clearing logic, and an old crop from a previous
        # box is simply an orphaned file from then on (same never-delete-
        # just-stop-referencing pattern already used for stale custom
        # streams elsewhere in this project).
        box_hash = hashlib.sha256(
            f"{x:.4f}:{y:.4f}:{w:.4f}:{h:.4f}".encode()).hexdigest()[:10]
        out_dir = os.path.join(store.dir, "watermarks")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{RunStore.safe_name(rec_key)}-{box_hash}.jpg")
        # Stale, not just missing: a candidate can be re-probed (Diagnose,
        # a single re-probe, a fresh Verify pass) any time after its crop
        # was first cached, overwriting frame_path with genuinely
        # different content -- confirmed live, a channel's screenshot had
        # visibly moved on from a re-probe while its watermark crop kept
        # showing the OLD picture, because "the file already exists" was
        # the only check here. The box's own hash already invalidates a
        # crop when the MARKED AREA changes; this is the other half --
        # invalidating it when the PICTURE underneath it changes instead.
        stale = (os.path.isfile(out_path)
                and os.path.getmtime(frame_path) > os.path.getmtime(out_path))
        if not os.path.isfile(out_path) or stale:
            ffmpeg = os.environ.get("PROBARR_FFMPEG", "ffmpeg")
            # A marked area is often a small fraction of an already
            # modest-resolution frame -- confirmed live, a ~7%x5% box on a
            # 704x396 source (a real BBC One candidate, itself a lower-
            # bitrate DASH rendition, not a bug in the crop) crops down to
            # 48x20 real pixels, which the browser then enlarges with its
            # own upscaling to match the row height. That softness is a
            # property of the source resolution, not something a sharper
            # filter here can substantively fix -- tried a lanczos upscale
            # server-side and it wasn't worth the extra step for what it
            # actually bought. Left as a native-resolution crop.
            crop_expr = f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-i", frame_path, "-vf", crop_expr,
                    "-frames:v", "1", "-q:v", "3", out_path],
                    capture_output=True, timeout=15, check=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    OSError) as e:
                return self._send(json.dumps({"error": f"crop failed: {e}"}),
                                  "application/json", 500)
        return self._file(run_id, ["watermarks", os.path.basename(out_path)])

    def _logo_countries(self, run_id):
        """Country/region folder names available to search, for the picker's
        dropdown. run_id is unused (the catalogue isn't per-run) but kept for
        route symmetry with every other /run/<id>/... endpoint.
        """
        self._send(json.dumps({"countries": logos_mod.fetch_countries(self.root)}),
                  "application/json")

    def _logo_search(self, run_id, country_dir, query):
        """Fuzzy-matched logo candidates from tv-logo/tv-logos for one
        country, backing the logo picker's search box. Every result is a
        link to GitHub's own hosting -- see logos.py's module docstring for
        why that's the whole point, not an implementation detail.
        """
        if not country_dir:
            return self._send(json.dumps({"results": []}), "application/json")
        norm = self._norm()
        results = logos_mod.search(self.root, query, country_dir, norm)
        self._send(json.dumps({"results": results}), "application/json")

    def _epg_search(self, run_id, source_name, query):
        """One saved EPG source's channel names matching `query`, live --
        backs Check EPG's manual search box for when resolve() guessed
        wrong or a channel is filed under a name the matcher never tries.
        """
        norm = self._norm()
        try:
            hits = epgcheck_mod.search_source(self.root, source_name, query, norm)
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:200]}), "application/json", 404)
        self._send(json.dumps({"hits": hits}), "application/json")

    def _test_provider(self, spec):
        """Try loading a source spec and report what came back.

        This is the whole point of the button: pasting a playlist URL or a
        set of Xtream credentials is easy to get subtly wrong (a stray space,
        the wrong port, http vs https), and the only feedback without this is
        starting a real multi-hour run and discovering the mistake at the end.
        """
        if not spec.strip():
            return self._send('{"ok":false,"error":"empty address"}',
                              "application/json")
        try:
            streams = load_source(spec.strip())
            return self._send(json.dumps({"ok": True, "channels": len(streams)}),
                              "application/json")
        except Exception as e:
            return self._send(json.dumps({"ok": False, "error": str(e)[:300]}),
                              "application/json")

    def _browse(self, body):
        """Group a source's raw channel names, with no probing at all.

        This is the answer to "I don't know what to type into a wantlist" --
        the fresh-install person who has a provider URL and nothing else.
        Probing to discover channels would mean paying the ffmpeg cost of a
        full run just to find out what exists; this is pure text grouping
        (the exact same normalize.group_candidates() a run uses to build its
        candidate pools), so it returns near-instantly even against a
        catalogue of tens of thousands of entries.
        """
        provider_name = (body.get("provider") or "").strip()
        prov = providers_mod.get(self.root, provider_name)
        if not prov:
            return self._send('{"error":"provider not found"}', "application/json", 404)

        regions = body.get("regions")
        regions = [r.strip().upper() for r in regions.split(",") if r.strip()] \
            if isinstance(regions, str) and regions.strip() else None

        try:
            streams = load_source(prov["spec"])
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:400]}),
                              "application/json", 502)

        norm = self._norm()
        pools = group_candidates(streams, norm, regions=regions, include_unmarked=True)

        channels = []
        for key, cands in pools.items():
            names = sorted({c.name for c in cands})
            # The shortest name is usually the least-qualified spelling --
            # "BBC One" rather than "UKFHD | BBC One HD [Multi-Audio]" -- and
            # so the most natural default label for the group.
            best = min(names, key=len)
            channels.append({"key": key, "name": best, "count": len(cands),
                            "examples": names[:6]})
        channels.sort(key=lambda c: c["name"].lower())

        self._send(json.dumps({"channels": channels, "total_streams": len(streams)}),
                   "application/json")

    def _start_run(self, body):
        """Kick off a verify run in the background from the New Run form.

        A `lineup` in the body pre-fills anything the form did not specify
        from that lineup's saved configuration, so "re-verify my
        lineup" is one field rather than re-selecting the same provider,
        wantlist, EPG and regions every time. The run records which lineup
        it belongs to, which is what lets its curation inherit that
        lineup's accumulated per-channel decisions.
        """
        lineup_name = (body.get("lineup") or "").strip()
        if lineup_name:
            lu = lineups_mod.get(self.root, lineup_name) or {}
            for k in ("source", "provider", "wantlist", "epg", "regions"):
                if not (body.get(k) or "").strip() and lu.get(k):
                    body[k] = lu[k]
        self._resolve_run_body(body)

        source = (body.get("source") or "").strip()
        if not source:
            return self._send('{"error":"a provider/source is required"}',
                              "application/json", 400)
        kwargs = self._run_kwargs(body, lineup_name)
        run_id = body.get("run_id") or None
        if run_id:
            kwargs["run_id"] = run_id
        run_id = runs_mod.start(self.root, **kwargs)
        return self._send(json.dumps({"ok": True, "run_id": run_id}),
                          "application/json")

    def _resolve_run_body(self, body):
        # A saved lineup, or a form field filled in from one, can carry
        # friendly NAMES where a run needs addresses -- "mybunny" rather than
        # the provider spec, "open-epg" rather than its XMLTV URL. Both are
        # the natural thing to store and neither is usable as-is, so they are
        # resolved here, for any caller, rather than failing later with an
        # unhelpful "no such source".
        # A lineup that names its provider but has no address of its own is
        # complete, not broken: the provider entry IS the address. Resolving
        # it here is what lets "re-verify my lineup" work with nothing
        # but a name saved against it.
        if not (body.get("source") or "").strip() and body.get("provider"):
            prov = providers_mod.get(self.root, body["provider"])
            if prov:
                body["source"] = prov["spec"]
        if body.get("source") and "://" not in body["source"]:
            prov = providers_mod.get(self.root, body["source"])
            if prov:
                body["provider"] = body.get("provider") or prov["name"]
                body["source"] = prov["spec"]
        if body.get("epg") and "://" not in body["epg"]:
            src = next((e for e in epgsources_mod.list_all(self.root)
                        if e["name"] == body["epg"]), None)
            body["epg"] = src["url"] if src else ""

    def _run_kwargs(self, body, lineup_name=None):
        """The verify arguments a request (or the scheduler) implies.

        Split out of the handler so an unattended re-verify is built by
        EXACTLY the same code as a hand-started one -- a scheduler that
        assembled its own arguments would drift from the form the moment
        either changed, and the divergence would only show up in a run
        nobody was watching.
        """
        source = (body.get("source") or "").strip()
        cfg = settings_mod.read(self.root)
        kwargs = dict(
            source=source,
            # Recorded so the Curate page's "Export to Dispatcharr" panel can
            # default the push target to the SAME saved connection the run
            # was sourced from -- the common case needs no separate
            # configuration at all.
            provider_name=(body.get("provider") or "").strip() or None,
            wantlist=(body.get("wantlist") or "").strip() or None,
            epg=(body.get("epg") or "").strip() or None,
            # Absent from every path except /browse until a real run against
            # a multi-country provider proved why that was wrong: with no
            # region filter, a generically-named channel ("TLC", "CNN",
            # "MTV"...) matches the same-named channel from every other
            # country on the platform too. Measured live: 158 UK channels
            # produced 1,565 candidates -- the worst offenders (TLC 56
            # candidates, Cartoon Network 55, Nickelodeon 49...) were almost
            # entirely other countries' identically-named channels, not real
            # UK spelling variants.
            regions=[r.strip().upper() for r in (body.get("regions") or "").split(",")
                    if r.strip()] or None,
            # Off by default: a Regions filter alone only rejects a stream
            # whose name or group title carries a RECOGNISABLE country
            # marker. Most aggregated multi-country providers list plenty
            # of channels with no marker at all, and those sail through
            # untouched regardless of what's typed into Regions -- exactly
            # what a user restricting to "US" would not expect. Strict
            # drops every unmarked candidate too, at the cost of also
            # dropping genuine single-country channels that just don't
            # carry a marker.
            strict_region=bool(body.get("strict_region")),
            # Without this a run matched by different rules than the
            # catalogue search that found the channel in the first place.
            aliases=aliases_mod.read(self.root),
            # A run probes for hours on a one-connection subscription, so it
            # pauses rather than recording the provider's holding card as a
            # lineup of dead streams.
            gate=self._viewer_gate,
            concurrency=int(body.get("concurrency") or cfg["concurrency"]),
            gap_seconds=cfg["gap_seconds"],
            sample_seconds=int(body.get("sample_seconds") or cfg["sample_seconds"]),
            frame_height=cfg["frame_height"],
            thumb_height=cfg["thumb_height"],
        )
        if lineup_name:
            kwargs["lineup"] = lineup_name
        return kwargs

    def _reprobe(self, run_id):
        """Re-run one candidate and append a fresh result.

        Worth having because a single frame is a single instant: a capture can
        land in an ad break, on a channel ident, or on the one dark shot in an
        otherwise bright programme. Re-probing costs one connection and answers
        "was that representative?" without redoing the whole run.
        """
        body, sent = self._json_body(limit=64 * 1024)
        if sent:
            return
        rec_key = body.get("rec_key") or ""
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        record = next((r for r in store.load()
                       if (r.get("rec_key") or "") == rec_key), None)
        if not record:
            return self._send('{"error":"unknown stream"}', "application/json", 404)
        if _reprobeable_url(record) is None:
            # An older run, from before probarr stored the real URL alongside
            # the redacted one, whose URL genuinely had credentials in it --
            # the only piece left is the "***"-masked copy, which cannot be
            # probed. Distinguished from a plain missing-URL case so the
            # operator gets an actionable message instead of a bare 404.
            return self._send(
                '{"error":"this run predates probarr storing the real URL, '
                'and its address had credentials redacted out of it -- '
                're-run verify to enable re-probing on this run"}',
                "application/json", 409)

        # Queued rather than run inline. The button is trivially spammable, and
        # each inline probe would be another simultaneous connection to a
        # provider that may only permit one.
        outcome = self._queue().submit(f"{run_id}|{rec_key}",
                                       {"run_id": run_id, "rec_key": rec_key,
                                        "lane": self._lane_for_run(store),
                                        "diagnose": bool(body.get("diagnose")),
                                        "preview": bool(body.get("preview"))})
        code = 200 if outcome.get("accepted") else 429 \
            if outcome.get("state") == "cooldown" else 200
        self._send(json.dumps(outcome), "application/json", code)

    def _diagnose_channel(self, run_id, body):
        """Re-probe every candidate for one channel in diagnose mode.

        The scenario this exists for: one channel is misbehaving in a real
        player, and the fix isn't obvious from a single still frame. Rather
        than re-probe just the current pick, this queues every candidate the
        channel has -- so switching to a different stream, if one is
        actually better, is something the operator can see rather than guess
        at -- each with a longer sample and a kept video clip instead of a
        discarded one.
        """
        channel_key = (body.get("channel_key") or "").strip()
        if not channel_key:
            return self._send('{"error":"channel_key required"}', "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        by_channel = self._records_by_channel(store, {channel_key})
        if not by_channel.get(channel_key):
            return self._send('{"error":"no candidates for this channel"}',
                              "application/json", 404)

        include_dead = bool(body.get("include_dead"))
        queued, skipped = self._diagnose_queue_records(
            run_id, by_channel[channel_key], include_dead, self._lane_for_run(store))
        self._send(json.dumps({"ok": True, "queued": queued,
                              "skipped": skipped,
                              # Serial by design, so a plain multiplication
                              # is an honest estimate rather than a guess.
                              "eta_seconds": len(queued) *
                                             (self.DIAGNOSE_SAMPLE_SECONDS + 6)}),
                  "application/json")

    @staticmethod
    def _records_by_channel(store, channel_keys):
        """All candidate records for a set of channels, loaded in ONE pass.

        Used by both the single-channel and batch diagnose endpoints -- a
        batch across N channels must not re-read the whole results file N
        times, the same reason the single-channel path stopped doing it per
        candidate.
        """
        by_channel = {}
        for r in store.load():
            ck = r.get("channel_key")
            if ck in channel_keys and r.get("rec_key"):
                by_channel.setdefault(ck, {})[r["rec_key"]] = r
        return by_channel

    def _diagnose_queue_records(self, run_id, records, include_dead, lane=None):
        """Queue a diagnose probe for each candidate in `records` (rec_key ->
        record), skipping dead ones unless `include_dead`. Returns
        (queued, skipped) exactly as the single-channel endpoint always has.

        A diagnose probe is 25 seconds plus a kept clip, run one at a time
        on a connection-limited provider -- so the cost is entirely in how
        many candidates it takes on. A candidate that returned nothing at
        all is skipped by default: spending 25s recording a stream that
        already failed to open delays every candidate behind it that might
        actually explain the fault. The per-card re-probe button still
        reaches those individually, and `include_dead` asks for the old
        behaviour when a slow-starting stream is the actual suspicion.
        """
        queued, skipped = [], []
        for rk in sorted(records):
            record = records[rk]
            if _reprobeable_url(record) is None:
                continue
            if not include_dead and record.get("status") == "dead":
                skipped.append(rk)
                continue
            outcome = self._queue().submit(f"{run_id}|{rk}",
                                           {"run_id": run_id, "rec_key": rk,
                                            "lane": lane, "diagnose": True})
            queued.append({"rec_key": rk, **outcome})
        return queued, skipped

    def _diagnose_batch(self, run_id, body):
        """Diagnose every candidate for a whole set of channels at once --
        the batch counterpart to `_diagnose_channel`, for "diagnose everyone
        currently flagged" rather than one channel at a time.
        """
        channel_keys = [k for k in (body.get("channel_keys") or []) if k]
        if not channel_keys:
            return self._send('{"error":"channel_keys required"}', "application/json", 400)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        include_dead = bool(body.get("include_dead"))
        by_channel = self._records_by_channel(store, set(channel_keys))

        queued, skipped, per_channel = [], [], []
        for ck in channel_keys:
            records = by_channel.get(ck)
            if not records:
                per_channel.append({"channel_key": ck, "queued": 0, "skipped": 0})
                continue
            ch_queued, ch_skipped = self._diagnose_queue_records(
                run_id, records, include_dead, self._lane_for_run(store))
            queued.extend(ch_queued)
            skipped.extend(ch_skipped)
            per_channel.append({"channel_key": ck, "queued": len(ch_queued),
                                "skipped": len(ch_skipped)})
        self._send(json.dumps({"ok": True, "channels": len(channel_keys),
                              "queued": len(queued), "skipped": len(skipped),
                              "per_channel": per_channel,
                              "eta_seconds": len(queued) *
                                             (self.DIAGNOSE_SAMPLE_SECONDS + 6)}),
                  "application/json")

    # A viewer holds the subscription's connection, so probing during one
    # gets a holding card or nothing -- results that look exactly like a bad
    # stream and quietly poison the run. Cached briefly because the queue
    # asks before every probe.
    _live_cache = (0.0, None)   # (checked_at, active_streams()-or-None)
    GATE_TTL = 5.0

    # Dispatcharr's event log, cached like the group list and for the same
    # reason: Find streams and every channel import were each fetching and
    # re-correlating the whole system-events log fresh, on every open --
    # exactly the "re-download a big thing on every click" mistake the EPG
    # index cache already went through once this session.
    _events_cache = {}   # spec -> (fetched_at, {channel_name: {stream_id: n}})
    EVENTS_TTL = 300
    # A stream's URL essentially never changes once created, so this is
    # cached indefinitely per process rather than TTL'd -- unlike the event
    # log, there is nothing here that goes stale.
    _stream_url_cache = {}   # (base, stream_id) -> url or None

    @classmethod
    def _cached_stream_url(cls, client, sid):
        ck = (client.base, sid)
        if ck not in cls._stream_url_cache:
            try:
                cls._stream_url_cache[ck] = client.stream(sid).get("url")
            except Exception:
                cls._stream_url_cache[ck] = None
        return cls._stream_url_cache[ck]

    # Dispatcharr's live "what's on now" for every channel it has, one bulk
    # call, cached like the event log -- the exact mistake this session
    # already made once (re-fetching the whole EPG index per channel, per
    # click) and is not repeating here.
    _programs_cache = {}   # base -> (fetched_at, {channel_uuid: programme})
    PROGRAMS_TTL = 300

    @classmethod
    def _cached_current_programs(cls, client):
        now = time.time()
        hit = cls._programs_cache.get(client.base)
        if hit and (now - hit[0]) < cls.PROGRAMS_TTL:
            return hit[1]
        by_uuid = {p["channel_uuid"]: p for p in client.current_programs()
                  if p.get("channel_uuid")}
        cls._programs_cache[client.base] = (now, by_uuid)
        return by_uuid

    @classmethod
    def _cached_failed_streams(cls, client, spec):
        now = time.time()
        hit = cls._events_cache.get(spec)
        if hit and (now - hit[0]) < cls.EVENTS_TTL:
            return hit[1]
        try:
            data = client.failed_streams()
        except Exception:
            data = {}
        cls._events_cache[spec] = (now, data)
        return data

    @classmethod
    def _live_dispatcharr(cls):
        """What Dispatcharr is streaming right now, or None if unavailable.

        Shared by _viewer_gate() (should a NEW probe wait at all) and
        _lane_viewer_count() (how many connections are viewers currently
        using, for weighing against a lane's real concurrency) -- both ask
        the identical question, so both read through the same short-lived
        cache rather than hitting Dispatcharr twice for one decision.
        """
        now = time.time()
        hit = cls._live_cache
        if hit and (now - hit[0]) < cls.GATE_TTL:
            return hit[1]
        live = None
        try:
            prov = next((p for p in providers_mod.list_all(cls.root)
                        if p.get("scheme") == "dispatcharr"), None)
            if prov:
                spec = prov["spec"]
                client = cls._groups_clients.get(spec)
                if client is None:
                    client = cls._groups_clients[spec] = client_from_spec(spec)
                live = client.active_streams()
        except Exception:
            live = None
        cls._live_cache = (now, live)
        return live

    @classmethod
    def _lane_viewer_count(cls, lane):
        """How many live Dispatcharr viewers are using this lane's provider
        connections right now -- 0 if unknown or nothing is watching.

        Used to weigh a viewer against a probe's OWN connection budget:
        both draw from the same provider allowance, so a lane's effective
        available capacity is its real limit minus whatever viewers are
        already using, not just minus other probes.
        """
        live = cls._live_dispatcharr()
        return live["count"] if live else 0

    @classmethod
    def _viewer_gate(cls, lane=None):
        """None when probing may start, else why it must not.

        Deliberately fails OPEN: if the check itself errors -- no
        Dispatcharr saved, instance down, endpoint changed -- probing
        proceeds as it always did, because a broken safety check must not
        become a reason nothing can be probed.

        Real bug this fixed: this used to block ALL probing the instant
        Dispatcharr reported ANYONE watching ANYTHING, phrased as "the
        provider allows one connection at a time" -- true for some
        providers, flatly false for one saved with its own concurrency
        above 1 (a household deliberately buys a multi-stream account
        specifically so watching and probing can happen at once). `lane`
        is the provider this gate is being asked on behalf of; its real
        limit is what a live viewer is actually competing against, not an
        assumed single connection. A viewer only has to block probing once
        they've genuinely used up every slot the provider allows.
        """
        live = cls._live_dispatcharr()
        if not live:
            return None
        limit = max(1, int(cls._lane_limit(lane))) if lane else 1
        if live["count"] >= limit:
            what = ", ".join(live["channels"][:3]) or "a channel"
            return (f"waiting \u2014 {what} is playing, and that's "
                   f"already using every connection this provider allows")
        return None

    @classmethod
    def _lane_limit(cls, lane):
        """This lane's (provider's) own concurrency, or the global default.

        `lane` is a provider name (see `_lane_for_run`). A provider saved
        with no explicit limit falls straight through to the same global
        setting every job used before lanes existed.
        """
        if lane and lane != "_default":
            prov = providers_mod.get(cls.root, lane)
            if prov and prov.get("concurrency"):
                return prov["concurrency"]
        return settings_mod.read(cls.root)["concurrency"]

    @classmethod
    def _lane_for_run(cls, store):
        """The provider a run's jobs should be pooled against.

        A run has exactly one source, so its own provider_name IS the lane
        -- pooling every job against the same provider under one shared cap
        regardless of which run (or which of Curate's many actions) queued
        it, while a different run against a different provider gets its own
        cap entirely instead of contending for the same slots.
        """
        return (store.read_meta().get("provider_name") or "").strip() or None

    @classmethod
    def _queue(cls):
        """Process-wide queue, created on first use."""
        if getattr(cls, "_pq", None) is None:
            cls._pq = probequeue.ProbeQueue(
                cls._run_reprobe,
                concurrency=lambda: settings_mod.read(cls.root)["concurrency"],
                gap=lambda: settings_mod.read(cls.root)["gap_seconds"],
                journal=os.path.join(cls.root, "probe-queue.json"),
                gate=cls._viewer_gate,
                lane_limit=cls._lane_limit,
                viewer_count=cls._lane_viewer_count)
        return cls._pq

    # A diagnose pass samples much longer than a normal probe -- long enough
    # that a genuine ABR-switching stall or a slow-fetch stretch has a real
    # chance to show up in the kept clip, not just in one 8-10s snapshot.
    DIAGNOSE_SAMPLE_SECONDS = 25
    # Short and deliberately not a diagnose: this is "what does it actually
    # look like right now", asked from any candidate, not a full re-scan of
    # every stream on the channel. Long enough to see real motion, short
    # enough that it costs almost nothing on a connection-limited provider.
    PREVIEW_SAMPLE_SECONDS = 6
    # The plain single ↻ re-probe. This used to fall through to the SAME
    # sample length as a full unattended Verify run (cfg["sample_seconds"],
    # 8-10s by default) -- a leftover from before the standalone Preview
    # button was merged into this one (see its docstring above: "a plain
    # re-probe now updates the status AND gives a watchable clip in one
    # action, so having both was two buttons for one job"). The merge
    # carried over the clip capture but never picked up Preview's short
    # window, so the button that got faster in every other respect stayed
    # exactly as slow to run.
    #
    # A full Verify run needs a longer decode because nobody is watching
    # it: the corruption-rate math it depends on (see WARMUP_SECONDS /
    # CORRUPTION_RATE_MAX in probe.py) was tuned against 10-25s samples
    # specifically to be statistically meaningful unattended. A ↻ click is
    # the opposite case -- a human is about to look at the resulting frame
    # themselves right now, and real playback failures are independently
    # corroborated by Dispatcharr's own stream-switch history. That is
    # exactly the case PREVIEW_SAMPLE_SECONDS was already proven for, so
    # reuse it rather than inventing an untested third number.
    REPROBE_SAMPLE_SECONDS = PREVIEW_SAMPLE_SECONDS

    @classmethod
    def _expected_now(cls, record, store=None):
        """What the guide says is on this channel at this moment, or None.

        Uses the saved EPG sources in order, first match winning, which is
        the same rule the EPG check panel shows -- and the same cached
        guides, so it costs nothing after the first lookup.
        """
        name = record.get("stream_name") or record.get("channel_key") or ""
        channel_key = record.get("channel_key")
        chsel = {}
        if store is not None:
            # The curated channel name wins over the raw stream's, same
            # reasoning as the EPG check panel: a rename is the operator
            # correcting what the provider called something, and some
            # sources genuinely file a "+1" variant under a name that only
            # appears once the search term itself says "+1".
            entry = next((w for w in (store.read_wantlist().get("wanted") or [])
                         if w.get("key") == channel_key), None)
            if entry and entry.get("name"):
                name = entry["name"]
            chsel = (store.read_selection() or {}).get(channel_key) or {}
        try:
            norm = Normalizer(aliases=aliases_mod.read(cls.root))
            at = datetime.datetime.now(datetime.timezone.utc)
            # An explicit EPG source pick (Check EPG's "Use this", or a
            # manually pinned exact guide entry) has to keep being honoured
            # by every later capture, not just the live comparison panel --
            # confirmed live, diagnosing a channel just after picking a
            # different source still captured the OLD source's programme,
            # because this used to only ever walk every saved source in
            # list order and take whichever matched first, blind to the
            # explicit pick sitting right there in selection.json. Same
            # precedence _resolve_epg_overrides() already uses for the
            # actual Dispatcharr push, so a diagnosed channel's guide panel
            # agrees with what gets exported -- not a third opinion.
            pref = chsel.get("epg_source")
            if pref:
                src = epgsources_mod.get(cls.root, pref)
                if src:
                    g = epgcheck_mod._indexed_guide(src["url"], norm, cls.root)
                    override_id = (chsel.get("epg_channel_id")
                                  if chsel.get("epg_channel_source") == pref else None)
                    cid = (override_id if override_id and override_id in g.display_names
                          else g.resolve(record.get("tvg_id") or None, name, norm))
                    if cid:
                        # Whatever this source says STANDS, including None.
                        # Falling through on a None meant a schedule gap in
                        # the pinned source (overnight, or a source that
                        # simply stops at midnight) silently stamped the
                        # frame with a DIFFERENT source's programme --
                        # reintroducing, in a narrower form, exactly the
                        # wrong-source capture this branch exists to stop.
                        # Only an unusable pick (source deleted, or it does
                        # not carry this channel at all) falls through.
                        return g.now_playing(cid, at)
            for src in epgsources_mod.list_all(cls.root):
                g = epgcheck_mod.load_cached(src["url"], root=cls.root)
                cid = g.build_name_index(norm).resolve(
                    record.get("tvg_id") or None, name, norm)
                if cid:
                    now = g.now_playing(cid, at)
                    if now:
                        return now
        except Exception:
            pass
        # Nothing found: better an empty guide panel than one confidently
        # showing a programme that ended hours ago.
        return None

    @classmethod
    def _run_reprobe(cls, payload):
        store = RunStore(cls.root, payload["run_id"])
        rec_key = payload["rec_key"]
        diagnose = bool(payload.get("diagnose"))
        preview = bool(payload.get("preview"))
        record = next((r for r in store.load()
                       if (r.get("rec_key") or "") == rec_key), None)
        if not record:
            # A channel added from the provider catalogue has no prior
            # result to re-probe -- the payload carries the stream itself
            # so the first probe can create the record rather than needing
            # one to already exist.
            seed = payload.get("seed")
            if not seed:
                return {"error": "record vanished"}
            record = {"rec_key": rec_key, "channel_key": seed["channel_key"],
                     "stream_id": seed["stream_id"], "stream_name": seed["name"],
                     "url": seed["url"], "url_redacted": seed.get("redacted", ""),
                     "group": seed.get("group", ""), "logo": seed.get("logo", ""),
                     "tvg_id": seed.get("tvg_id", "")}
        url = _reprobeable_url(record)
        if url is None:
            return {"error": "no usable URL for this record"}
        cfg = settings_mod.read(cls.root)
        sample_seconds = (cls.DIAGNOSE_SAMPLE_SECONDS if diagnose
                          else cls.PREVIEW_SAMPLE_SECONDS if preview
                          else cls.REPROBE_SAMPLE_SECONDS)
        try:
            # A clip is now captured on every re-probe, not just Diagnose --
            # it is a stream-copy riding the same single decode already
            # happening, so it costs nothing beyond disk I/O. The standalone
            # Preview button and its short 6s sample existed only because a
            # plain re-probe did not do this; a plain re-probe now updates
            # the status AND gives a watchable clip in one action, so having
            # both was two buttons for one job.
            opts = ProbeOptions(sample_seconds=sample_seconds,
                                frame_height=cfg["frame_height"],
                                thumb_height=cfg["thumb_height"],
                                capture_timeout=sample_seconds + 35,
                                capture_clip=True).resolved()
        except RuntimeError as e:
            return {"error": str(e)}

        class _S:  # minimal stand-in; probe only reads .url
            name = record.get("stream_name", "")
            tvg_id = record.get("tvg_id", "")
        _S.url = url

        clip_path = store.clip_path(rec_key)
        result = probe(_S, opts, store.thumb_path(rec_key),
                       store.frame_path(rec_key), store.crop_path(rec_key),
                       clip_path)
        safe = RunStore.safe_name(rec_key)
        fresh = {**record,
                 **{k: v for k, v in result.items()
                    if k not in ("thumb", "frame", "crop", "clip")},
                 # Rebuilt from THIS capture's result, exactly like a normal
                 # verify run does (verify.py's one()) -- not inherited from
                 # the old record. An older record may carry no frame/crop key
                 # at all (runs made before those fields existed) or a stale
                 # thumb-only record, and blindly spreading **record over that
                 # would leave the UI with no image to show even though a
                 # fresh capture just succeeded and wrote real files to disk.
                 "thumb": f"thumbs/{safe}.jpg" if result.get("thumb") else None,
                 "frame": f"frames/{safe}.jpg" if result.get("frame") else None,
                 "crop": f"crops/{safe}.jpg" if result.get("crop") else None,
                 "url": url,   # ensure future re-probes on this record work too
                 "probed_at": time.time(), "reprobed": True, "diagnosed": diagnose}
        # A non-diagnose reprobe of a record that previously HAD a clip must
        # not silently keep advertising it -- the clip on disk is now from a
        # different (shorter) capture than the rest of this record's numbers.
        fresh["clip"] = f"clips/{safe}.mp4" if result.get("clip") else None
        # The guide entry has to describe THIS capture, not the one this
        # record used to hold. `expected` is what was on air when the stream
        # was first probed, and copying it forward left a frame captured at
        # 23:39 sitting under a programme that finished at 22:00 -- the one
        # comparison the panel exists to make, silently wrong, in the moment
        # a re-probe is most likely to be trusted.
        fresh["expected"] = cls._expected_now(fresh, store)
        # Appended, not rewritten: the log stays append-only and load() takes
        # the newest record for this probe.
        store.append(fresh)
        return {"status": fresh.get("status"), "reason": fresh.get("reason", "")}

    @staticmethod
    def _run_dates(r):
        """The two completion timestamps, rendered for the run list."""
        def fmt(ts):
            return time.strftime("%d %b %H:%M", time.localtime(ts)) if ts else None
        full, last = fmt(r.get("full_completed")), fmt(r.get("last_completed"))
        bits = []
        if full:
            bits.append(f"full run: {html.escape(full)}")
        elif last:
            bits.append("full run: never completed")
        if last and last != full:
            bits.append(f"last pass: {html.escape(last)}")
        if r.get("run_state") == "running":
            # run.json is written by the runner process itself, so a state
            # of "running" only reflects reality while that exact process
            # is still alive -- a container restart mid-run (this session's
            # own deploy process does this routinely) leaves it stuck
            # reading "running" forever, with no live job to actually
            # finish it. runs_mod.status() is the in-memory "is a job for
            # this run_id actually alive right now" check; None means it
            # isn't, no matter what the file on disk still claims.
            if runs_mod.status(r["run_id"]):
                bits.append("running now")
            else:
                bits.append('<span style="color:var(--warn)">stalled -- the process '
                            "that was running this stopped (e.g. a restart) before it "
                            "finished. Delete it and start again, or Stop then re-run "
                            "the same lineup.</span>")
        if bits:
            return " &middot; ".join(bits)
        return ('not completed yet -- probably an aborted or empty run; '
               "safe to Delete if you don't recognise it")

    def _index(self):
        runs = RunStore.list_runs(self.root)
        if not runs:
            # A first-run screen that says only "start a run" assumes you
            # already know what a run is, what it needs, and in what order.
            # Three numbered steps cost nothing and are the difference
            # between a tool that explains itself and one that doesn't.
            rows = (
                '<div class="run"><div><b>Nothing here yet &mdash; three steps '
                'to your first result</b>'
                '<div class="m" style="margin-top:6px;line-height:1.9">'
                '<b>1.</b> <a href="/providers">Add your provider</a> '
                '&mdash; an M3U URL, an Xtream login, or a Dispatcharr you '
                'already run.<br>'
                '<b>2.</b> <a href="/browse">Browse the channels</a> it '
                'carries and tick the ones you want. That saves a '
                '<i>wantlist</i>: the channels probarr will look for, which '
                'is what keeps a run to minutes instead of hours.<br>'
                '<b>3.</b> <a href="/new">Start a run</a>. It probes every '
                'stream your provider offers for those channels, decodes a '
                'real sample of each, and lands in <i>Curate</i> &mdash; '
                'where you see the actual pictures and pick the winners.'
                '</div></div></div>')
        else:
            rows = "".join(
                f'<div class="run"><div style="flex:1"><b>{html.escape(r["run_id"])}</b>'
                f'<div class="m">{r.get("channels","?")} channels &middot; '
                f'{r.get("candidates","?")} candidates &middot; '
                f'{html.escape(str(r.get("source","")))}</div>'
                f'<div class="m">{self._run_dates(r)}</div></div>'
                f'<a href="/run/{urllib.parse.quote(r["run_id"])}/curate">'
                f'<button class="primary">Curate</button></a>'
                f'<button data-clear-images="{html.escape(r["run_id"])}" '
                f'title="Delete every captured thumbnail, frame and clip for '
                f'this run. Every probe result and curated decision is kept '
                f'\u2014 candidates just show \u201cno frame\u201d until '
                f'next probed.">Clear images</button>'
                f'<button class="danger" data-del-run="{html.escape(r["run_id"])}">'
                f'Delete</button></div>'
                for r in runs)
        self._send(INDEX
                   .replace("__CSS__", CSS)
                   .replace("__TOPBAR__", topbar(f"{len(runs)} run(s)",
                                                 active="runs"))
                   .replace("__ROWS__", rows))

    def _sheet(self, run_id):
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send("<h1>no such run</h1>", code=404)
        by_channel = annotate_placeholders(store)
        out = os.path.join(store.dir, "contact-sheet-web.html")
        # Rendered to a separate file from the standalone contact-sheet.html,
        # precisely so the served copy can carry links the portable copy must
        # not have.
        # Not embedded: thumbnails are served from /run/<id>/thumbs/ so the
        # page streams instead of shipping several MB of base64 up front.
        render_sheet(by_channel, store, out, embed=False, served=True)
        with open(out, encoding="utf-8") as f:
            doc = f.read()
        doc = doc.replace('"thumbs/', f'"/run/{urllib.parse.quote(run_id)}/thumbs/')
        self._send(doc)

    def _dropped_urls(self, store):
        """{channel_key: {url: failure count}} for the whole run.

        One system-events fetch (cached, see _cached_failed_streams) covers
        every channel; only the per-stream URL lookups are per-channel, and
        only for channels that have actually failed over at all -- which on
        a real lineup is a small minority.
        """
        if settings_mod.read(self.root).get("failover_display", "info") == "off":
            return {}
        try:
            client = client_from_spec(prov["spec"])
            failed = self._cached_failed_streams(client, client.base)
        except Exception:
            return {}
        if not failed:
            return {}
        out = {}
        for w in (store.read_wantlist().get("wanted") or []):
            dch = w.get("dispatcharr") or {}
            name = dch.get("channel_name")
            if not name or name not in failed:
                continue
            urls = {}
            for sid, n in failed[name].items():
                url = self._cached_stream_url(client, sid)
                if url:
                    urls[url] = n
            if urls:
                out[w["key"]] = urls
        return out

    # The audit itself, not just the Dispatcharr calls underneath it, is
    # what actually needs caching -- caught live: the network calls were
    # already cached, but resolving every channel against every guide
    # still meant a fuzzy scan over a several-thousand-entry XMLTV file,
    # repeated for up to 159 channels, synchronously, on every single
    # curate page load. Measured cost: sustained ~60% CPU and the page
    # itself timing out. Same mistake as the EPG index rebuild earlier
    # this session, one layer further down -- caching the fetch was not
    # enough when the COMPUTE built on top of it was the actual cost.
    _mismatch_cache = {}   # (run_id, base) -> (computed_at, result)
    MISMATCH_TTL = 300

    def _epg_mismatches(self, store):
        prov = next((p for p in providers_mod.list_all(self.root)
                    if p.get("scheme") == "dispatcharr"), None)
        if not prov:
            return {}
        base = base_url_of(prov["spec"])
        ck = (store.run_id, base)
        now = time.time()
        hit = self._mismatch_cache.get(ck)
        if hit and (now - hit[0]) < self.MISMATCH_TTL:
            return hit[1]
        result = self._compute_epg_mismatches(store, prov)
        self._mismatch_cache[ck] = (now, result)
        return result

    def _compute_epg_mismatches(self, store, prov):
        """{channel_key: {dispatcharr: {...}, probarr: {...}}} for every
        pushed channel where Dispatcharr's live EPG link disagrees with
        what probarr itself resolves as correct.

        Matched by channel NUMBER, not the uuid recorded at import time --
        proved necessary live: a channel pushed straight from probarr,
        never pulled back in via Import, has no stored uuid at all despite
        genuinely existing in Dispatcharr under that number. Number is
        exactly what the export itself uses as identity, so it is never
        stale in the way a one-off import snapshot can be.

        One bulk fetch of Dispatcharr's channels and one of its current
        programmes (both cached) cover every channel in the run; nothing
        here is a per-channel request. See _epg_mismatches() for why the
        RESULT of this is also cached, not just these two fetches.
        """
        try:
            prov = next((p for p in providers_mod.list_all(self.root)
                        if p.get("scheme") == "dispatcharr"), None)
            if not prov:
                return {}
            client = client_from_spec(prov["spec"])
            by_number = {c.get("channel_number"): c for c in client.channels()
                        if c.get("channel_number") is not None}
            programs = self._cached_current_programs(client)
        except Exception:
            return {}
        if not by_number:
            return {}

        norm = self._norm()
        sources = epgsources_mod.list_all(self.root)
        sel = store.read_selection() or {}
        inherited = self._inherited(store)
        out = {}
        for w in (store.read_wantlist().get("wanted") or []):
            num = w.get("number")
            if num is None:
                continue
            dch = by_number.get(float(num))
            if not dch:
                continue
            prog = programs.get(dch.get("uuid"))
            if not prog:
                continue   # Dispatcharr has nothing scheduled -- not a mismatch, just unknown

            # What probarr itself would resolve, by the same explicit-or-
            # default rule the EPG check panel and the export both use.
            wsel = sel.get(w["key"]) or inherited.get(w["key"]) or {}
            pick = wsel.get("epg_source")
            ordered = ([s for s in sources if s["name"] == pick] if pick
                      else []) + [s for s in sources if not pick or s["name"] != pick]
            name = w.get("name") or w.get("key")
            override_source = wsel.get("epg_channel_source")
            override_id = wsel.get("epg_channel_id")
            correct = None
            for src in ordered:
                try:
                    g = epgcheck_mod._indexed_guide(src["url"], norm, self.root)
                    # A manual pick from Check EPG's search wins outright for
                    # the source it was made against -- it exists precisely
                    # because resolve() guessed wrong.
                    cid = (override_id if src["name"] == override_source
                           and override_id in g.display_names
                           else g.resolve(w.get("tvg_id") or None, name, norm))
                except Exception:
                    continue
                if cid:
                    names = g.display_names.get(cid) or []
                    correct = {"source": src["name"], "guide_id": cid,
                              "guide_name": names[0] if names else cid}
                    break
            if not correct:
                continue   # probarr itself has no opinion -- nothing to compare against

            dispatcharr_tvg = prog.get("tvg_id") or ""
            # tvg-ids are compared case-insensitively -- the same real guide
            # channel routinely shows up with different casing between
            # Dispatcharr's own EPG store and a source's XMLTV (e.g.
            # "bbcthree.uk" vs "BBCThree.uk"), which is not a real mismatch.
            if dispatcharr_tvg and dispatcharr_tvg.lower() != correct["guide_id"].lower():
                out[w["key"]] = {
                    "dispatcharr": {"title": prog.get("title") or "",
                                    "guide_id": dispatcharr_tvg},
                    "probarr": correct,
                }
        return out

    def _curate(self, run_id):
        store = RunStore(self.root, run_id)
        # Checked against run.json, NOT results.jsonl -- a run whose wantlist
        # genuinely matched zero streams never writes a results file at all
        # (there is nothing to append), which made a run that completed
        # cleanly and found nothing indistinguishable from a run_id that was
        # never started: both hit this check and returned a bare 404. run.json
        # is written as the very first thing a run does, before anything can
        # fail, so its absence is the real "no such run" signal.
        if not os.path.exists(store.meta_path):
            return self._send("<h1>no such run</h1>", code=404)
        # Warm the group list while the page is being read. Even reused, the
        # first fetch behind a fresh token costs about a second, and the
        # curator hits it the moment they file their first channel -- doing
        # it now means the modal is never the thing they wait on. Failures
        # are irrelevant here: the real call still handles its own errors.
        self._prefetch_groups(store)
        by_channel = annotate_placeholders(store)
        guide_present = bool(store.read_meta().get("epg"))
        self._send(curate.render(by_channel, store, guide_present,
                                 self._inherited(store), self._dropped_urls(store),
                                 self._epg_mismatches(store)))

    def _lineups(self):
        """Saved lineups, each annotated with the runs made from it.

        The list page is the only place the relationship between a lineup
        and its runs is visible at all -- run.json records which lineup it
        belongs to, but nothing ever read that back, so a lineup looked
        like configuration with no history attached.
        """
        runs_by_lineup = {}
        for r in RunStore.list_runs(self.root):
            if r.get("lineup"):
                runs_by_lineup.setdefault(r["lineup"], []).append(r)
        out = []
        for lu in lineups_mod.list_all(self.root):
            rs = runs_by_lineup.get(lu["name"], [])
            # list_runs() is already newest-first by directory name, which
            # is the timestamp these are named after.
            last = next((r.get("last_completed") for r in rs
                         if r.get("last_completed")), None)
            out.append({**lu, "runs": [r["run_id"] for r in rs],
                       "last_run": (time.strftime("%d %b %H:%M",
                                                  time.localtime(last))
                                    if last else None)})
        return out

    def _epg_fallback_logo(self, name, tvg_id):
        """A logo URL from whichever saved EPG source best matches `name`,
        for a channel the M3U itself gave no tvg-logo for. None (not an
        error) when there are no saved sources, none of them match, or the
        winning match's source carries no icon at all -- all real,
        unremarkable cases, not something worth logging or interrupting an
        export over. Best-effort throughout: any exception here (a
        malformed guide, a source URL that stopped resolving) means "no
        logo available", never a broken export.
        """
        try:
            sources = epgcheck_mod.check_all(self.root, name, tvg_id, self._norm())
            winner = epgcheck_mod.consensus_winner(sources, root=self.root)
            return (winner or {}).get("logo") or ""
        except Exception:
            return ""

    def _inherited(self, store):
        """Per-channel decisions this run inherits from its lineup, if any.
        Empty dict when the run has no lineup -- unconfigured runs behave
        exactly as they did before lineups existed."""
        return lineups_mod.preferences(self.root, store.read_meta().get("lineup"))

    def _resolve_curated(self, store, report_dropped=False):
        """Curated channels ready to export: number, title, primary + fallback.

        Shared by every export format. Falls back to the automatic ranking
        for any channel not yet reviewed, so an export is useful before
        curation is finished rather than only after -- the curator's explicit
        picks simply override the auto-pick wherever they exist.

        `report_dropped` additionally returns the channels this export is
        NOT carrying because the provider no longer offers a usable stream
        for them -- returns (curated, dropped) instead of just curated.

        That exists because of a real reported bug: a channel the provider
        has stopped carrying was skipped here by a bare `continue`, so it
        appeared nowhere in the push preview while Dispatcharr quietly kept
        serving the old channel pointing at a dead stream. Never deleting
        anything automatically is deliberate (see dispatcharr_export.py's
        own docstring on why); giving no signal at all was not. A channel
        deliberately excluded by the curator is NOT reported -- that is a
        decision, not a provider failure.
        """
        by_channel = annotate_placeholders(store)
        inherited = self._inherited(store)
        payload = curate.build_payload(by_channel, store, False, inherited)
        sel = {**inherited, **(store.read_selection() or {})}
        # The guide id, for exports that carry one. An explicit id from the
        # wantlist wins -- it was written precisely because the automatic
        # match was wrong -- with the id the provider advertised as the
        # fallback. Without this the M3U export named every channel and
        # matched none of them to a guide.
        tvg = {w.get("key"): w.get("tvg_id") for w in
               (store.read_wantlist().get("wanted") or []) if w.get("tvg_id")}
        for r in store.load():
            if r.get("tvg_id") and not tvg.get(r.get("channel_key")):
                tvg[r["channel_key"]] = r["tvg_id"]
        out, dropped = [], []
        for ch in payload["channels"]:
            s = sel.get(ch["key"]) or {}
            cands = ch["candidates"]
            if s and not s.get("include", True):
                continue     # an explicit decision, never reported as dropped
            if not cands:
                dropped.append({"key": ch["key"], "number": ch["number"],
                               "name": ch["title"],
                               "reason": "the provider no longer carries a "
                                         "stream for this channel"})
                continue
            # An ordered list of streams, not a primary and a fallback.
            # Dispatcharr stores a channel as exactly that -- an ordered
            # streams array it fails over down -- so the two-slot model was
            # a narrowing probarr imposed on itself, and it meant a third
            # good candidate had nowhere to go. primary/fallback are still
            # produced below, as the first two, so every existing caller
            # keeps working.
            picked = [next((c for c in cands if c["id"] == rk), None)
                      for rk in (s.get("streams") or [])]
            picked = [c for c in picked if c]
            if not picked:
                legacy = [s.get("primary"), s.get("fallback")]
                picked = [c for rk in legacy if rk
                          for c in cands if c["id"] == rk]
            if not picked:
                # Real fallback depth, not just one guess: an uncurated
                # channel used to export a single stream, so the moment it
                # failed there was nothing behind it. Candidates are already
                # ranked best-first, so the top few playable ones become a
                # genuine failover chain -- and every one beyond the first is
                # also a chance to learn, from Dispatcharr's own failover log,
                # whether it actually holds up in real use.
                picked = [c for c in cands
                         if c["status"] in ("ok", "dirty")][:AUTO_FALLBACK_DEPTH]
            if not picked:
                # Candidates exist, but none of them are playable -- as
                # invisible on the push as having none at all, and worth
                # the same signal.
                dropped.append({"key": ch["key"], "number": ch["number"],
                               "name": ch["title"],
                               "reason": "none of this channel's streams are "
                                         "playable any more"})
                continue
            primary = picked[0]
            # A channel with no NUMBER is not exportable, and pushing it
            # anyway was actively destructive: Dispatcharr identifies a
            # channel by its number, so one arriving without gets whatever
            # is free -- 1, 2, 3, 4 -- named after the stream rather than
            # the channel, landing at the top of the lineup and looking
            # like the numbering had broken. Confirmed live: seven channels
            # had probe results but no wantlist entry (the wantlist is
            # where number and name come from), and four of them were
            # pushed into a real lineup that way.
            if ch["number"] is None:
                # Reported for the same reason the two skips above are: a
                # channel that silently appears in neither the playlist nor
                # the push preview is indistinguishable from one nobody
                # asked for.
                dropped.append({"key": ch["key"], "number": None,
                               "name": ch["title"],
                               "reason": "no channel number -- add one in the "
                                         "wantlist before this can be exported"})
                continue
            fallback = picked[1] if len(picked) > 1 else None
            chan_tvg_id = tvg.get(ch["key"], "")
            # An explicit logo picked in the logo browser is a deliberate
            # curator decision -- the entire point of building it was to let
            # a human override an automatic pick that's wrong or missing, so
            # it outranks both the provider's own tvg-logo and the EPG
            # fallback below, not just the EPG fallback.
            logo_url = s.get("logo_override") or primary.get("logo", "")
            if not logo_url:
                # The M3U itself supplied nothing -- fall back to whichever
                # saved EPG source's own icon best agrees with this
                # channel's name, per the same word-overlap consensus used
                # everywhere else EPG sources are compared. Never the other
                # way around: a provider-supplied logo is kept even when a
                # trusted EPG source disagrees, since providers' own icons
                # are usually the more deliberately-chosen of the two, and
                # this is only meant to fill a genuine gap.
                logo_url = self._epg_fallback_logo(ch["title"], chan_tvg_id)
            out.append({"key": ch["key"], "number": ch["number"], "name": ch["title"],
                       "logo_url": logo_url,
                       # A per-channel group set in Curate beats both the
                       # export form's group field and the channel's
                       # existing group -- it is an explicit decision about
                       # THIS channel, which is more specific than either.
                       "group": s.get("group"),
                       "tvg_id": chan_tvg_id,
                       "streams": picked,
                       "primary": primary, "fallback": fallback})
        # A plain list by default, so every existing caller (three export
        # formats and the push itself) is untouched by this addition.
        return (out, dropped) if report_dropped else out

    def _export_m3u(self, run_id):
        store = RunStore(self.root, run_id)
        # Every sibling export/read endpoint guards on this; without it,
        # writing the playlist into a run directory that does not exist
        # raised FileNotFoundError straight out of the handler and dropped
        # the connection. Latent until RunStore stopped creating
        # directories on read, at which point it became reachable with any
        # unknown run id.
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        curated = self._resolve_curated(store)
        # Everything the curator decided, carried into the file: the
        # per-channel group (which the Dispatcharr push already honoured
        # while this path silently dropped it), the logo, and the guide id.
        # Exporting a bare name and URL made the "streamlined" playlist
        # worse in a player than the raw one it was distilled from -- no
        # icons, and nothing matching the guide.
        rows = [(ch["number"], ch["name"], ch.get("group") or "probarr",
                ch.get("logo_url") or "",
                # Falls back to a stable synthesised id rather than none, so
                # every channel lines up with export.xmltv -- an id only the
                # playlist has is no more use than no id at all.
                ch.get("tvg_id") or f"probarr.{ch['key'].lower()}",
                self._real_url(store, ch["primary"]["stream_id"]))
                for ch in curated]
        tmp = os.path.join(store.dir, "export.m3u")
        m3u.write(rows, tmp)
        with open(tmp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "audio/x-mpegurl")
        self.send_header("Content-Disposition",
                         f'attachment; filename="probarr-{run_id}.m3u"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _export_xmltv(self, run_id):
        """A guide for exactly the curated channels, keyed to the M3U.

        Without this an exported playlist arrives in a player as a wall of
        names: probarr knew which guide each channel matched, including a
        per-channel override chosen in Curate, and had no way to hand that
        knowledge over. Channel ids are the same tvg-ids export.m3u writes,
        so the two files line up with no mapping step.
        """
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send("<h1>no such run</h1>", code=404)
        curated = self._resolve_curated(store)
        sel = {**self._inherited(store), **(store.read_selection() or {})}
        sources = epgsources_mod.list_all(self.root)
        norm = self._norm()
        guides = {}

        def guide_for(url):
            if url not in guides:
                try:
                    guides[url] = epgcheck_mod.load_cached(
                        url, window_hours=48, root=self.root)
                except Exception:
                    guides[url] = None
            return guides[url]

        def resolve(ch):
            # A source chosen for THIS channel wins outright -- it was
            # chosen precisely because the automatic answer was wrong. Any
            # other saved source is then tried in order, first match wins,
            # which is the same rule the EPG check panel shows.
            chsel = sel.get(ch["key"]) or {}
            pick = chsel.get("epg_source")
            override_source = chsel.get("epg_channel_source")
            override_id = chsel.get("epg_channel_id")
            ordered = ([s for s in sources if s["name"] == pick]
                       if pick else []) + [s for s in sources
                                           if not pick or s["name"] != pick]
            for src in ordered:
                g = guide_for(src["url"])
                if not g:
                    continue
                # Indexed once per (source, aliases), not once per channel
                # -- this loop runs over the whole exported lineup.
                g = epgcheck_mod._indexed_guide(src["url"], norm, self.root)
                # A manual pick from Check EPG's search wins outright for the
                # source it was made against.
                cid = (override_id if src["name"] == override_source
                       and override_id in g.display_names
                       else g.resolve(ch.get("tvg_id") or None, ch["name"], norm))
                if cid:
                    return g, cid
            return None, None

        rows = [{"id": ch.get("tvg_id") or f"probarr.{ch['key'].lower()}",
                "name": ch["name"], "logo": ch.get("logo_url") or "",
                "key": ch["key"], "tvg_id": ch.get("tvg_id") or ""}
                for ch in curated]
        text, stats = xmltv_mod.build(rows, resolve)
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="probarr-{run_id}.xml"')
        self.send_header("X-Probarr-Matched",
                         f"{stats['matched']}/{stats['channels']} channels, "
                         f"{stats['programmes']} programmes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # A push in progress this long ago with no terminal state is treated as
    # abandoned (its thread died with the container, e.g. a redeploy) rather
    # than genuinely still running -- otherwise a crash mid-push would wedge
    # the run's push status at "running" forever and permanently refuse any
    # retry. 90s is generous against the per-channel pace actually observed
    # (well under 1s/channel for both the resolve and upsert phases).
    PUSH_STALE_SECONDS = 90

    def _export_dispatcharr(self, run_id, body):
        """Kick off a background push of the curated selection into a
        Dispatcharr instance, returning immediately.

        The target is a saved Provider of scheme dispatcharr -- deliberately
        the SAME concept as a source, not a separate "export destination" to
        configure: if the run was itself sourced from a saved Dispatcharr
        provider, pushing back into that same instance needs no extra setup
        at all, which is the common case this exists for.

        Runs in a background thread rather than blocking this request:
        a ~150-channel push (each needing 1-2 Dispatcharr API calls to
        resolve/create a stream, then create/update the channel) previously
        ran synchronously inside the HTTP request, which meant closing the
        tab, a reload, or the browser's own request timeout lost all
        visibility into whether it was still going, had finished, or had
        silently died -- there was no way to tell from outside that one
        browser tab. Progress now lives in store.push_status(), pollable via
        GET .../export/dispatcharr/status from any client, and survives a
        page reload because it is written to disk on every channel, not held
        only in the request's local variables.
        """
        provider_name = (body.get("provider") or "").strip()
        fallback_mode = body.get("fallback_mode") or ""
        if fallback_mode not in ("native", "separate"):
            return self._send(
                '{"error":"fallback_mode must be \\"native\\" or \\"separate\\""}',
                "application/json", 400)
        prov = providers_mod.get(self.root, provider_name)
        if not prov:
            return self._send('{"error":"provider not found"}', "application/json", 404)
        if prov.get("scheme") != "dispatcharr":
            return self._send(
                '{"error":"chosen provider is not a Dispatcharr connection"}',
                "application/json", 400)

        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        curated = self._resolve_curated(store)
        # An optional single-channel scope -- pushing one just-changed
        # channel (a new stream pick, a new EPG choice) shouldn't require
        # re-processing the whole curated set, and does not need the
        # background-thread/polling machinery below at any real scale: even
        # including EPG resolution, one channel finishes in a couple of
        # seconds, so it rides the same push_status flow for consistency
        # rather than needing a second, synchronous code path.
        channel_key = (body.get("channel_key") or "").strip()
        if channel_key:
            curated = [c for c in curated if c["key"] == channel_key]
            if not curated:
                return self._send(
                    '{"error":"channel not found, or not currently included"}',
                    "application/json", 404)
        if not curated:
            return self._send('{"error":"nothing selected to export"}',
                              "application/json", 400)

        existing = store.read_push_status()
        if existing and existing.get("state") == "running" \
                and time.time() - existing.get("updated", 0) < self.PUSH_STALE_SECONDS:
            return self._send(json.dumps({"error": "a push is already in progress",
                                          "status": existing}),
                              "application/json", 409)

        # Falls back to whatever group name a push into THIS PROVIDER last
        # actually used -- deliberately attached to the provider, not the
        # run: without this, a later push (especially a single-channel one,
        # where retyping the group name every time is real friction) lands
        # in a brand new, different group the instant the field is left
        # None (not a computed fallback string) unless the field was
        # actually typed in -- push()/upsert() then leaves any EXISTING
        # channel's group untouched, exactly like updating any other field
        # only touches what changed. Confirmed live TWICE that resolving a
        # fallback string here unconditionally is wrong: once because
        # leaving the field blank silently relocated a channel out of its
        # real group on a later push within the same run, and again across
        # two different probarr runs of what the operator considers the
        # same conceptual lineup. default_group_name is still needed for a
        # genuinely NEW channel with nothing to preserve -- the provider's
        # own remembered group name is the sane choice there (see
        # set_last_group_name()'s docstring), not this run's id.
        # Defaults ON: a push that moves the last channel out of a group
        # leaving the empty shell behind is never what was wanted, and the
        # prune is scoped to groups this push itself vacated.
        prune_empty = body.get("prune_empty_groups", True)
        group_name = (body.get("group_name") or "").strip() or None
        # Remembered on the way in, not on success: these are the answers to
        # "how do you push", and they are the same answers next time whether
        # or not this particular push happened to work.
        try:
            settings_mod.write(self.root, {
                **settings_mod.read(self.root),
                "push_provider": provider_name,
                "push_fallback": fallback_mode,
                "push_prune": bool(prune_empty)})
        except Exception:
            pass
        default_group_name = prov.get("last_group_name") or f"probarr ({run_id})"
        store.write_push_status({"state": "running", "phase": "resolving",
                                 "done": 0, "total": len(curated),
                                 "started": time.time()})
        threading.Thread(target=self._run_export,
                         args=(store, prov, provider_name, curated,
                               fallback_mode, group_name, default_group_name,
                               prune_empty,
                               # Only a FULL push applies staged removals.
                               # A single-channel push touches exactly the
                               # channel asked for; quietly destroying others
                               # alongside it is the surprise the whole
                               # preview-then-push model exists to prevent.
                               not channel_key),
                         daemon=True).start()
        self._send(json.dumps({"ok": True, "started": True,
                               "total": len(curated)}), "application/json")

    def _resolve_epg_overrides(self, store, client, curated):
        """({channel_key: Dispatcharr epg_data_id}, {touched Dispatcharr epg
        source ids}) for every curated channel whose curator explicitly
        picked an EPG source in Curate's "Check EPG" modal (see epgcheck.py
        / the epg_source field in selection.json).

        Ensures the chosen source exists in DISPATCHARR too (a probarr-saved
        source is only useful for the live comparison in Curate otherwise --
        see get_or_create_epg_source()'s docstring), then resolves this
        specific channel against that specific source's guide to find the
        matching EPGData row. A channel with no preference, or where
        resolution fails for any reason, is simply left out of the returned
        dict -- push() then falls back to Dispatcharr's own generic
        auto-match for it, exactly as before this feature existed.

        The second return value matters just as much as the first: setting
        epg_data_id via a direct channel PATCH only creates the FK link --
        confirmed live, it does NOT make Dispatcharr fetch/parse that
        channel's actual <programme> data, unlike its own "Match EPG" UI
        action. The exact same gotcha bit this project's original
        channel-sync.py pipeline (see its notes on
        dispatch_program_refresh_for_epg_ids). The caller re-imports each
        touched source after the push actually lands, which is what makes
        Dispatcharr treat these channels as newly "mapped" and go fetch
        their programmes -- without it, the guide silently keeps showing
        nothing (or stale data) despite the link being genuinely correct.
        """
        sel = store.read_selection()
        by_channel = annotate_placeholders(store)
        norm = self._norm()
        overrides = {}
        touched_sources = set()
        for ch in curated:
            chsel = sel.get(ch["key"]) or {}
            pref = chsel.get("epg_source")
            if not pref:
                continue
            src = epgsources_mod.get(self.root, pref)
            if not src:
                continue
            records = by_channel.get(ch["key"])
            if not records:
                continue
            top = rank_mod.rank(records)[0]
            override_id = (chsel.get("epg_channel_id")
                          if chsel.get("epg_channel_source") == pref else None)
            try:
                ds_source_id = client.get_or_create_epg_source(src["name"], src["url"])
                g = epgcheck_mod._indexed_guide(src["url"], norm, self.root)
                # A manual pick from Check EPG's search wins outright -- it
                # exists precisely because resolve() guessed wrong.
                cid = (override_id if override_id and override_id in g.display_names
                       else g.resolve(top.get("tvg_id") or "", ch.get("name"), norm))
                if not cid:
                    continue
                epgdata_id = client.epgdata_map().get((ds_source_id, cid))
                if epgdata_id:
                    overrides[ch["key"]] = epgdata_id
                    touched_sources.add(ds_source_id)
            except Exception:
                continue  # fall back to Dispatcharr's own auto-match for this one
        return overrides, touched_sources

    def _run_export(self, store, prov, provider_name, curated, fallback_mode,
                    group_name, default_group_name, prune_empty=True,
                    apply_removals=True):
        """The actual push, run off the request thread. See _export_dispatcharr."""
        # A push is the one operation that creates a group or empties one, so
        # the cached group list is dropped here rather than left to expire.
        self._forget_remote_groups()
        try:
            client = client_from_spec(prov["spec"])
            meta = store.read_meta()
            # A candidate's stream can be reused directly ONLY when it
            # already belongs to THIS target instance -- checked twice,
            # because either signal alone can be wrong: provider_name is
            # authoritative but only recorded for runs started via the New
            # Run form, and comparing host strings is a reasonable fallback
            # for CLI-driven runs but could in principle match two unrelated
            # instances on the same host.
            same_instance = (
                (meta.get("provider_name") and meta.get("provider_name") == provider_name)
                or (str(meta.get("source", "")).startswith("dispatcharr://")
                    and base_url_of(meta["source"]) == base_url_of(prov["spec"])))

            def resolve_stream_id(cand):
                real_url = self._real_url(store, cand["stream_id"])
                if same_instance and str(cand["stream_id"]).startswith("dispatcharr:"):
                    return int(str(cand["stream_id"]).split(":", 1)[1])
                return client.get_or_create_custom_stream(cand["name"], real_url)

            # Staged removals go FIRST, so that push()'s prune_empty step
            # can then tidy a group the deletion just emptied -- doing it
            # afterwards would leave the group behind until the next push.
            deleted = self._apply_removals(store, client) if apply_removals else []

            epg_overrides, touched_epg_sources = self._resolve_epg_overrides(
                store, client, curated)

            channels = []
            for i, ch in enumerate(curated):
                channels.append({
                    "number": ch["number"], "name": ch["name"],
                    "logo_url": ch["logo_url"],
                    "group": ch.get("group"),
                    # The whole ordered list. primary/fallback are still
                    # sent so an older export path reading only those two
                    # behaves exactly as before.
                    "streams": [{"stream_id": resolve_stream_id(c)}
                                for c in ch.get("streams") or [ch["primary"]]],
                    "primary": {"stream_id": resolve_stream_id(ch["primary"])},
                    "fallback": ({"stream_id": resolve_stream_id(ch["fallback"])}
                                if ch["fallback"] else None),
                    "epg_data_id": epg_overrides.get(ch["key"]),
                })
                store.write_push_status({"state": "running", "phase": "resolving",
                                         "done": i + 1, "total": len(curated),
                                         "started": store.read_push_status()["started"]})

            def on_progress(done, total, name):
                store.write_push_status({"state": "running", "phase": "pushing",
                                         "done": done, "total": total,
                                         "current": name,
                                         "started": store.read_push_status()["started"]})

            log_lines = []
            # Every custom stream this push creates lands in Dispatcharr's
            # ONE shared, easy-to-overlook "custom" M3U account -- see
            # enforce_custom_stream_limit()'s docstring for the real
            # incident this closes (that account defaulting to unlimited
            # silently defeated a provider's genuine 1-connection cap).
            # This run's own concurrency is the only connection limit
            # probarr actually knows for certain, since it is what the
            # provider was verified against.
            client.enforce_custom_stream_limit(
                store.read_meta().get("concurrency"), log=log_lines.append)
            # If Dispatcharr ALSO has a real M3U account for this exact
            # provider (see docs/design/per-provider-m3u-accounts.md), keep
            # its own max_streams in step too -- that account's limit is
            # what Dispatcharr actually enforces against Live TV playback
            # AND VOD together, which the shared "custom" account's limit
            # above can never do since a custom stream is invisible to that
            # accounting regardless of which account it's filed under. A
            # no-op when no such account exists yet.
            client.enforce_provider_stream_limit(
                prov["spec"], store.read_meta().get("concurrency"),
                log=log_lines.append)
            summary = dispatcharr_export.push(
                client, channels, group_name=group_name,
                default_group_name=default_group_name,
                fallback_mode=fallback_mode, log=log_lines.append,
                progress_cb=on_progress, prune_empty_groups=prune_empty)
            # Must happen AFTER push() actually writes epg_data_id to
            # Dispatcharr, not before -- the import task decides which
            # channels count as "mapped" (and therefore worth fetching
            # programmes for) by querying live Channel state at the moment
            # it runs. See _resolve_epg_overrides()'s docstring for why this
            # step exists at all.
            for source_id in touched_epg_sources:
                try:
                    client.api("POST", "/api/epg/import/", {"id": source_id})
                    log_lines.append(f"  re-imported EPG source {source_id} "
                                     f"to fetch programmes for newly-mapped channel(s)")
                except Exception as e:
                    log_lines.append(f"  EPG source {source_id} re-import failed: {e}")
            summary["log"] = log_lines
            summary["deleted"] = deleted
            summary["same_instance"] = same_instance
            # Only when a group was EXPLICITLY given -- that is a real
            # decision to update the default for next time. A blank field
            # changed nothing about any existing channel's group (see
            # push()'s docstring), so there is nothing new worth
            # remembering; default_group_name is already what gets reused
            # for brand-new channels either way. Remembered on SUCCESS only,
            # so a failed attempt (a typo'd name, a mid-push error) never
            # becomes the new default -- and against the PROVIDER, not this
            # run, so a later push from a different probarr run of the same
            # conceptual lineup still finds it.
            if group_name:
                providers_mod.set_last_group_name(self.root, prov["name"], group_name)
            store.write_push_status({"state": "done", "phase": "done",
                                     "done": len(curated), "total": len(curated),
                                     "started": store.read_push_status()["started"],
                                     "summary": summary})
        except Exception as e:
            prev = store.read_push_status() or {}
            store.write_push_status({"state": "error", "phase": "error",
                                     "done": prev.get("done", 0),
                                     "total": prev.get("total", len(curated)),
                                     "started": prev.get("started", time.time()),
                                     "error": str(e)[:400]})

    def _apply_removals(self, store, client):
        """Delete the channels staged by Remove, and forget each one as it
        goes.

        Cleared per channel, immediately, rather than in a batch at the end:
        a failure partway through must not re-delete what already succeeded
        on the next push, nor forget what did not. Same reasoning as the
        append-per-probe rule in store.py -- the expensive failure is losing
        the record of work already done.

        A channel already gone from Dispatcharr (deleted by hand there, or
        by an earlier push that failed after the delete but before the
        clear) is treated as success, because the requested end state is
        exactly what is true.
        """
        out = []
        pending = store.read_removals()
        if not pending:
            return out
        existing = {c.get("channel_number"): c for c in client.channels()}
        for row in pending:
            number = row.get("number")
            target = existing.get(float(number)) if number is not None else None
            try:
                if target:
                    client.api("DELETE",
                               f"/api/channels/channels/{target['id']}/")
                    out.append({"number": number, "name": row.get("name"),
                               "id": target["id"]})
                else:
                    out.append({"number": number, "name": row.get("name"),
                               "id": None, "note": "already gone"})
                store.clear_removal(row.get("key"))
            except Exception as e:
                out.append({"number": number, "name": row.get("name"),
                           "error": str(e)[:200]})
        return out

    def _export_plan(self, run_id, body):
        """Preview what a push would change, without changing anything.

        Deliberately resolves stream ids READ-ONLY: an existing custom
        stream is looked up by URL, and one that doesn't exist yet is
        reported as such rather than created. Previewing must not have side
        effects, or it becomes as consequential as the thing it previews.
        """
        provider_name = (body.get("provider") or "").strip()
        prov = providers_mod.get(self.root, provider_name)
        if not prov or prov.get("scheme") != "dispatcharr":
            return self._send('{"error":"provider not found"}', "application/json", 404)
        store = RunStore(self.root, run_id)
        if not os.path.exists(store.results_path):
            return self._send('{"error":"no such run"}', "application/json", 404)
        curated, dropped = self._resolve_curated(store, report_dropped=True)
        channel_key = (body.get("channel_key") or "").strip()
        if channel_key:
            curated = [c for c in curated if c["key"] == channel_key]
            dropped = [c for c in dropped if c["key"] == channel_key]
        if not curated:
            return self._send('{"error":"nothing selected"}', "application/json", 400)

        try:
            client = client_from_spec(prov["spec"])
            url_map = client.stream_url_map()
            meta = store.read_meta()
            same_instance = (
                (meta.get("provider_name") and meta.get("provider_name") == provider_name)
                or (str(meta.get("source", "")).startswith("dispatcharr://")
                    and base_url_of(meta["source"]) == base_url_of(prov["spec"])))

            def peek_stream_id(cand):
                if same_instance and str(cand["stream_id"]).startswith("dispatcharr:"):
                    return int(str(cand["stream_id"]).split(":", 1)[1])
                # Sentinel for "would be created" -- never equal to a real
                # id, so _decide() correctly reports it as a change.
                return url_map.get(self._real_url(store, cand["stream_id"]), "new")

            channels = [{
                "number": ch["number"], "name": ch["name"],
                "logo_url": ch["logo_url"],
                # Carried through explicitly: _resolve_curated() attaches
                # the curator's per-channel group, and rebuilding the dict
                # here without it silently dropped the whole feature --
                # the preview and push both fell back to the blanket group.
                "group": ch.get("group"),
                "streams": [{"stream_id": peek_stream_id(c)}
                            for c in ch.get("streams") or [ch["primary"]]],
                "primary": {"stream_id": peek_stream_id(ch["primary"])},
                "fallback": ({"stream_id": peek_stream_id(ch["fallback"])}
                            if ch["fallback"] else None),
            } for ch in curated]

            group_name = (body.get("group_name") or "").strip() or None
            default_group_name = prov.get("last_group_name") or f"probarr ({run_id})"
            result = dispatcharr_export.plan(
                client, channels, group_name=group_name,
                default_group_name=default_group_name,
                fallback_mode=body.get("fallback_mode") or "native")
            # Both blocks below need to know what is currently live in the
            # target, so it is fetched at most once for the pair.
            by_number = None
            if dropped or not channel_key:
                by_number = {c.get("channel_number"): c
                             for c in client.channels()}

            def present(number):
                return (float(number) in by_number
                        if number is not None and by_number is not None else False)

            # Staged deletions belong in the same diff as everything else --
            # a preview that shows six updates while quietly omitting the
            # channel about to be destroyed is worse than no preview.
            # Only on a full push: a single-channel push touches just that
            # channel, and silently deleting others alongside it would be
            # the exact surprise this preview exists to prevent.
            if not channel_key:
                result["removals"] = [
                    {"number": r.get("number"), "name": r.get("name"),
                     "present": present(r.get("number"))}
                    for r in store.read_removals()]
            # Channels this push is NOT carrying because the provider has
            # stopped offering a usable stream. Reported, never acted on:
            # whatever is live in Dispatcharr stays exactly as it is, but
            # the preview now says so instead of leaving the channel to rot
            # there unmentioned. `present` distinguishes "still live in
            # Dispatcharr, now unbacked" from "already gone anyway".
            if dropped:
                result["dropped"] = [{**d, "present": present(d.get("number"))}
                                     for d in dropped]
        except Exception as e:
            return self._send(json.dumps({"error": str(e)[:400]}),
                              "application/json", 502)
        self._send(json.dumps(result), "application/json")

    def _export_dispatcharr_status(self, run_id):
        store = RunStore(self.root, run_id)
        status = store.read_push_status()
        if not status:
            return self._send('{"state":"none"}', "application/json")
        self._send(json.dumps(status), "application/json")

    def _real_url(self, store, stream_id):
        """Unredacted URL for export. Never used for display."""
        if getattr(self, "_url_cache_run", None) != store.run_id:
            self._url_cache = {}
            self._url_cache_run = store.run_id
            for r in store.load():
                self._url_cache.setdefault(r["stream_id"], r.get("url") or
                                           r.get("url_redacted", ""))
        return self._url_cache.get(stream_id, "")

    def _file(self, run_id, rest):
        # Resolve inside the run directory and refuse anything that escapes it
        # -- the run id and filename both arrive from the URL.
        store = RunStore(self.root, run_id)
        if not rest or rest[0] not in ("thumbs", "frames", "crops", "clips", "watermarks"):
            return self._send("forbidden", "text/plain", code=403)
        name = posixpath.normpath("/".join(rest)).lstrip("/")
        base = os.path.realpath(store.dir)
        target = os.path.realpath(os.path.join(base, name))
        if not target.startswith(base + os.sep):
            return self._send("forbidden", "text/plain", code=403)
        if not os.path.isfile(target):
            return self._send("not found", "text/plain", code=404)
        # A URL carrying ?v=<capture time> refers to one specific capture and
        # can be cached hard; without it the image may be overwritten by a
        # re-probe at any moment, so it must be revalidated every time.
        versioned = "v=" in (urllib.parse.urlparse(self.path).query or "")
        cache = ("public, max-age=31536000, immutable" if versioned
                 else "no-store, must-revalidate")
        ctype = "video/mp4" if target.endswith(".mp4") else "image/jpeg"
        size = os.path.getsize(target)

        if ctype == "video/mp4":
            # Browsers need at least basic Range support to play/seek a
            # <video> at all reliably -- without it some refuse to play
            # anything beyond the first buffered chunk of a multi-MB clip.
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                try:
                    start_s, end_s = rng[6:].split("-", 1)
                    start = int(start_s) if start_s else 0
                    end = int(end_s) if end_s else size - 1
                    end = min(end, size - 1)
                except ValueError:
                    start, end = 0, size - 1
                with open(target, "rb") as f:
                    f.seek(start)
                    chunk = f.read(end - start + 1)
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            if self.command != "HEAD":
                with open(target, "rb") as f:
                    self.wfile.write(f.read())
            return

        with open(target, "rb") as f:
            self._send(f.read(), ctype, cache=cache)


def _scheduler(root, interval=600):
    """Unattended re-verification for lineups that ask for it.

    Off unless a lineup sets a period, and deliberately conservative about
    when it fires. A run holds the provider's connection for as long as it
    takes -- on a one-connection subscription that is the whole household's
    television -- so this never starts one while any other run or probe is
    in flight, and records the attempt on the lineup whether the run
    succeeds or not, so a failing lineup retries tomorrow rather than every
    thirty minutes forever.

    Deliberately not cron: the schedule belongs to the lineup, travels with
    it, and is visible in the UI that owns it.
    """
    import threading as _t

    def due(lu, runs_by_lineup):
        days = int(lu.get("schedule_days") or 0)
        if days <= 0:
            return False
        now = datetime.datetime.now()
        # A full re-scan holds the provider's connection for as long as it
        # takes -- hours, on a one-connection subscription -- so it runs at
        # an hour nobody is watching rather than whenever the interval
        # happens to elapse. Default 02:00, and for a weekly cadence a
        # chosen night, because "Monday at 2am" is a decision about the
        # household, not about probarr.
        if now.hour != int(lu.get("schedule_hour", 2)):
            return False
        if days == 7 and now.weekday() != int(lu.get("schedule_weekday", 0)):
            return False
        last = lu.get("last_scheduled") or 0
        for r in runs_by_lineup.get(lu["name"], []):
            last = max(last, r.get("last_completed") or r.get("started") or 0)
        # Slightly under the cadence, so the hour window is never missed by a
        # run that finished a few minutes late last time.
        return (time.time() - last) >= (days * 86400) - 7200

    def tick():
        while True:
            time.sleep(interval)
            try:
                if Handler._queue().snapshot()["queued"] or \
                        Handler._queue().snapshot()["running"]:
                    continue
                runs = RunStore.list_runs(root)
                if any(r.get("run_state") == "running" and
                       runs_mod.status(r["run_id"]) and
                       runs_mod.status(r["run_id"])["state"] == "running"
                       for r in runs):
                    continue
                by_lineup = {}
                for r in runs:
                    if r.get("lineup"):
                        by_lineup.setdefault(r["lineup"], []).append(r)
                for lu in lineups_mod.list_all(root):
                    # A one-off beats the recurring rule and is cleared as it
                    # fires. "Re-check everything tonight" is a different
                    # request from "re-check every Monday", and answering it
                    # by switching a recurring schedule on and remembering to
                    # switch it off again is how you end up with an
                    # unattended run you have forgotten about.
                    once = lu.get("run_once_at") or 0
                    if once and time.time() >= once:
                        lineups_mod.save(root, lu["name"], run_once_at=0,
                                         last_scheduled=time.time())
                    elif not due(lu, by_lineup):
                        continue
                    else:
                        lineups_mod.save(root, lu["name"],
                                         last_scheduled=time.time())
                    body = {"lineup": lu["name"], "provider": lu.get("provider"),
                            "source": lu.get("source") or "",
                            "wantlist": lu.get("wantlist") or "",
                            "epg": lu.get("epg") or "",
                            "regions": lu.get("regions") or ""}
                    h = Handler.__new__(Handler)
                    h.root = root
                    h._resolve_run_body(body)
                    if not (body.get("source") or "").strip():
                        continue
                    kwargs = h._run_kwargs(body, lu["name"])
                    # An update re-verifies the lineup's newest run IN PLACE.
                    # A fresh run would be a fresh snapshot needing curating
                    # from scratch; refreshing the existing one keeps every
                    # pick, group and rename, and the changes show up in
                    # Curate's own "needs review" filter -- which is the
                    # question being asked ("what moved?"), not "give me
                    # another lineup".
                    prev = by_lineup.get(lu["name"]) or []
                    if once and prev:
                        kwargs["run_id"] = prev[0]["run_id"]
                        kwargs["resume"] = False   # re-probe, do not skip
                    else:
                        kwargs["run_id"] = (lu["name"] + "-" +
                                            time.strftime("%Y%m%d-%H%M"))
                    print(f"scheduled re-verify of lineup {lu['name']} "
                          f"as run {kwargs['run_id']}", flush=True)
                    runs_mod.start(root, **kwargs)
                    break        # one at a time, never two at once
            except Exception as e:
                print(f"scheduler: {e}", flush=True)

    _t.Thread(target=tick, daemon=True).start()


def serve(root, host="0.0.0.0", port=7799):
    Handler.root = os.path.abspath(root)
    os.makedirs(Handler.root, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    # Probes accepted by a previous process and never finished. Resumed at
    # start rather than on first request, so a restart mid-queue costs a
    # pause and not the work -- every deploy recreates this container, and
    # losing the queue silently left the UI waiting on probes that no longer
    # existed.
    _scheduler(Handler.root)
    restored = Handler._queue().restore()
    if restored:
        print(f"resumed {restored} probe(s) left over from the last run",
              flush=True)
    # Every restart -- every deploy -- starts with a stone-cold EPG cache,
    # and the FIRST person to open Curate paid for that live through the
    # page's own persistent EPG badge (~19s across four real saved
    # sources, confirmed). Warming it here means that cost lands on an
    # idle container instead of the next person's page load.
    threading.Thread(target=epgcheck_mod.prewarm_all_sources,
                     args=(Handler.root, Normalizer(aliases=aliases_mod.read(Handler.root))),
                     daemon=True).start()
    print(f"probarr web UI on http://{host}:{port} (data: {Handler.root})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
