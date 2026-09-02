"""Command line interface."""
import argparse
import json
import os
import sys
import time

from . import __version__
from . import rank as rank_mod
from . import runner as runner_mod
from .contactsheet import render as render_sheet
from . import wantlist as wantlist_mod
from .normalize import Normalizer, group_candidates
from .sources import load_source
from .store import RunStore
from .verify import annotate_placeholders

# CHANNELIQ_* checked first, PROBARR_* honoured as a fallback -- anyone who
# set a custom PROBARR_CONFIG/PROBARR_PORT/PROBARR_FFMPEG in their own
# compose file (this app was renamed from probarr) keeps working exactly as
# before on their next pull, with nothing for them to change.
DEFAULT_ROOT = os.environ.get("CHANNELIQ_CONFIG",
                              os.environ.get("PROBARR_CONFIG", "/config"))


def _env(name, default=None):
    return os.environ.get(f"CHANNELIQ_{name}",
                          os.environ.get(f"PROBARR_{name}", default))


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _normalizer(args):
    aliases = {}
    if args.aliases and os.path.exists(args.aliases):
        with open(args.aliases) as f:
            aliases = json.load(f)
    return Normalizer(region_tags=args.region_tags, aliases=aliases)


def cmd_verify(args):
    aliases = {}
    if args.aliases and os.path.exists(args.aliases):
        with open(args.aliases) as f:
            aliases = json.load(f)

    total_estimate_shown = [False]

    def on_progress(p):
        r = p["record"]
        flag = {"ok": "OK   ", "dirty": "DIRTY", "placeholder": "PLCHLD",
                "no_frame": "NOFRM", "no_video": "NOVID", "dead": "DEAD "}.get(
            r.get("status"), "?????")
        detail = ""
        if r.get("status") in ("ok", "dirty", "placeholder"):
            detail = (f"{r.get('width')}x{r.get('height')}@{r.get('fps')} "
                      f"{r.get('measured_kbps')}kbps {r.get('video_codec')} "
                      f"motion={r.get('motion')}"
                      f"{' ' + str(r.get('corruption_errors')) + ' corrupt' if r.get('corruption_errors') else ''}")
        _log(f"  [{p['done']}/{p['total']}] {flag} {r['stream_name'][:52]:<52} {detail}"
             f"  eta {p['eta']//60}m")

    def on_log(msg):
        _log(msg)
        if (args.concurrency == 1 and "candidate streams" in msg
                and not total_estimate_shown[0]):
            try:
                total = int(msg.split(",")[1].strip().split()[0])
            except (IndexError, ValueError):
                total = 0
            if total > 40:
                est = total * (args.sample_seconds + 6) / 60
                _log(f"serial probing -- rough estimate {est:.0f} min. "
                     f"Raise --concurrency only up to what your provider allows.")
            total_estimate_shown[0] = True

    store, by_channel = runner_mod.start_run(
        args.root, args.source, run_id=args.run,
        wantlist=args.wantlist, epg=args.epg,
        regions=args.regions, strict_region=args.strict_region,
        region_tags=args.region_tags, aliases=aliases,
        concurrency=args.concurrency, gap_seconds=args.gap,
        sample_seconds=args.sample_seconds,
        frame_height=args.frame_height or 720,
        thumb_height=args.thumb_height or 240,
        max_candidates=args.max_candidates, min_candidates=args.min_candidates,
        only_channels=args.channel, limit_channels=args.limit_channels,
        resume=not args.no_resume, log=on_log, progress_cb=on_progress,
        clean_target=args.clean_target,
        prioritise=args.rolling,
        budget_seconds=(args.budget_minutes * 60
                        if args.budget_minutes else None),
    )

    out = args.sheet or os.path.join(store.dir, "contact-sheet.html")
    path, _ = render_sheet(by_channel, store, out, embed=not args.no_embed)
    _log(f"contact sheet: {path}")
    return 0


def cmd_sheet(args):
    store = RunStore(args.root, args.run) if args.run else RunStore.latest(args.root)
    if not store:
        _log("no runs found")
        return 1
    by_channel = annotate_placeholders(store)
    out = args.out or os.path.join(store.dir, "contact-sheet.html")
    path, payload = render_sheet(by_channel, store, out, embed=not args.no_embed)
    _log(f"contact sheet for run {store.run_id}: {path} "
         f"({len(payload['channels'])} channels)")
    return 0


def cmd_explain(args):
    """Show how a title normalises. The matcher fails silently, so make it visible."""
    norm = _normalizer(args)
    if args.source:
        streams = load_source(args.source)
        pools = group_candidates(streams, norm, regions=args.regions,
                                 include_unmarked=not args.strict_region)
        key = norm.key(args.name)
        print(f"key for {args.name!r}: {key}")
        matches = pools.get(key, [])
        print(f"{len(matches)} candidate stream(s) would be grouped under it:")
        for s in matches:
            print(f"  - {s.name}")
        near = [k for k in pools if k != key and (k.startswith(key[:6]) or key.startswith(k[:6]))]
        if near:
            print(f"nearby keys not grouped with it: {', '.join(sorted(near)[:12])}")
    else:
        for line in [args.name]:
            for k, v in norm.explain(line).items():
                print(f"  {k}: {v}")
    return 0


def cmd_runs(args):
    for r in RunStore.list_runs(args.root):
        print(f"{r['run_id']}  {r.get('channels', '?')} channels  "
              f"{r.get('candidates', '?')} candidates  {r.get('source', '')}")
    return 0


def cmd_serve(args):
    from .web import serve
    return serve(args.root, args.host, args.port)


def build_parser():
    p = argparse.ArgumentParser(
        prog="channeliq",
        description="Verify, compare and visually curate IPTV streams.")
    p.add_argument("--version", action="version", version=f"channeliq {__version__}")
    p.add_argument("--root", default=DEFAULT_ROOT,
                   help="config/data directory (default %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_match_args(sp):
        sp.add_argument("--regions", nargs="*", default=None,
                        help="restrict to these region tags, e.g. --regions UK IE")
        sp.add_argument("--strict-region", action="store_true",
                        help="exclude streams with no region marker at all "
                             "(off by default: genuine feeds are often unmarked)")
        sp.add_argument("--region-tags", nargs="*", default=None,
                        help="override the region tag vocabulary")
        sp.add_argument("--aliases", default=_env("ALIASES"),
                        help="JSON file of {name: canonical} aliases")

    v = sub.add_parser("verify", help="probe candidate streams and build a contact sheet")
    v.add_argument("--source", required=True,
                   help="m3u path/URL, dispatcharr://user:pass@host:9191, "
                        "or xtream://user:pass@host:port")
    v.add_argument("--run", default=None, help="run id (default: timestamp; reuse to resume)")
    v.add_argument("--concurrency", type=int, default=int(_env("CONCURRENCY", "1")),
                   help="simultaneous probes. Default 1. Never exceed your "
                        "provider's connection allowance (default %(default)s)")
    v.add_argument("--gap", type=float, default=0.4, help="seconds between serial probes")
    v.add_argument("--sample-seconds", type=int, default=8,
                   help="seconds of video to decode per stream (default %(default)s)")
    v.add_argument("--max-candidates", type=int, default=None,
                   help="cap candidates probed per channel")
    v.add_argument("--rolling", action="store_true",
                   help="probe worst-and-stalest channels first instead of "
                        "alphabetically -- pair with --budget-minutes to "
                        "re-verify continuously on a schedule")
    v.add_argument("--budget-minutes", type=float, default=None,
                   help="stop cleanly after roughly this long; re-running "
                        "resumes where it left off")
    v.add_argument("--clean-target", type=int, default=rank_mod.FALLBACK_DEPTH,
                   help="stop probing a channel's remaining (lower-declared-"
                        "quality) candidates once this many come back clean; "
                        "0 disables early stopping and probes everything "
                        "(default %(default)s)")
    v.add_argument("--min-candidates", type=int, default=1,
                   help="skip channels with fewer than N candidates")
    v.add_argument("--limit-channels", type=int, default=None, help="probe only the first N channels")
    v.add_argument("--channel", nargs="*", default=None, help="only these channel names")
    v.add_argument("--include-timeshift", action="store_true",
                   help="also probe '+1' catch-up variants (treated as separate channels)")
    v.add_argument("--no-resume", action="store_true", help="re-probe already-verified streams")
    v.add_argument("--wantlist", default=_env("WANTLIST"),
                   help="channels you want: a file path, or the name of a "
                        "wantlist saved in the web UI")
    v.add_argument("--epg", default=_env("EPG"),
                   help="XMLTV guide file or URL (.xml or .xml.gz) - records "
                        "what SHOULD be playing at probe time")
    v.add_argument("--frame-height", type=int, default=None,
                   help="height of the full-size captured frame (default 720)")
    v.add_argument("--thumb-height", type=int, default=None,
                   help="height of the grid thumbnail (default 240)")
    v.add_argument("--sheet", default=None, help="contact sheet output path")
    v.add_argument("--no-embed", action="store_true",
                   help="link thumbnails instead of embedding (smaller file, not portable)")
    add_match_args(v)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("sheet", help="rebuild the contact sheet from a stored run")
    s.add_argument("--run", default=None)
    s.add_argument("--out", default=None)
    s.add_argument("--no-embed", action="store_true")
    s.set_defaults(func=cmd_sheet)

    e = sub.add_parser("explain", help="show how a channel name is normalised and matched")
    e.add_argument("name")
    e.add_argument("--source", default=None)
    add_match_args(e)
    e.set_defaults(func=cmd_explain)

    r = sub.add_parser("runs", help="list stored runs")
    r.set_defaults(func=cmd_runs)

    w = sub.add_parser("serve", help="run the web UI")
    w.add_argument("--host", default="0.0.0.0")
    w.add_argument("--port", type=int, default=int(_env("PORT", "7799")))
    w.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _log("interrupted -- results already probed are saved and the run can be resumed")
        return 130
    except RuntimeError as e:
        _log(f"error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
