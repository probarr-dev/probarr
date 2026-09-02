"""Shared run orchestration: source -> wantlist -> EPG -> probe -> store.

This is the one place that assembles a run. It exists so the CLI and the web
UI's "New Run" flow do exactly the same thing -- previously this logic lived
only inside the CLI's argparse handler, which meant the web UI could show a
form but had no way to actually act on it without either shelling out to the
CLI or silently reimplementing (and inevitably drifting from) its behaviour.
"""
import os
import shutil
import threading
import time

from . import __version__
from . import epgcheck as epgcheck_mod
from . import lineups as lineups_mod
from . import settings as settings_mod
from . import tagsettings
from . import wantlist as wantlist_mod
from .epg import Guide
from .normalize import Normalizer, group_candidates
from .probe import ProbeOptions
from .sources import load_source
from .store import RunStore
from .verify import verify as run_probes


def start_run(root, source, run_id=None, wantlist=None, epg=None,
              regions=None, strict_region=False, region_tags=None,
              aliases=None, concurrency=1, gap_seconds=0.4,
              sample_seconds=10, frame_height=720, thumb_height=240,
              max_candidates=None, min_candidates=1, only_channels=None,
              limit_channels=None, resume=True, provider_name=None, log=None,
              progress_cb=None, should_stop=None, clean_target=2,
              lineup=None, prioritise=False, budget_seconds=None, gate=None,
              prefer_dispatcharr_proxy=False):
    """Run a full verification pass. Returns the RunStore it wrote to.

    `log`: callable(str), for progress narration -- printed by the CLI,
    appended to a run's live log by the web UI's background runner.
    """
    log = log or (lambda msg: None)
    # Created up front, before anything that can fail (loading the source,
    # the EPG, matching the wantlist), specifically so a failure has
    # somewhere to report itself. Without this, an unreachable provider URL
    # would raise before a RunStore existed at all, and a web UI polling for
    # progress would have no record to poll and would spin forever.
    # The one place a run is genuinely brought into existence, so the one
    # place that asks for its directories to be made -- see RunStore's own
    # docstring for why every other (reading) caller must not.
    store = RunStore(root, run_id, create=True)
    store.write_meta({"source": source.split("?")[0], "provider_name": provider_name,
                      # Which durable lineup this run is a snapshot of, if
                      # any -- what lets curation inherit that lineup's
                      # accumulated per-channel decisions.
                      "lineup": lineup,
                      "run_state": "running",
                      "started": time.time(), "version": __version__})
    try:
        return _run(store, root, source, wantlist, epg, regions, strict_region,
                   region_tags, aliases, concurrency, gap_seconds,
                   sample_seconds, frame_height, thumb_height, max_candidates,
                   min_candidates, only_channels, limit_channels, resume,
                   log, progress_cb, should_stop, clean_target, lineup,
                   prioritise, budget_seconds, gate, prefer_dispatcharr_proxy)
    except Exception as e:
        store.write_meta({**store.read_meta(), "run_state": "error",
                          "error": str(e)[:500], "finished": time.time()})
        log(f"error: {e}")
        raise


def _carry_forward_fresh(root, store, lineup, pools, log):
    """Copy still-fresh verdicts from this lineup's last run straight into
    this one, so build_worklist()'s existing resume logic (see verify.py)
    skips re-probing them -- a genuinely new run that spends its connection
    budget only on what might actually have changed.

    Idea borrowed from Podium (open-source, MIT, see its README): a
    provider's stream set barely moves between runs, so a stream whose
    provider-declared id (`stream.id`, which is itself derived from its URL
    -- see sources/m3u.py and sources/xtream.py) is unchanged from last time
    almost certainly still measures the same, and re-probing it anyway is a
    connection spent on nothing new. `freshness_hours` (0 = disabled) is how
    long a prior verdict is trusted before it is treated as stale again
    regardless of whether the id moved.

    Requires a lineup: an ad-hoc run has no "last time" to compare against,
    and carrying forward a DIFFERENT lineup's verdict for what happens to be
    the same stream id would be trusting a probe against a different
    channel's context (a different EPG, different curation).
    """
    if not lineup:
        return 0
    hours = settings_mod.read(root).get("freshness_hours") or 0
    if hours <= 0:
        return 0
    prior_meta = next((r for r in RunStore.list_runs(root)
                       if r.get("lineup") == lineup and r.get("run_id") != store.run_id
                       and r.get("run_state") not in ("running", "error")), None)
    if not prior_meta:
        return 0
    prior = RunStore(root, prior_meta["run_id"])
    if not os.path.exists(prior.results_path):
        return 0
    cutoff = time.time() - hours * 3600
    # Newest record per rec_key -- load() already collapses re-probes of the
    # same stream to the latest one.
    #
    # Per-CHANNEL id sets, not one flattened global set. Real bug found on
    # a full-codebase review: a provider will happily list the same URL
    # under several channel names (verify.py notes this same fact
    # elsewhere), so a bare "is this stream id still in the catalogue
    # ANYWHERE" check let a stale record for a channel excluded from THIS
    # run's scope (via only_channels/min_candidates/limit_channels) carry
    # forward anyway, purely because some OTHER, in-scope channel happened
    # to share that stream id. That out-of-scope channel's old verdict then
    # re-entered results.jsonl looking freshly verified.
    current_ids_by_channel = {ch: {s.id for s in streams}
                              for ch, streams in pools.items()}
    carried = 0
    for r in prior.load():
        ch_key = r.get("channel_key")
        if r.get("stream_id") not in current_ids_by_channel.get(ch_key, ()):
            continue           # not offered for THIS channel any more (or
                                # this channel isn't part of this run at all)
        if (r.get("probed_at") or 0) < cutoff:
            continue           # old enough that it deserves a real look again
        if r.get("status") == "dead":
            # Never carried forward, on purpose: a dead stream is exactly
            # the one candidate worth re-trying on every real pass rather
            # than skipping, since that retry -- not a person clicking
            # "trust me" -- is what quietly un-deads it the moment the
            # provider's own fault clears. Skipping it here would make
            # "dead" permanent instead of just the last thing observed.
            continue
        rk = r.get("rec_key") or f"{r.get('channel_key')}|{r.get('stream_id')}"
        record = {**r, "carried_forward": True}
        store.append(record)
        # Images live on disk per-run, not in the JSON -- without copying
        # them across, a carried-forward candidate would show "no frame"
        # despite claiming a clean verdict, which reads as a lie.
        for attr, path_fn in (("thumb", prior.thumb_path), ("frame", prior.frame_path),
                              ("crop", prior.crop_path), ("clip", prior.clip_path)):
            if not r.get(attr):
                continue
            src = path_fn(rk)
            if not os.path.exists(src):
                continue
            dst = {"thumb": store.thumb_path, "frame": store.frame_path,
                  "crop": store.crop_path, "clip": store.clip_path}[attr](rk)
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass
        carried += 1
    return carried


def _seed_groups(root, store, lineup, wanted):
    """Carry `[Group]` headers from the wantlist into the channel's group,
    but only where nothing has decided one yet.

    A wantlist header is a starting point, not a standing order -- once a
    lineup has its own recorded group preference for a channel (set by
    curating it, here or in an earlier run), that decision wins on every
    later re-verify, same as every other durable per-channel preference.
    Group headers exist so a lineup's FIRST run doesn't start from nothing.

    Without a lineup, there is nothing durable to carry the group forward
    between runs anyway, so it is written straight into this run's own
    selection instead -- still better than making the operator rebuild
    every group by hand immediately after the first probe finishes.
    """
    groups = {w.key: w.group for w in wanted if w.group}
    if not groups:
        return
    if lineup:
        # A run can name a lineup before that lineup has ever been formally
        # saved (typed straight into New Run) -- set_preference() is a no-op
        # against a lineup that doesn't exist yet, which would silently
        # defeat group headers on exactly the first-run case they are for.
        if not lineups_mod.get(root, lineup):
            lineups_mod.save(root, lineup)
        existing = lineups_mod.preferences(root, lineup)
        for key, group in groups.items():
            if not (existing.get(key) or {}).get("group"):
                lineups_mod.set_preference(root, lineup, key, group=group)
    else:
        sel = store.read_selection() or {}
        changed = False
        for key, group in groups.items():
            if not (sel.get(key) or {}).get("group"):
                sel.setdefault(key, {})["group"] = group
                changed = True
        if changed:
            store.write_selection(sel)


def _run(store, root, source, wantlist, epg, regions, strict_region, region_tags,
         aliases, concurrency, gap_seconds, sample_seconds, frame_height,
         thumb_height, max_candidates, min_candidates, only_channels,
         limit_channels, resume, log, progress_cb, should_stop, clean_target=2,
         lineup=None, prioritise=False, budget_seconds=None, gate=None,
         prefer_dispatcharr_proxy=False):
    # The operator's own saved tag vocabulary (Settings -> Manage tags) is
    # the base for every run; `region_tags` here is only ever a run-specific
    # ADDITION on top of it (the New Run form's one-off "Custom prefixes"
    # field, for a prefix not worth saving permanently) -- never a
    # replacement, which is what Normalizer(region_tags=...) would do if
    # handed only the extras. See tagsettings.py's own docstring for why
    # the saved list itself already tracks future built-in additions
    # rather than being frozen the moment a user customises anything.
    all_region_tags = list(dict.fromkeys(
        tagsettings.tags(root, "region") + list(region_tags or [])))
    norm = Normalizer(region_tags=all_region_tags,
                      quality_tags=tagsettings.tags(root, "quality"),
                      aliases=aliases or {})

    log(f"loading source: {source.split('?')[0]}")
    # `prefer_proxy` is meaningful only for a dispatcharr:// source --
    # every other loader's load() ignores unknown kwargs (see sources/
    # base.py's load_source()), so passing it through unconditionally is
    # safe rather than needing a scheme check here.
    streams = load_source(source, prefer_proxy=prefer_dispatcharr_proxy)
    log(f"{len(streams)} streams in source")

    pools = group_candidates(streams, norm, regions=regions,
                             include_unmarked=not strict_region)

    wanted, missing = [], []
    if wantlist:
        wanted = wantlist_mod.load(wantlist_mod.resolve_path(root, wantlist), norm)
        log(f"wantlist: {len(wanted)} channels requested")
        sensitivity = settings_mod.read(root).get("match_sensitivity", "strict")
        pools, missing, fuzzy = wantlist_mod.apply(wanted, pools, sensitivity=sensitivity)
        for w, alt in fuzzy:
            log(f"    ~ {w.name}: no exact match, using '{alt}'")
        if missing:
            log(f"{len(missing)} wanted channel(s) matched NO stream at all:")
            for w in missing[:20]:
                log(f"    - {w.name}  (key {w.key})")
            if len(missing) > 20:
                log(f"    ... and {len(missing) - 20} more")

    if only_channels:
        wanted_keys = {norm.key(c) for c in only_channels}
        pools = {k: v for k, v in pools.items() if k in wanted_keys}
    if min_candidates > 1:
        pools = {k: v for k, v in pools.items() if len(v) >= min_candidates}
    if limit_channels:
        pools = dict(sorted(pools.items())[:limit_channels])
    # max_candidates truncates candidates PER CHANNEL, not the channel list --
    # that truncation happens inside verify()'s worklist builder, below, so it
    # is not duplicated here.

    guide = None
    if epg:
        log(f"loading EPG: {epg.split('?')[0]}")
        try:
            guide = Guide.load(epg).build_name_index(norm)
            st = guide.stats()
            log(f"EPG: {st['channels']} channels, {st['programmes']} programmes in window")
        except Exception as e:
            log(f"EPG unavailable ({e}) - continuing without expected-programme data")

    total = sum(len(v) for v in pools.values())
    log(f"{len(pools)} channels, {total} candidate streams (concurrency {concurrency})")
    # Real incident this catches: a run against a genuinely multi-country
    # catalogue with no Regions filter set matched a plainly-named channel
    # ("5", "Al Jazeera English") against every country's copy of it, not
    # just the intended one -- 139 channels pulled 1,203 candidates instead
    # of a few hundred. Nothing caught it until someone read the log and
    # did the division by hand. A high average here, with no filter set, is
    # exactly that signature -- surfaced automatically so a future run
    # doesn't need a person who happens to already know what "too many
    # candidates" looks like.
    if not regions and pools and (total / len(pools)) > 6:
        log(f"note: {total/len(pools):.1f} candidates per channel on average with "
            "no Regions filter set -- on a multi-country provider a plainly-named "
            "channel (e.g. \"5\", \"Al Jazeera English\") can match every "
            "country's copy of it, not just the one you want. If this run is "
            "taking far longer than expected, set Regions (e.g. \"UK\") on it "
            "or its lineup and re-run.")

    if wanted:
        store.write_wantlist(wanted, missing)
        _seed_groups(root, store, lineup, wanted)
    store.write_meta({
        **store.read_meta(),
        "epg": bool(guide),
        "wantlist": len(wanted) if wanted else 0,
        "missing": len(missing),
        "channels": len(pools), "candidates": total,
        "concurrency": concurrency, "sample_seconds": sample_seconds,
        "run_state": "running",
    })
    log(f"run {store.run_id} -> {store.dir}")

    carried = _carry_forward_fresh(root, store, lineup, pools, log)
    if carried:
        log(f"{carried} candidate(s) carried forward unprobed -- "
           f"unchanged since a recent enough verdict")

    opts = ProbeOptions(sample_seconds=sample_seconds, frame_height=frame_height,
                        thumb_height=thumb_height,
                        capture_timeout=sample_seconds + 35).resolved()

    by_channel = run_probes(pools, store, opts, concurrency=concurrency,
                            gap_seconds=gap_seconds, resume=resume,
                            max_candidates_per_channel=max_candidates,
                            progress_cb=progress_cb, should_stop=should_stop,
                            guide=guide, normalizer=norm, clean_target=clean_target,
                            log=log, prioritise=prioritise,
                            budget_seconds=budget_seconds, gate=gate)

    clean = sum(1 for rs in by_channel.values()
                if any(r.get("status") == "ok" for r in rs))
    log(f"done: {clean}/{len(by_channel)} channels have a clean stream")

    now = time.time()
    meta = store.read_meta()
    # Two distinct timestamps, because they answer different questions.
    # last_completed: when a pass last finished at all, including one cut
    # short by a budget -- "is this run being kept up to date?".
    # full_completed: when a pass last got through the ENTIRE worklist --
    # "when was this lineup last verified end to end?". A rolling
    # 20-minute nightly job updates the first every night and the second
    # only when it finally catches up, which is exactly the distinction
    # worth seeing at a glance.
    updates = {"run_state": "done", "finished": now, "last_completed": now}
    if not meta.get("interrupted"):
        updates["full_completed"] = now
    store.write_meta({**meta, **updates})
    # A completed run is exactly the moment Curate's own EPG cache is most
    # likely to be cold -- a real run routinely outlasts the cache's TTL,
    # so the person who just finished waiting for the run would otherwise
    # immediately hit another ~19s wait opening the result. Backgrounded:
    # this must not delay the run's own completion, and a failure here is
    # not a run failure (see prewarm_all_sources()'s own best-effort
    # handling of individual sources).
    threading.Thread(target=epgcheck_mod.prewarm_all_sources,
                     args=(root, norm), daemon=True).start()
    return store, by_channel
