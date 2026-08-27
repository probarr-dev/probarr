"""Run storage: incremental, resumable, crash-safe.

Every probe result is appended to disk the moment it exists.

This is a hard-won rule rather than a style choice. An earlier version of this
logic collected results in memory and applied them in one batch at the end; a
single unhandled ffmpeg timeout partway through therefore discarded an hour of
already-correct verification. On a provider that permits one connection at a
time, re-running is measured in hours, so losing computed work is the most
expensive failure mode there is.

Consequences of the append-only design:
  - a crash loses at most the one in-flight probe
  - a run can be resumed, skipping anything already verified
  - the contact sheet can be generated from a partial run
"""
import json
import os
import shutil
import time


class InvalidRunId(ValueError):
    """A run id that could name something other than a direct child of the
    run root. A ValueError subclass so existing broad handlers still catch
    it, but its own type so the web layer can answer 400 for THIS and not
    for every other ValueError in the codebase -- json.JSONDecodeError is a
    ValueError too, and reporting a corrupt run.json as "bad request" tells
    the operator the wrong thing entirely.
    """


class RunStore:
    def __init__(self, root, run_id=None, create=None):
        """`create` decides whether this run's subdirectories are made now.

        Default (None) means "only if this run already exists, or is brand
        new (no id given)". That is deliberately NOT the old behaviour of
        always creating them: a run id arrives from a URL on nearly every
        read path, and unconditionally os.makedirs'ing four directories
        under it meant a single unauthenticated GET to
        /run/<anything>/thumbs/x.jpg created directories on disk. Nothing
        bounded that, so a crawler could exhaust inodes. Reported by a
        reviewer, and confirmed by doing it to a live instance.

        Callers that genuinely create a run (runner.start_run) pass
        create=True; everything else reads, and a read of a run that does
        not exist should leave the disk exactly as it found it.
        """
        self.root = os.path.abspath(root)
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        # A run id becomes a directory name, so this is a security boundary
        # rather than tidiness -- the same reasoning wantlist.safe_name()
        # already applies to wantlist names, and that delete() has always
        # applied to its own run id. Rejected rather than sanitised: a
        # silently-rewritten id would address a DIFFERENT run than the
        # caller asked for, which is worse than an error.
        if (os.sep in self.run_id or (os.altsep and os.altsep in self.run_id)
                or self.run_id in (os.curdir, os.pardir)
                or self.run_id.startswith(".")):
            raise InvalidRunId(f"invalid run id: {run_id!r}")
        self.dir = os.path.join(self.root, self.run_id)
        self.thumbs = os.path.join(self.dir, "thumbs")
        self.frames = os.path.join(self.dir, "frames")
        self.crops = os.path.join(self.dir, "crops")
        self.clips = os.path.join(self.dir, "clips")
        if create is None:
            create = run_id is None or os.path.isdir(self.dir)
        if create:
            self._ensure_dirs()
        self.selection_path = os.path.join(self.dir, "selection.json")
        self.wantlist_path = os.path.join(self.dir, "wantlist.json")
        self.results_path = os.path.join(self.dir, "results.jsonl")
        self.meta_path = os.path.join(self.dir, "run.json")
        self.push_status_path = os.path.join(self.dir, "push_status.json")
        self.removals_path = os.path.join(self.dir, "removals.json")
        self.excluded_path = os.path.join(self.dir, "excluded_streams.json")

    def _atomic_write_json(self, path, payload):
        """Write JSON via a temp file, fsync, and an atomic replace --
        cleaning up the temp file if anything goes wrong along the way.

        Consolidates what used to be six separate hand-rolled copies of
        "tmp file + os.replace" in this class. Found on a full-codebase
        review: only the wantlist writer (added later, after a real
        data-loss incident -- see its own history) had grown the fsync and
        the on-failure cleanup; the other five (meta, removals, excluded,
        selection, push_status) still had the plain version, so the same
        class of bug -- a crash or full disk mid-write leaving a stale
        .tmp file, or a replace that isn't durable without an fsync first
        -- was still fully reachable through any of them. One
        implementation now, so a future hardening only has to happen once.
        """
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _ensure_dirs(self):
        """Make this run's directories. Called from the constructor only for
        a run that exists (or is being created), and otherwise from each
        WRITE below -- which is the whole point of the split: writing is a
        legitimate reason to bring a run into existence, reading never is.
        Anything reaching a write has already gone through the real request
        path; a bare GET for a nonexistent run gets nowhere near one.
        """
        for d in (self.thumbs, self.frames, self.crops, self.clips):
            os.makedirs(d, exist_ok=True)

    # -- meta ---------------------------------------------------------------
    def write_meta(self, meta: dict):
        self._ensure_dirs()
        meta = {**meta, "run_id": self.run_id, "updated": time.time()}
        self._atomic_write_json(self.meta_path, meta)

    def read_meta(self):
        if not os.path.exists(self.meta_path):
            return {}
        with open(self.meta_path) as f:
            return json.load(f)

    # -- results ------------------------------------------------------------
    def append(self, record: dict):
        """Append one probe result and flush it to the OS immediately."""
        self._ensure_dirs()
        with open(self.results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def load(self, dedupe=True):
        """All results so far. Tolerates a truncated final line from a hard kill.

        The file stays strictly append-only -- that is what makes a crash cost
        at most one probe. Re-probing a stream therefore appends a *second*
        record for it rather than rewriting the first, and the newest record
        for a given probe wins. Without this, a re-probed stream would appear
        twice in the UI, once with its stale result.
        """
        out = []
        if not os.path.exists(self.results_path):
            return out
        with open(self.results_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # partial write at the moment of a crash
        if not dedupe:
            return out
        latest = {}
        for r in out:
            key = r.get("rec_key") or f"{r.get('channel_key')}|{r.get('stream_id')}"
            latest[key] = r          # later lines overwrite earlier ones
        return list(latest.values())

    def drop_channel(self, channel_key):
        """Remove every trace of one channel from this run.

        The results file is strictly append-only everywhere else -- that is
        what makes a crash cost at most one probe -- so rewriting it is a
        deliberate, narrow exception for an explicit destructive action the
        operator asked for, not something any automated path does. Written
        via a temp file and atomic replace so an interruption leaves either
        the old file or the new one, never a half-written list of results.

        Returns how many probe records were removed.
        """
        rows = self.load(dedupe=False)
        keep = [r for r in rows if r.get("channel_key") != channel_key]
        removed = len(rows) - len(keep)
        if removed:
            tmp = self.results_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for r in keep:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.results_path)

        # Captured images for those probes, so a re-add later cannot show a
        # stale frame from the previous life of the channel.
        for r in rows:
            if r.get("channel_key") != channel_key:
                continue
            rk = r.get("rec_key") or f"{channel_key}|{r.get('stream_id')}"
            for path in (self.thumb_path(rk), self.frame_path(rk),
                        self.crop_path(rk), self.clip_path(rk)):
                try:
                    os.remove(path)
                except OSError:
                    pass

        want = self.read_wantlist()
        wanted = [w for w in (want.get("wanted") or []) if w.get("key") != channel_key]
        missing = [w for w in (want.get("missing") or []) if w.get("key") != channel_key]
        self.write_wantlist_raw(wanted, missing)

        sel = self.read_selection()
        if channel_key in sel:
            sel.pop(channel_key)
            self.write_selection(sel)
        return removed

    # -- pending removals ---------------------------------------------------
    #
    # A channel removed from the run is gone from here immediately, but it is
    # still sitting in Dispatcharr. Deleting it there is a push-time action,
    # not a click-time one: everything else in this tool is curate-locally,
    # review-the-diff, then push, and a Remove button that reached out and
    # destroyed a live channel the instant it was clicked was the one action
    # that broke that model -- with no preview and no undo.

    def read_removals(self):
        if not os.path.exists(self.removals_path):
            return []
        try:
            with open(self.removals_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def write_removals(self, items):
        self._ensure_dirs()
        self._atomic_write_json(self.removals_path, items)

    def add_removal(self, channel_key, number, name):
        """Record that this channel should be deleted from Dispatcharr on the
        next push. Keyed by number, because that is how the exporter
        identifies a channel there."""
        items = [r for r in self.read_removals() if r.get("key") != channel_key]
        items.append({"key": channel_key, "number": number, "name": name,
                      "requested": time.time()})
        self.write_removals(items)
        return items

    def clear_removal(self, channel_key):
        items = [r for r in self.read_removals() if r.get("key") != channel_key]
        self.write_removals(items)
        return items

    # -- excluded streams -----------------------------------------------------
    #
    # A deleted stream's URL is untouched and its provider entry stays in the
    # catalogue, so "Delete stream" only ever removes it from THIS channel --
    # Find streams' free search can and will surface the exact same stream
    # again later, with no memory of why it was rejected. This is that memory:
    # a note attached to the (channel, stream) pair that survives the delete,
    # so a person looking a second time sees why before probing it again.

    def read_excluded(self):
        if not os.path.exists(self.excluded_path):
            return {}
        try:
            with open(self.excluded_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_excluded(self, items):
        self._ensure_dirs()
        self._atomic_write_json(self.excluded_path, items)

    def add_excluded(self, channel_key, stream_id, name, reason):
        """Note that `stream_id` was deliberately deleted from `channel_key`,
        keyed the same way a candidate's rec_key is (channel|stream), so
        Find streams can look this up by exactly the id it is about to offer.
        """
        items = self.read_excluded()
        items[f"{channel_key}|{stream_id}"] = {
            "name": name, "reason": reason or "", "at": time.time()}
        self.write_excluded(items)
        return items

    def clear_excluded(self, channel_key, stream_id):
        """Forget an exclusion note -- for when a stream was wrongly flagged,
        or a provider fix means it is genuinely worth trying again."""
        items = self.read_excluded()
        items.pop(f"{channel_key}|{stream_id}", None)
        self.write_excluded(items)
        return items

    def clear_images(self):
        """Delete every captured thumb, frame, crop and clip. Results and
        every curated decision are untouched -- only the pictures go, and a
        candidate shows "no frame" until it is next probed or re-probed.

        Exists because images are the one thing in a run that only grows:
        a genuinely long-lived lineup accumulates a capture per candidate
        per re-probe forever, with nothing that ever prunes it, and no
        result is lost by clearing them since the results log is the
        record of truth -- the pictures are illustration.
        """
        removed = 0
        for d in (self.thumbs, self.frames, self.crops, self.clips):
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                try:
                    os.remove(os.path.join(d, name))
                    removed += 1
                except OSError:
                    pass
        return removed

    def drop_stream(self, rec_key):
        """Remove ONE candidate from a channel: its results and its images.

        The counterpart to attaching a stream by hand. A pool can carry a
        stream that is simply not this channel -- a wrong-country feed, a
        near-duplicate, something the search attached that turned out to be
        somebody else's -- and leaving it there means re-reading and
        re-rejecting it on every pass.

        Same deliberate exception to append-only as drop_channel: an explicit
        destructive action the operator asked for, written via a temp file
        and atomic replace.
        """
        rows = self.load(dedupe=False)
        keep = [r for r in rows
                if (r.get("rec_key") or
                    f"{r.get('channel_key')}|{r.get('stream_id')}") != rec_key]
        removed = len(rows) - len(keep)
        if not removed:
            return 0
        tmp = self.results_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.results_path)
        for path in (self.thumb_path(rec_key), self.frame_path(rec_key),
                    self.crop_path(rec_key), self.clip_path(rec_key)):
            try:
                os.remove(path)
            except OSError:
                pass
        # A selection pointing at a stream that no longer exists would
        # silently fall back to the auto-pick with no explanation.
        sel = self.read_selection()
        touched = False
        for key, pick in sel.items():
            for field in ("primary", "fallback"):
                if pick.get(field) == rec_key:
                    pick.pop(field)
                    touched = True
        if touched:
            self.write_selection(sel)
        return removed

    def duplicate_channel(self, channel_key, new_key, number, group=None):
        """Copy a channel within this run so it can live in two groups.

        Dispatcharr identifies a channel by its NUMBER, so a second copy at
        a different number is a genuinely separate channel there -- which is
        what lets the same feed appear in, say, both "General" and "F1"
        without one push undoing the other. The copy keeps the original's
        name (so the guide still matches) and its probe results, so it needs
        no re-probing and no extra provider connections.

        Returns how many probe records were copied.
        """
        rows = [r for r in self.load() if r.get("channel_key") == channel_key]
        copied = 0
        for r in rows:
            old_rk = r.get("rec_key") or f"{channel_key}|{r.get('stream_id')}"
            new_rk = f"{new_key}|{r.get('stream_id')}"
            for getter in (self.thumb_path, self.frame_path,
                          self.crop_path, self.clip_path):
                src, dst = getter(old_rk), getter(new_rk)
                if os.path.exists(src):
                    try:
                        shutil.copyfile(src, dst)
                    except OSError:
                        pass
            fresh = {**r, "channel_key": new_key, "rec_key": new_rk}
            # Image paths are stored relative and derived from rec_key, so
            # they must be re-pointed or the copy would display the
            # original's frames and re-probing it would write past them.
            for field, sub in (("thumb", "thumbs"), ("frame", "frames"),
                              ("crop", "crops"), ("clip", "clips")):
                if r.get(field):
                    ext = ".mp4" if field == "clip" else ".jpg"
                    fresh[field] = f"{sub}/{self.safe_name(new_rk)}{ext}"
            self.append(fresh)
            copied += 1

        want = self.read_wantlist()
        wanted = list(want.get("wanted") or [])
        orig = next((w for w in wanted if w.get("key") == channel_key), None)
        wanted.append({"number": number,
                      "name": (orig or {}).get("name") or new_key,
                      "tvg_id": (orig or {}).get("tvg_id") or "",
                      "key": new_key})
        self.write_wantlist_raw(wanted, want.get("missing") or [])

        # Written even when the original had no selection entry of its own:
        # the caller may have asked for a group, and dropping it just
        # because the source channel was still on its auto-pick would
        # silently ignore the whole point of duplicating it.
        sel = self.read_selection()
        copy = dict(sel.get(channel_key) or {})
        # Picks are per-channel-key, so re-point them at the copy's own
        # rec_keys rather than leaving them aimed at the original's.
        for f in ("primary", "fallback"):
            if copy.get(f) and str(copy[f]).startswith(channel_key + "|"):
                copy[f] = new_key + str(copy[f])[len(channel_key):]
        copy["confirmed"] = False
        copy.setdefault("include", True)
        if group is not None:
            copy["group"] = group or None
        sel[new_key] = copy
        self.write_selection(sel)
        return copied

    def done_ids(self):
        """Probes already completed, as 'channel_key|stream_id'."""
        out = set()
        for r in self.load():
            if "rec_key" in r:
                out.add(r["rec_key"])
            elif "channel_key" in r and "stream_id" in r:
                out.add(f"{r['channel_key']}|{r['stream_id']}")
        return out

    @staticmethod
    def safe_name(rec_key):
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in rec_key)

    def thumb_path(self, rec_key):
        self._ensure_dirs()
        return os.path.join(self.thumbs, f"{self.safe_name(rec_key)}.jpg")

    def frame_path(self, rec_key):
        self._ensure_dirs()
        return os.path.join(self.frames, f"{self.safe_name(rec_key)}.jpg")

    def crop_path(self, rec_key):
        self._ensure_dirs()
        return os.path.join(self.crops, f"{self.safe_name(rec_key)}.jpg")

    def clip_path(self, rec_key):
        self._ensure_dirs()
        return os.path.join(self.clips, f"{self.safe_name(rec_key)}.mp4")

    # -- curation state -----------------------------------------------------
    def write_selection(self, selection: dict):
        """Persist the curator's picks server-side.

        Kept on the server rather than only in browser storage so a selection
        survives a different browser, a different machine, and clearing site
        data -- it represents real human effort that would be tedious to redo.
        """
        self._ensure_dirs()
        self._atomic_write_json(self.selection_path, selection)

    def read_selection(self):
        if not os.path.exists(self.selection_path):
            return {}
        try:
            with open(self.selection_path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            return {}

    # -- Dispatcharr export status -------------------------------------------
    def write_push_status(self, status: dict):
        self._ensure_dirs()
        """Persist Dispatcharr export progress server-side, same reasoning as
        write_selection(): a push previously lived entirely in one browser
        tab's in-flight fetch, with no way to tell "still going" from "gave
        up" from a different tab, a page reload, or from outside the browser
        entirely. Written on every progress tick, not just at completion, so
        a poller sees real-time movement rather than a single jump at the end.
        """
        status = {**status, "run_id": self.run_id, "updated": time.time()}
        self._atomic_write_json(self.push_status_path, status)

    def read_push_status(self):
        if not os.path.exists(self.push_status_path):
            return None
        try:
            with open(self.push_status_path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            return None

    def _write_wantlist_atomic(self, payload):
        """Write the wantlist via _atomic_write_json().

        The wantlist is a bad one to lose: it holds each channel's NUMBER
        and NAME, and _resolve_curated() skips any channel without a
        number from every export -- so a half-written file does not fail
        loudly, it silently drops channels from the M3U and from the
        Dispatcharr push. Worse, read_wantlist() treats unparseable JSON
        as an empty wantlist, so a truncated write reads back as "nothing
        was wanted" rather than as an error. This was the first writer
        hardened with fsync + on-failure cleanup; _atomic_write_json()
        below is that same hardening, now shared by every writer in this
        class instead of being this one's alone.
        """
        self._atomic_write_json(self.wantlist_path, payload)

    def write_wantlist(self, wanted, missing):
        self._ensure_dirs()
        self._write_wantlist_atomic(
            {"wanted": [w.as_dict() for w in wanted],
             "missing": [w.as_dict() for w in missing]})

    def write_wantlist_raw(self, wanted, missing):
        """Write an already-plain-dict wantlist.

        write_wantlist() takes the parser's objects and calls as_dict() on
        them; channels added from the provider catalogue are already plain
        dicts (they never went through the wantlist file), so they need a
        way in that does not require reconstructing those objects just to
        immediately serialise them again.
        """
        self._ensure_dirs()
        self._write_wantlist_atomic({"wanted": wanted, "missing": missing})

    def read_wantlist(self):
        if not os.path.exists(self.wantlist_path):
            return {"wanted": [], "missing": []}
        try:
            with open(self.wantlist_path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            return {"wanted": [], "missing": []}

    @classmethod
    def list_runs(cls, root):
        if not os.path.isdir(root):
            return []
        runs = []
        for name in sorted(os.listdir(root), reverse=True):
            d = os.path.join(root, name)
            if os.path.isdir(d) and os.path.exists(os.path.join(d, "run.json")):
                with open(os.path.join(d, "run.json")) as f:
                    try:
                        runs.append(json.load(f))
                    except ValueError:
                        pass
        return runs

    @classmethod
    def latest(cls, root):
        runs = cls.list_runs(root)
        return cls(root, runs[0]["run_id"]) if runs else None

    @classmethod
    def delete(cls, root, run_id):
        """Permanently remove a run: results, thumbnails, frames, everything.

        run_id typically arrives from a URL, and this is a destructive,
        irreversible operation, so the resulting path is confirmed to
        actually be a direct child of `root` before anything is removed --
        the same defensive check already used for serving thumbnails,
        applied here because the consequence of getting it wrong is deletion
        rather than an information leak.
        """
        root_real = os.path.realpath(root)
        target = os.path.realpath(os.path.join(root, run_id))
        if target == root_real or not target.startswith(root_real + os.sep):
            return False
        if not os.path.isdir(target):
            return False
        if not os.path.exists(os.path.join(target, "run.json")):
            # Refuse anything that doesn't look like a run directory this
            # class actually created -- cheap insurance against run_id being
            # some unrelated path component that happens to satisfy the
            # containment check above.
            return False
        shutil.rmtree(target)
        return True
