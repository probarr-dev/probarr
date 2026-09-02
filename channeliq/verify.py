"""Run orchestration: walk candidates, probe each, write results as they land.

Concurrency is a first-class configuration value with a deliberately
conservative default of 1.

Many IPTV providers enforce a hard cap on simultaneous connections -- the one
this tool was built against allowed exactly one, and exceeding it does not
produce a clean error. It produces *plausible garbage*: near-uniform tiny
error responses that look like dead streams, leading you to conclude a working
stream is broken. Parallel probing against such a provider silently poisons
its own results.

So: default serial, raise it explicitly once you know your allowance, and
always leave headroom for whoever is actually watching TV.
"""
import collections
import concurrent.futures
import datetime
import threading
import time

from . import rank as rank_mod
from .dhash import group_identical
from .normalize import declared_quality_rank
from .probe import probe, STATUS_OK


def _safe(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


class RateLimitGuard:
    """Adaptive backoff for a provider that is actively REFUSING connections
    (HTTP 429/403 seen in ffmpeg/ffprobe's stderr -- see probe.py), as
    distinct from a genuinely dead or corrupted stream.

    Modelled directly on the equivalent in PiratesIRC's IPTVChecker (already
    credited in the README for other ideas), which this project's own
    verification pipeline turned out to have no counterpart for. That gap
    matters concretely: a probe that comes back "no frame could be decoded"
    because the provider said 403 looks IDENTICAL, in every field channeliq
    used to record, to one that failed because the channel is genuinely off
    air. One specific channel's failures were investigated by hand and
    showed exactly this shape -- the same URL, seconds apart, zero other
    traffic, one hard failure and one clean decode -- which a fixed retry
    delay and a per-channel/per-lane concurrency limit (see probequeue.py's
    LANE_SETTLE_SECONDS) cannot address, because neither is a response to
    what the provider is actually saying.

    A single instance is shared across an entire verify() run (not
    per-channel, not per-lane): a provider issuing 429s is asserting
    something about the ACCOUNT's connection budget, not about one channel,
    so tripping should pause everything hitting that provider, the same way
    IPTVChecker's guard is one process-wide singleton rather than one per
    stream.
    """
    WINDOW_SECONDS = 60
    # Lower than IPTVChecker's default (5): providers seen from this tool
    # typically permit far fewer concurrent connections in the first place,
    # so a smaller burst of refusals is already a meaningful signal here.
    TRIP_THRESHOLD = 3
    BASE_COOLDOWN_SECONDS = 30
    MAX_COOLDOWN_SECONDS = 300
    DECAY_AFTER_SECONDS = 180

    def __init__(self):
        self._lock = threading.Lock()
        self._hit_times = collections.deque()
        self._cooldown_until = 0.0
        self._next_cooldown = self.BASE_COOLDOWN_SECONDS
        self._last_hit_time = 0.0
        # Exposed for the UI/tests: how many times this run has tripped.
        self.trips = 0

    def record_hit(self, log=None):
        now = time.time()
        with self._lock:
            self._hit_times.append(now)
            self._last_hit_time = now
            cutoff = now - self.WINDOW_SECONDS
            while self._hit_times and self._hit_times[0] < cutoff:
                self._hit_times.popleft()
            if len(self._hit_times) >= self.TRIP_THRESHOLD and now >= self._cooldown_until:
                cooldown = self._next_cooldown
                self._cooldown_until = now + cooldown
                self._next_cooldown = min(self._next_cooldown * 2, self.MAX_COOLDOWN_SECONDS)
                self._hit_times.clear()
                self.trips += 1
                if log:
                    log(f"  rate-limit guard tripped: provider refused "
                       f"{self.TRIP_THRESHOLD}+ connections (429/403) within "
                       f"{self.WINDOW_SECONDS}s -- pausing ALL probing for "
                       f"{int(cooldown)}s")

    def wait(self, log=None, should_stop=None):
        with self._lock:
            now = time.time()
            if self._last_hit_time and (now - self._last_hit_time) > self.DECAY_AFTER_SECONDS:
                self._next_cooldown = self.BASE_COOLDOWN_SECONDS
            remaining = self._cooldown_until - now
        if remaining <= 0:
            return
        if log:
            log(f"  rate-limit cooldown active -- waiting {int(remaining)}s before next probe")
        # Re-read _cooldown_until each iteration so a fresh trip that
        # EXTENDS the cooldown mid-wait is honoured, rather than every
        # waiting worker resuming on the original (now stale) deadline.
        while True:
            with self._lock:
                remaining = self._cooldown_until - time.time()
            if remaining <= 0:
                return
            if should_stop and should_stop():
                return
            time.sleep(min(remaining, 1.0))


def _rk(record):
    """Probe identity, tolerating records written before rec_key existed."""
    return record.get("rec_key") or f"{record['channel_key']}|{record['stream_id']}"


class Progress:
    """Thread-safe progress accounting, rendered by whatever front end is attached."""

    def __init__(self, total, callback=None):
        self.total = total
        self.done = 0
        self.started = time.time()
        self._lock = threading.Lock()
        self._callback = callback
        self.current = ""

    def tick(self, label, record):
        with self._lock:
            self.done += 1
            self.current = label
            elapsed = time.time() - self.started
            rate = self.done / elapsed if elapsed > 0 else 0
            eta = (self.total - self.done) / rate if rate > 0 else 0
            snapshot = {
                "done": self.done, "total": self.total,
                "elapsed": round(elapsed), "eta": round(eta),
                "label": label, "record": record,
            }
        if self._callback:
            self._callback(snapshot)
        return snapshot


def channel_priority(store):
    """(worst-and-stalest-first) ordering key per channel key.

    Alphabetical order is fine for a run that will probe everything anyway,
    and actively wrong for one that might stop early -- under a time budget
    the alphabet decides what gets verified, which is nobody's intent.

    Ranks by, in order: channels with NO clean result yet (the ones a
    lineup is actually broken without), then least-recently-probed (so
    attention rotates rather than re-checking the same head of the list
    every night), then name for stability.
    """
    clean, last_seen = {}, {}
    for r in store.load():
        k = r.get("channel_key")
        if not k:
            continue
        if r.get("status") == STATUS_OK:
            clean[k] = True
        at = r.get("probed_at") or 0
        if at > last_seen.get(k, 0):
            last_seen[k] = at

    def key(channel_key):
        return (1 if clean.get(channel_key) else 0,
                last_seen.get(channel_key, 0.0),
                channel_key)
    return key


def build_worklist(pools, store, resume=True, max_candidates_per_channel=None,
                   prioritise=False):
    """Flatten {channel_key: [Stream]} into probe units, skipping finished work.

    Each channel's candidates are sorted best-declared-quality-first (see
    declared_quality_rank()) before any truncation, so max_candidates_per_channel
    (a hard ceiling) and the adaptive clean_target stopping in verify() both
    get to try the plausibly-best candidates, not whatever order the M3U
    happened to list them in.

    `prioritise` orders the CHANNELS themselves worst-and-stalest-first
    rather than alphabetically -- see channel_priority(). Matters whenever a
    run may not finish everything (a time budget, an interruption), which is
    the normal case for continuous re-verification.
    """
    done = store.done_ids() if resume else set()
    work = []
    order = channel_priority(store) if prioritise else (lambda k: k)
    for key, streams in sorted(pools.items(), key=lambda kv: order(kv[0])):
        streams = sorted(streams, key=lambda s: declared_quality_rank(s.name),
                         reverse=True)
        chosen = streams[:max_candidates_per_channel] if max_candidates_per_channel else streams
        for s in chosen:
            if f"{key}|{s.id}" in done:
                continue
            work.append((key, s))
    return work


def _wait_for_free_connection(gate, log, should_stop):
    """Hold until nobody is watching, when a gate says somebody is.

    A run probes for hours on a subscription that permits one connection, so
    starting one while a television is playing does not merely slow it down
    -- every probe gets the provider's holding card or nothing, and the run
    records that as a lineup of dead and placeholder streams. Waiting is
    always better than recording a lie.
    """
    said = False
    while gate:
        reason = None
        try:
            reason = gate()
        except Exception:
            return          # a broken check must never stall a run
        if not reason:
            if said:
                log("  connection free again, continuing")
            return
        if not said:
            log(f"  paused: {reason}")
            said = True
        for _ in range(6):
            if should_stop and should_stop():
                return
            time.sleep(5)


def verify(pools, store, opts, concurrency=1, gap_seconds=0.4,
           resume=True, max_candidates_per_channel=None, progress_cb=None,
           should_stop=None, guide=None, normalizer=None, clean_target=2,
           gate=None,
           log=None, prioritise=False, budget_seconds=None):
    """Probe every candidate, appending each result to the store immediately.

    should_stop: optional callable checked between probes so a front end can
    cancel a long run without killing the process and losing the store.

    clean_target: stop probing a channel's remaining (lower-ranked) candidates
    once it has this many genuinely clean (status "ok") results. Candidates
    are already sorted best-declared-first by build_worklist(), so the common
    case is exactly 2 probes per channel -- try the best, try the second-best,
    both come back clean, stop. A channel only spills into its 3rd/4th/...
    candidate when one of the first two actually had errors, which is the
    real, adaptive version of what max_candidates_per_channel could only do
    as a blind, non-adaptive ceiling. Only applied to the serial
    (concurrency<=1) path -- see the note in the concurrent branch below for
    why parallel probing doesn't get the same treatment.

    log: optional callable(str), narrates each probe AND each adaptive skip.
    Without this, a skip was previously invisible everywhere -- not in the
    run log, not in results.jsonl (nothing is written for a candidate that
    was never probed), so there was no way to tell "this channel only got 2
    candidates because they were both clean" from "this run just hasn't
    gotten to the rest yet". Every skip now says why.
    """
    log = log or (lambda msg: None)
    work = build_worklist(pools, store, resume, max_candidates_per_channel,
                          prioritise=prioritise)
    started_at = time.time()
    rate_guard = RateLimitGuard()
    # Per-channel locks so the concurrency>1 path never runs two candidates
    # of the SAME channel at once, matching probequeue.py's per-channel
    # single-flight rule (see its comment for the evidenced reason: two
    # same-channel candidates launched in the same second both came back
    # corrupted, while the identical URL decoded cleanly moments later in
    # isolation). The serial path never needed this -- only one probe runs
    # at all -- but the concurrent branch below had NO equivalent before
    # this, despite being the path an operator running with several
    # provider slots actually uses for a full verify.
    channel_locks = {}
    channel_locks_guard = threading.Lock()

    def _channel_lock(key):
        # defaultdict(threading.Lock) would race two threads seeing the
        # same missing key at once into creating two DIFFERENT Lock objects
        # (dict.__setitem__ is atomic, the creation before it is not) --
        # exactly the same failure mode this lock exists to prevent, just
        # one level up. Guard the creation itself instead.
        with channel_locks_guard:
            lock = channel_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                channel_locks[key] = lock
            return lock
    # Whether this pass got through its whole worklist, as opposed to being
    # cut short by a budget or a stop request. The distinction matters to a
    # reader of the run list: "finished at 4am" means something very
    # different if it stopped because it ran out of time rather than
    # because it ran out of work.
    interrupted = [False]
    prog = Progress(len(work), progress_cb)

    def one(item):
        key, stream = item
        rk = f"{key}|{stream.id}"
        rate_guard.wait(log, should_stop)
        with _channel_lock(key):
            result = probe(stream, opts, store.thumb_path(rk),
                           store.frame_path(rk), store.crop_path(rk))
        if result.get("rate_limited"):
            rate_guard.record_hit(log)

        # Resolve the expected programme AT PROBE TIME, not at viewing time.
        # The frame and the schedule entry have to describe the same instant
        # or comparing them proves nothing.
        expected = None
        if guide is not None:
            cid = guide.resolve(stream.tvg_id, stream.name, normalizer)
            if cid:
                expected = guide.now_playing(
                    cid, datetime.datetime.now(datetime.timezone.utc))
                if expected:
                    expected["guide_channel"] = cid
        record = {
            "channel_key": key,
            # Identity of this PROBE, not of the stream. A provider will
            # happily list one URL under several channel names, and M3U stream
            # ids are derived from the URL -- so keying anything by stream_id
            # alone silently collapses those into a single entry. That is the
            # exact case placeholder detection needs to see.
            "rec_key": f"{key}|{stream.id}",
            "stream_id": stream.id,
            "stream_name": stream.name,
            # The real URL is kept in the run data because an export has to
            # produce a playlist that actually plays. The privacy boundary is
            # the SHARED artefact, not the working file: run directories live
            # under the gitignored config volume, while contact sheets and the
            # curation UI only ever receive `url_redacted`.
            "url": stream.url,
            "url_redacted": stream.redacted_url(),
            "group": stream.group,
            "logo": stream.logo,
            "tvg_id": stream.tvg_id,
            "thumb": (f"thumbs/{_safe(rk)}.jpg" if result.get("thumb") else None),
            "frame": (f"frames/{_safe(rk)}.jpg" if result.get("frame") else None),
            "crop": (f"crops/{_safe(rk)}.jpg" if result.get("crop") else None),
            "expected": expected,
            "probed_at": time.time(),
            **{k: v for k, v in result.items()
               if k not in ("thumb", "frame", "crop")},
        }
        store.append(record)
        prog.tick(f"{key} / {stream.name}", record)
        log(f"  probed {key} / {stream.name}: {record.get('status')}")
        return record

    if concurrency <= 1:
        # Seed from already-completed results (resumed run or an earlier
        # channel this same run) so a channel that already has its 2 clean
        # candidates doesn't get re-probed, and so total prog.total staying
        # at the full work list length (not adjusted for skips) is the only
        # inaccuracy -- ETA runs a little conservative near the end rather
        # than needing a second progress-total scheme.
        clean_counts = collections.defaultdict(int)
        for r in store.load():
            if r.get("status") == STATUS_OK:
                clean_counts[r["channel_key"]] += 1
        for item in work:
            if should_stop and should_stop():
                interrupted[0] = True
                break
            # A budget makes a run bounded rather than open-ended, which is
            # what turns "block for three hours once" into "verify for
            # twenty minutes on a schedule". Checked between probes only --
            # killing an in-flight ffmpeg mid-capture would waste the work
            # already done and can leave a half-written frame.
            if budget_seconds and (time.time() - started_at) >= budget_seconds:
                log(f"  budget of {budget_seconds}s reached -- stopping cleanly; "
                   f"re-run to continue where this left off")
                interrupted[0] = True
                break
            key, stream = item
            if clean_target and clean_counts[key] >= clean_target:
                # Already have enough clean candidates for this channel --
                # every remaining item for it is lower-ranked by construction
                # (build_worklist sorts best-declared-first), so there is
                # nothing to gain by probing it too.
                log(f"  skipped {key} / {stream.name}: already has "
                   f"{clean_counts[key]} clean candidate(s)")
                continue
            _wait_for_free_connection(gate, log, should_stop)
            if should_stop and should_stop():
                break
            record = one(item)
            if record.get("status") == STATUS_OK:
                clean_counts[key] += 1
            if gap_seconds:
                time.sleep(gap_seconds)
    else:
        # No adaptive early-stop here: with several probes genuinely in
        # flight at once, a channel could reach clean_target from workers
        # still running when a later worker for the same channel is
        # dispatched, and cancelling in-flight ffmpeg processes safely isn't
        # worth the complexity for a concurrency level real IPTV providers
        # essentially never allow in the first place (see the module
        # docstring). Concurrency>1 still probes everything, same as before.
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for item in work:
                if should_stop and should_stop():
                    interrupted[0] = True
                    break
                # Checked here too, though it rarely fires here in
                # practice: submit() is non-blocking, so this loop races
                # through the whole work list in milliseconds -- the real
                # enforcement is the identical check in the as_completed
                # loop below, which can actually observe elapsed wall time
                # since probes take real seconds to run.
                if budget_seconds and (time.time() - started_at) >= budget_seconds:
                    interrupted[0] = True
                    break
                futures.append(pool.submit(one, item))
            # submit() only queues work -- it returns immediately, so the
            # loop above races through the ENTIRE work list (hundreds of
            # candidates, all queued in milliseconds) long before a
            # should_stop() flip could ever land mid-loop. Real bug this
            # caused: Stop verifying appeared to do nothing at all on any
            # concurrency>1 run, because by the time a stop request arrived
            # every future was already queued, and this loop used to just
            # wait for every single one of them to finish regardless.
            # Checking here too, and cancelling whatever hasn't actually
            # started yet, is what makes Stop take effect promptly instead
            # of only after the full candidate list drains.
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    # Belt and braces: probe() itself never raises, but
                    # store.append()/guide lookups inside one() theoretically
                    # could. Before the should_stop handling above, an
                    # exception here always propagated loudly (every future
                    # was consumed via as_completed to the end); now that a
                    # stop can abandon still-running futures without ever
                    # calling their .result(), an exception from one of
                    # THOSE would otherwise vanish silently instead of
                    # ending the run visibly. Logged here so it's never lost
                    # either way.
                    log(f"  probe raised an unexpected error: {e}")
                stopped = should_stop and should_stop()
                # Real bug: budget_seconds was documented and enforced in
                # the serial path above, but this branch (concurrency>1)
                # checked only should_stop() -- a scheduled lineup with a
                # concurrency>1 provider and a budget cap ran to completion
                # of the entire work list regardless of elapsed time,
                # silently defeating the one thing budget_seconds exists
                # for. Same semantics as the serial path: checked between
                # completions, not mid-capture, so nothing in flight is
                # killed -- only futures that haven't started are cancelled.
                over_budget = (budget_seconds and
                              (time.time() - started_at) >= budget_seconds)
                if stopped or over_budget:
                    interrupted[0] = True
                    if over_budget and not stopped:
                        log(f"  budget of {budget_seconds}s reached -- "
                           f"stopping cleanly; re-run to continue where "
                           f"this left off")
                    for pending in futures:
                        pending.cancel()
                    break

    # Recorded on the store rather than returned, so adding it did not have
    # to change verify()'s return shape for every existing caller.
    store.write_meta({**store.read_meta(), "interrupted": interrupted[0]})
    return annotate_placeholders(store)


def annotate_placeholders(store):
    """Cross-stream pass identifying provider placeholder cards.

    Runs after probing rather than during it, because the corroborating signal
    is a relation between streams.

    The per-stream stillness test (done during capture) already says "this
    picture is not moving". That alone is ambiguous: it could be the
    provider's "channel unavailable" card, or a channel genuinely off air
    showing its own idle slate, or a static-image radio channel.

    This pass disambiguates by matching still frames *across* streams. When
    several different channels serve the same still picture, that picture is
    the provider's, not any one channel's -- which is the actual finding.

    Note what is deliberately NOT attempted: matching frames of *moving*
    content across channels to find relabelled duplicate feeds. Streams probed
    minutes apart never match even when they are the same feed, so that test
    would report nothing but false negatives.
    """
    records = store.load()

    # Only still frames are eligible. Comparing moving content across streams
    # is meaningless, and including it produced false groupings in testing.
    hashes = {_rk(r): r.get("dhash")
              for r in records if r.get("dhash") and r.get("low_motion")}
    frames = {}
    for r in records:
        if r.get("frame32"):
            try:
                frames[_rk(r)] = bytes.fromhex(r["frame32"])
            except ValueError:
                pass
    groups = group_identical(hashes, frames=frames)

    group_channels = {}
    for r in records:
        g = groups.get(_rk(r))
        if g:
            group_channels.setdefault(g, set()).add(r["channel_key"])

    by_channel = {}
    for r in records:
        g = groups.get(_rk(r))
        spans = len(group_channels.get(g, ())) > 1 if g else False
        # A still shared across several channels is the provider's placeholder.
        # The same still twice within one channel just means the provider
        # lists one feed twice, which is not a finding.
        r["placeholder_group"] = g if spans else None
        r["placeholder"] = bool(spans)
        # Only now, with cross-channel evidence, is the verdict safe to make
        # automatically. A single stream showing a still picture is genuinely
        # ambiguous -- it may simply be a fixed camera.
        if spans and r.get("status") == "ok":
            r["status"] = "placeholder"
            r["reason"] = ("same still picture served for "
                           f"{len(group_channels[g])} different channels")
        # Kept under the old key so existing consumers keep working.
        r["duplicate_group"] = r["placeholder_group"]
        by_channel.setdefault(r["channel_key"], []).append(r)

    # Cadence is judged against the WHOLE run, which is why it happens here
    # with every record in hand rather than inside the per-channel ranking.
    house = rank_mod.dominant_cadence(records)
    if house:
        for r in records:
            c = rank_mod.cadence_of(r.get("fps"))
            r["off_cadence"] = bool(c and c != house and c != "film")
            if r["off_cadence"]:
                r["cadence"] = c
                r["house_cadence"] = house

    for key, rs in by_channel.items():
        by_channel[key] = rank_mod.rank(rs)
    return by_channel


# Backwards-compatible alias: this pass was originally (and inaccurately)
# called duplicate detection.
annotate_duplicates = annotate_placeholders
