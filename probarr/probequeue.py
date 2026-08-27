"""A serialised queue for on-demand re-probes.

Without this, the re-probe button is a loaded gun. Each click would run a probe
directly on its own request thread, so an impatient operator clicking six
buttons opens six simultaneous connections to the provider -- straight through
the connection allowance, in the one situation where exceeding it is most
confusing, because the resulting "dead stream" results look like the button
diagnosing a real fault.

So every re-probe goes through here:

  * at most `concurrency` probes run at once, taken from settings
  * launches are spaced by `gap_seconds`, so a burst of clicks becomes a
    paced sequence rather than a thundering herd
  * the same stream cannot be queued twice; a second click reports the
    position of the request already waiting
  * a stream re-probed moments ago is refused with a cooldown, because a
    fresh capture of the same instant tells you nothing new
  * pending work survives a restart, because it is written to disk as it is
    accepted -- see `journal` below

A queue that lived only in memory silently discarded everything waiting
whenever the container was recreated. That is not a rare event (every
deploy does it), and the failure is invisible: the UI is told the probe was
accepted, the restart drops it, and the operator is left watching a card
that never changes. Anything accepted is therefore journalled, and anything
still outstanding is resubmitted on the next start.
"""
import json
import os
import inspect
import threading
import time

# Re-probing the same stream more often than this is pointless: live content
# has barely moved and the provider is being hit for no new information.
COOLDOWN_SECONDS = 15

# How long to leave a lane's connection slot idle after it was genuinely
# FULL (every slot -- probes plus live viewers -- in use) and one just
# freed up, before reusing it. Real, evidenced case this exists for: a
# provider can accept a new connection into a slot that only just closed
# server-side and serve it corrupted data (decode errors, no frame ever
# produced) rather than a clean refusal -- observed directly against a
# real account, tracing back to genuine client-side connection churn, not
# a bad stream. Only applies when the lane was actually saturated; a lane
# with continuous spare capacity never pays this, launches immediately.
LANE_SETTLE_SECONDS = 5

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def _channel_of(payload):
    """The channel a job's rec_key belongs to ("channel|stream_id" -> "channel").

    Falls back to the whole rec_key (or the submit key) for a payload that
    somehow has neither -- worst case that just makes two genuinely
    unrelated jobs share a "channel" bucket and queue behind each other
    unnecessarily, never the reverse (never lets two same-channel jobs
    run concurrently by mistake).
    """
    rk = payload.get("rec_key") or payload.get("key") or ""
    return rk.split("|", 1)[0] if rk else id(payload)


class ProbeQueue:
    # Idea borrowed from Podium and StreamFlow (both open-source Dispatcharr
    # tools, see their READMEs) after comparing notes with their community:
    # a global concurrency cap treats every provider as one shared pipe, so
    # one saturated provider stalls jobs against a completely different,
    # more permissive one. `lane_limit` turns "how many probes at once" into
    # "how many at once FOR THIS PROVIDER" -- each job's payload carries an
    # optional `lane` (provider name; unset jobs share one implicit lane, so
    # this is a strict superset of the old single-queue behaviour and every
    # existing single-provider setup is unaffected).
    def __init__(self, runner, concurrency=lambda: 1, gap=lambda: 0.4,
                 journal=None, gate=lambda lane=None: None, lane_limit=None,
                 viewer_count=lambda lane: 0):
        self._runner = runner              # callable(job) -> result dict
        self._concurrency = concurrency    # callables so settings changes apply live
        self._gap = gap
        self._lock = threading.Condition()
        self._pending = []                 # job dicts, FIFO
        self._active = {}                  # key -> job
        self._recent = {}                  # key -> (finished_at, status, reason)
        self._last_launch = 0.0
        self._worker = None
        self._journal = journal
        # Returns a reason string when probing must not start, or None when
        # it may. Jobs WAIT rather than fail: the queue is holding real work
        # the operator asked for, and throwing it away because someone
        # started watching television would be the wrong answer.
        self._gate = gate
        # Determined ONCE from the callable's real signature, not guessed
        # from whether calling it raises TypeError. Real bug found on a
        # full-codebase review: the old code called self._gate(next_lane)
        # and treated ANY TypeError as "this must be a gate that predates
        # the lane argument", silently retrying with zero arguments. A
        # caller-supplied gate with a genuine bug (e.g. it does something
        # invalid with `lane` internally) raises TypeError too, and that
        # got misdiagnosed and silently swallowed the exact same way,
        # changing the queue's actual gating behaviour with nothing
        # logged anywhere to say so.
        try:
            self._gate_takes_lane = len(
                inspect.signature(gate).parameters) >= 1
        except (TypeError, ValueError):
            # Some callables (certain builtins/C-implemented callables)
            # don't expose an inspectable signature at all -- fall back to
            # the modern, documented shape rather than assuming the old one.
            self._gate_takes_lane = True
        self._blocked = None
        # callable(lane) -> int, defaults to the global concurrency for any
        # lane with no provider-specific override.
        self._lane_limit = lane_limit or (lambda lane: max(1, int(self._concurrency())))
        # callable(lane) -> live viewer count sharing this lane's connection
        # pool (e.g. someone watching via Dispatcharr) -- counted against
        # the same limit a probe would be, since it is the same provider
        # connection allowance either way.
        self._viewer_count = viewer_count
        # lane -> when a slot in it last freed up while the lane was
        # genuinely full. See LANE_SETTLE_SECONDS.
        self._lane_finished_at = {}

    # -- durability --------------------------------------------------------
    def _write_journal_locked(self):
        """Everything still owed, written as one small file.

        Rewritten whole rather than appended to: the file has to describe
        what is OUTSTANDING, and an append-only log of accepted jobs would
        replay finished work on the next start. It is never more than a few
        dozen entries, so rewriting costs nothing.
        """
        if not self._journal:
            return
        try:
            rows = [{"key": j["key"], "payload": j["payload"]}
                    for j in self._pending]
            rows += [{"key": j["key"], "payload": j["payload"]}
                     for j in self._active.values() if j["state"] == RUNNING]
            tmp = self._journal + ".tmp"
            os.makedirs(os.path.dirname(self._journal), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            os.replace(tmp, self._journal)
        except OSError:
            pass  # durability is a courtesy; never break probing over it

    def restore(self):
        """Re-queue whatever a previous process still owed.

        A job that was RUNNING when the process died is resubmitted too: the
        probe never finished, so nothing was appended for it, and re-running
        it is the only way it completes. Returns how many were restored.
        """
        if not self._journal or not os.path.exists(self._journal):
            return 0
        try:
            with open(self._journal, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            return 0
        n = 0
        for row in rows if isinstance(rows, list) else []:
            key, payload = row.get("key"), row.get("payload")
            if key and payload and self.submit(key, payload).get("accepted"):
                n += 1
        return n

    # -- public ------------------------------------------------------------
    def submit(self, key, payload):
        """Queue a probe. Returns a status dict describing what happened."""
        now = time.time()
        with self._lock:
            if key in self._active:
                return {"accepted": False, "state": self._active[key]["state"],
                        "position": self._position_locked(key),
                        "reason": "already queued"}
            last = self._recent.get(key)
            if last and (now - last[0]) < COOLDOWN_SECONDS:
                return {"accepted": False, "state": "cooldown",
                        "retry_after": round(COOLDOWN_SECONDS - (now - last[0]), 1),
                        "reason": f"re-probed {round(now - last[0])}s ago"}
            job = {"key": key, "payload": payload, "state": QUEUED,
                   "queued_at": now, "result": None}
            self._pending.append(job)
            self._active[key] = job
            self._write_journal_locked()
            self._ensure_worker_locked()
            self._lock.notify_all()
            return {"accepted": True, "state": QUEUED,
                    "position": self._position_locked(key)}

    def status(self, key):
        with self._lock:
            job = self._active.get(key)
            if job:
                return {"state": job["state"], "position": self._position_locked(key)}
            last = self._recent.get(key)
            if last:
                return {"state": last[1], "reason": last[2],
                        "age": round(time.time() - last[0], 1)}
            return {"state": "idle"}

    def snapshot(self):
        with self._lock:
            return {"blocked": self._blocked,
                    "queued": sum(1 for j in self._active.values()
                                  if j["state"] == QUEUED),
                    "running": sum(1 for j in self._active.values()
                                   if j["state"] == RUNNING),
                    "keys": {k: {"state": j["state"],
                                 "position": self._position_locked(k)}
                             for k, j in self._active.items()}}

    # -- internals ---------------------------------------------------------
    def _active_running_locked(self):
        return any(j["state"] == RUNNING for j in self._active.values())

    def _position_locked(self, key):
        for i, j in enumerate(self._pending):
            if j["key"] == key:
                return i + 1
        return 0

    def _ensure_worker_locked(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._pump, daemon=True)
            self._worker.start()

    def _pump(self):
        """Launch queued jobs, respecting concurrency and the launch gap."""
        while True:
            with self._lock:
                while not self._pending:
                    # Idle out rather than spin, so the thread costs nothing
                    # between bursts of clicks.
                    if not self._lock.wait(timeout=30) and not self._pending:
                        self._worker = None
                        return
                if not self._active_running_locked():
                    # Only checked when nothing is in flight -- a probe
                    # already running IS the connection in use, and asking
                    # then would see itself and deadlock the queue. The
                    # lane of the job that would launch next (queue is
                    # idle here, so that's simply the first one pending)
                    # is passed through so the gate can weigh a viewer
                    # against THAT provider's real concurrency, not
                    # against an assumed single connection.
                    next_lane = (self._pending[0]["payload"].get("lane") or "_default"
                                if self._pending else None)
                    try:
                        reason = (self._gate(next_lane) if self._gate_takes_lane
                                 else self._gate())
                    except Exception:
                        reason = None      # never let the check block work
                    self._blocked = reason
                    if reason:
                        self._lock.wait(timeout=15)
                        continue
                running = sum(1 for j in self._active.values() if j["state"] == RUNNING)
                global_limit = max(1, int(self._concurrency()))
                if running >= global_limit:
                    self._lock.wait(timeout=0.5)
                    continue
                gap = max(0.0, float(self._gap()))
                wait = (self._last_launch + gap) - time.time()
                if wait > 0:
                    self._lock.wait(timeout=wait)
                    continue
                # A job may only launch if BOTH the global cap and its own
                # lane's cap have room -- the global cap still bounds total
                # host load (ffmpeg processes are not free) even when lanes
                # individually have spare capacity. Scans for the first
                # pending job whose lane isn't already full, rather than
                # always taking [0], so one saturated provider's jobs queue
                # behind each other without blocking a different provider's
                # jobs sitting later in the same list.
                running_by_lane = {}
                running_channels = set()   # {(lane, channel_key)} currently in flight
                for j in self._active.values():
                    if j["state"] == RUNNING:
                        lane = j["payload"].get("lane") or "_default"
                        running_by_lane[lane] = running_by_lane.get(lane, 0) + 1
                        running_channels.add((lane, _channel_of(j["payload"])))
                job = None
                settling = False
                for candidate in self._pending:
                    lane = candidate["payload"].get("lane") or "_default"
                    limit = max(1, int(self._lane_limit(lane)))
                    used = running_by_lane.get(lane, 0) + self._viewer_count(lane)
                    if used >= limit:
                        continue   # genuinely no free slot in this lane yet
                    # Even with a free slot, never run two candidates for
                    # the SAME channel at once. Real, evidenced case: with
                    # spare lane capacity to spare, two quality-variant
                    # candidates of one channel launched in the same
                    # second and both came back corrupted (decode errors,
                    # no frame), while the exact same URL decoded cleanly
                    # moments later in complete isolation -- the provider's
                    # per-CHANNEL backend relay, not the account's overall
                    # connection count, is what can't be shared. Different
                    # channels still probe fully in parallel up to the
                    # lane's real limit; only same-channel candidates queue
                    # behind each other.
                    if (lane, _channel_of(candidate["payload"])) in running_channels:
                        continue
                    # A free slot exists. If the lane was completely full
                    # (probes plus viewers) right up until a slot just
                    # freed, give the provider LANE_SETTLE_SECONDS before
                    # reusing it -- real, evidenced case: a connection
                    # accepted too soon after the previous one closed can
                    # come back corrupted (decode errors, no frame ever
                    # produced) rather than cleanly refused. A lane that
                    # had spare capacity all along never hits this: its
                    # _lane_finished_at entry is either unset or long
                    # enough ago that the check passes immediately.
                    since_settle = time.time() - self._lane_finished_at.get(lane, 0)
                    if since_settle < LANE_SETTLE_SECONDS:
                        settling = True
                        continue
                    job = candidate
                    break
                if job is None:
                    # Either every lane with pending work is already at its
                    # own cap, or the only free slots are still settling --
                    # nothing to do until one finishes or settles.
                    self._lock.wait(timeout=0.5 if not settling else 1.0)
                    continue
                self._pending.remove(job)
                job["state"] = RUNNING
                self._last_launch = time.time()
                self._write_journal_locked()
            threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job):
        state, reason = DONE, ""
        try:
            result = self._runner(job["payload"])
            job["result"] = result
            if not result or result.get("error"):
                state = FAILED
                reason = (result or {}).get("error", "probe failed")
            else:
                reason = result.get("status", "")
        except Exception as e:                       # never kill the worker
            state, reason = FAILED, str(e)[:200]
        finally:
            with self._lock:
                lane = job["payload"].get("lane") or "_default"
                # Measured BEFORE this job is removed from _active, i.e.
                # whether the lane was completely full (this job's own slot
                # included) at the moment it finished -- that is precisely
                # the condition LANE_SETTLE_SECONDS exists to protect
                # against, and it must not apply to a lane that had spare
                # capacity all along.
                running_in_lane = sum(1 for j in self._active.values()
                                      if j["state"] == RUNNING and
                                      (j["payload"].get("lane") or "_default") == lane)
                limit = max(1, int(self._lane_limit(lane)))
                if running_in_lane + self._viewer_count(lane) >= limit:
                    self._lane_finished_at[lane] = time.time()
                job["state"] = state
                self._recent[job["key"]] = (time.time(), state, reason)
                self._active.pop(job["key"], None)
                self._write_journal_locked()
                # Bound the memory: only the cooldown window matters.
                cutoff = time.time() - (COOLDOWN_SECONDS * 20)
                for k, v in list(self._recent.items()):
                    if v[0] < cutoff:
                        self._recent.pop(k, None)
                self._lock.notify_all()
