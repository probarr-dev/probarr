"""Dispatcharr as a stream source (and, separately, as an export target).

Dispatcharr is optional throughout probarr -- it is one adapter among
several, never a requirement.

Two behaviours of its API are load-bearing and easy to get wrong:

1. The JWT access token expires in roughly 30 minutes. A verification run over
   a large catalogue on a connection-limited provider takes far longer than
   that, so a token fetched at the start of a run is dead by the time results
   are written. This client therefore re-authenticates lazily on every call
   that is about to touch the API after a gap, rather than holding one token.

2. Creating or updating a channel via the API does NOT link a logo, even
   though Dispatcharr has already imported a Logo object for the tvg-logo URL
   it saw in the M3U. `logo_id` has to be resolved and set explicitly or every
   channel silently ends up with no icon. Worse, that auto-import only ever
   happens for a URL Dispatcharr saw itself while ingesting an M3U -- a URL
   from anywhere else (a saved EPG source's own icon, a tv-logo/tv-logos
   search pick) has no Logo row at ALL, so even the lookup finds nothing.
   get_or_create_logo() below is the create half of that fix.

3. Django's own permission flags are not sufficient for write access.
   Dispatcharr layers a separate `user_level` field (0-10) on top, checked by
   its own DRF permission classes -- an account with `is_superuser=True` in
   Django can still get a flat 403 from every write endpoint if this field is
   low. Confirmed live: a freshly created superuser account was rejected
   until `user_level` was raised to match the built-in admin account (10).

4. Creating ANY custom stream (get_or_create_custom_stream, below) depends on
   a single hidden M3UAccount row -- name "custom", locked=True -- that
   Dispatcharr's own post_save signal on Stream looks up unconditionally
   (apps/channels/signals.py: set_default_m3u_account). It is normally
   created once, forever, by a data migration on first install
   (apps/m3u/migrations/0003_create_custom_account.py) and is never exposed
   in the UI as something a user manages. If an instance is ever fully wiped
   via the API (deleting every M3UAccount, treating them all as ordinary
   data) this row goes with them, and every subsequent custom-stream create
   fails with a bare HTTP 500 -- confirmed live, doing exactly that. The fix
   is to recreate it with the same fields the migration uses (name="custom",
   max_streams=0, locked=True, plus a default M3UAccountProfile), not to
   treat the 500 as a probarr bug. If you are ever resetting a Dispatcharr
   instance to a blank slate before using probarr against it, this is the
   one row worth leaving alone -- or recreating first, before any export.
"""
import re
import time
import urllib.parse

from .. import http
from .base import Stream, register

TOKEN_TTL = 20 * 60  # refresh well inside Dispatcharr's ~30 min expiry


class Dispatcharr:
    def __init__(self, base_url, username, password, timeout=30):
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token = None
        self._token_at = 0.0
        self._stream_url_map = None
        self._epgdata_map = None

    # -- auth ---------------------------------------------------------------
    @property
    def token(self):
        if self._token and (time.time() - self._token_at) < TOKEN_TTL:
            return self._token
        d = http.request(f"{self.base}/api/accounts/token/", "POST",
                         {"username": self.username, "password": self.password},
                         timeout=self.timeout)
        self._token = d["access"]
        self._token_at = time.time()
        return self._token

    # Dispatcharr throttles its own API fairly aggressively -- a real push
    # doing dozens of writes in a row, or another admin session active at
    # the same time, both trip it constantly in practice (every manual
    # workaround during this project's development ended up being some
    # variant of "wait for the stated seconds, then retry by hand"). A 429
    # is a transient condition, not a real failure, so retrying it here
    # automatically is what turns "the whole push dies because Dispatcharr
    # was momentarily busy" into "the push takes a few seconds longer".
    _MAX_429_RETRIES = 8

    def api(self, method, path, body=None):
        for attempt in range(self._MAX_429_RETRIES):
            try:
                return http.request(f"{self.base}{path}", method, body,
                                    headers={"Authorization": f"Bearer {self.token}"},
                                    timeout=self.timeout)
            except http.HttpError as e:
                if e.status != 429 or attempt == self._MAX_429_RETRIES - 1:
                    raise
                # Dispatcharr's own throttle body names the exact wait:
                # {"detail": "Request was throttled. Expected available in
                # 18 seconds."} -- honour that instead of guessing, with a
                # small fixed fallback if the body doesn't parse (format
                # changes, or a non-JSON 429 from something in front of it).
                m = re.search(r"available in (\d+(?:\.\d+)?)\s*seconds?", e.body)
                time.sleep(float(m.group(1)) + 1 if m else 5.0)

    def paged(self, path, page_size=1000):
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while True:
            d = self.api("GET", f"{path}{sep}page_size={page_size}&page={page}")
            if not d:
                break
            results = d.get("results") if isinstance(d, dict) else d
            if not results:
                break
            out.extend(results)
            if not (isinstance(d, dict) and d.get("next")):
                break
            page += 1
        return out

    # -- reading ------------------------------------------------------------
    def streams(self):
        """Every stream Dispatcharr is actually willing to use right now.

        Real feedback (Discord): using Dispatcharr as a probe SOURCE pulled
        every stream from every M3U account it had ever ingested, including
        ones the operator had switched off in Dispatcharr's own UI (`is_active
        =False` on the account -- Dispatcharr's own toggle for "stop using
        this provider without deleting it"). A disabled account's streams are
        exactly the ones an operator does NOT want probed or matched into a
        wantlist; showing them anyway meant Curate filled up with channels
        from a provider that had been turned off on purpose. Custom streams
        (probarr's own, and any created by hand) carry no m3u_account at all
        and are kept regardless -- they were never subject to an account
        toggle in the first place.
        """
        accounts = {a["id"]: a for a in self.paged("/api/m3u/accounts/")}
        return [
            Stream(id=f"dispatcharr:{s['id']}", name=s["name"], url=s["url"],
                   group=str(s.get("channel_group") or ""),
                   logo=s.get("logo_url") or "", tvg_id=s.get("tvg_id") or "",
                   source="dispatcharr", attrs={"dispatcharr_id": s["id"]})
            for s in self.paged("/api/channels/streams/")
            if s.get("m3u_account") is None
            or accounts.get(s["m3u_account"], {}).get("is_active", True)
        ]

    def channels(self):
        return self.paged("/api/channels/channels/")

    def active_lineup(self):
        """The operator's actual curated channel list, with real category names.

        channels() returns Dispatcharr's assigned/active lineup already --
        this just resolves each channel's bare `channel_group_id` against
        groups() so callers get a human name ("Movies", "24/7") instead of
        an opaque id, which is what Browse Channels' category filter needs.
        A Dispatcharr instance can carry thousands of groups from raw M3U
        ingestion that were never assigned to any channel; only ones actually
        referenced here are relevant, so no attempt is made to return the
        rest.
        """
        names = {g["id"]: g.get("name") or "" for g in self.groups()}
        out = []
        for c in self.channels():
            out.append({
                "id": c["id"], "name": c.get("name") or "",
                "group": names.get(c.get("channel_group_id"), ""),
                "tvg_id": c.get("tvg_id") or "",
            })
        return out

    def active_streams(self):
        """What Dispatcharr is serving to a viewer RIGHT NOW.

        /proxy/ts/status is the TS proxy's own live view -- {"channels": [...],
        "count": N} -- and it is the only honest answer to "is the
        subscription's connection free?". A provider that permits one
        concurrent connection gives probarr nothing at all while someone is
        watching: it serves a holding card, or refuses. Those come back as
        placeholder frames and dead streams, which look exactly like a
        genuinely bad stream and quietly poison a run's results.

        Cheap enough to ask before every probe: it is a small JSON document
        from a service already on the LAN.
        """
        d = self.api("GET", "/proxy/ts/status") or {}
        chans = d.get("channels") or []
        names = [c.get("name") or c.get("channel_name") or "?"
                 for c in chans if isinstance(c, dict)]
        return {"count": d.get("count", len(chans)), "channels": names}

    def failover_counts(self, days=7):
        """{channel_name: failover count} over the last `days`.

        Kept as the cheap, channel-level summary used for the card badge.
        See failed_streams() for which STREAM each failure actually landed
        on, which needs the fuller correlation below.
        """
        counts = {}
        for name, streams in self.failed_streams(days=days).items():
            counts[name] = sum(streams.values())
        return counts

    def failed_streams(self, days=7):
        """{channel_name: {stream_id: failure count}} over the last `days`.

        /api/core/system-events/ is Dispatcharr's own log of real playback
        events, tied to what a viewer's player actually did -- not a
        probe's 10-25s guess. A channel_failover event names only the
        CHANNEL, not which stream broke; the stream_id it names belongs to
        the switch it is paired with, which is the stream being switched
        TO, not the one that just failed. Confirmed against the raw log:
        every channel_failover is immediately preceded (within about a
        second) by a stream_switch to the replacement stream.

        So the failed stream is whichever one was actually active just
        before that pairing -- the last channel_start or stream_switch
        strictly more than a second earlier. A simple "most recent
        stream_switch" would instead credit -- or rather blame -- the
        stream that just fixed the problem.
        """
        import datetime as _dt
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
        # No documented multi-value filter -- confirmed live, a
        # comma-joined event_type returns zero rows rather than the union.
        # Fetched unfiltered (Dispatcharr's own stated max) and filtered
        # here instead.
        try:
            d = self.api("GET", "/api/core/system-events/?limit=1000")
        except Exception:
            return {}
        wanted_types = {"channel_start", "stream_switch", "channel_failover"}
        by_channel = {}
        for e in (d or {}).get("events", []):
            name = e.get("channel_name")
            if not name or e.get("event_type") not in wanted_types:
                continue
            try:
                at = _dt.datetime.fromisoformat(e["timestamp"])
            except (KeyError, ValueError):
                continue
            by_channel.setdefault(name, []).append((at, e))

        out = {}
        for name, events in by_channel.items():
            events.sort(key=lambda x: x[0])
            for i, (at, e) in enumerate(events):
                if e["event_type"] != "channel_failover" or at < cutoff:
                    continue
                prior = None
                for at2, e2 in reversed(events[:i]):
                    if (at - at2).total_seconds() <= 1:
                        continue   # the co-occurring switch, not the failed stream
                    if e2["event_type"] in ("channel_start", "stream_switch"):
                        prior = e2.get("details", {}).get("stream_id")
                        break
                if prior is not None:
                    ch = out.setdefault(name, {})
                    ch[prior] = ch.get(prior, 0) + 1
        return out

    def current_programs(self):
        """What Dispatcharr's own EPG says is airing right now, for every
        channel it has, in one call.

        The bulk endpoint deliberately exists to answer "what is on now
        everywhere" without a request per channel; used here to check
        Dispatcharr's own live EPG assignment against what probarr itself
        resolves as correct, across a whole lineup at once, not one
        channel looked up on demand.
        """
        try:
            d = self.api("POST", "/api/epg/current-programs/", {})
        except Exception:
            return []
        return d if isinstance(d, list) else []

    def proxy_stream_url(self, channel_uuid):
        """The URL a real player uses for this channel: Dispatcharr's own
        proxy, not the raw provider address behind it.

        Probing this instead of the raw stream tests the actual delivery
        pipe -- Dispatcharr's own transcode/relay, not just the provider --
        and can never disagree with what a viewer sees, because it is the
        same request a viewer's player makes. It is scoped to the CURRENT
        stream on a channel, not an arbitrary candidate: Dispatcharr proxies
        by channel, so there is no meaningful way to ask it to deliver a
        stream that is not the one actually assigned.
        """
        return f"{self.base}/proxy/ts/stream/{channel_uuid}"

    def stream(self, stream_id):
        """One stream by id. Cheap next to streams(), which on a real
        instance is a 55k-row paginated fetch -- importing a handful of
        existing channels only needs the few streams they actually use."""
        return self.api("GET", f"/api/channels/streams/{stream_id}/")

    def group_names(self):
        """{group id: name} -- channels carry the id, people read the name."""
        return {g["id"]: g.get("name", "") for g in self.groups()}

    def logos(self):
        """Every Logo Dispatcharr already knows about, full rows -- id, name,
        url. Fetched fresh (not cached on self) since dispatcharr_export.py
        calls this once per plan()/push() and then builds whatever url->id
        or id->name maps it needs from the result.
        """
        return self.paged("/api/channels/logos/")

    def get_or_create_logo(self, name, url):
        """Logo id for `url`, creating a Logo row if none exists for it yet.

        Point 2 above (creating/updating a channel never links a logo) is
        only half the story: Dispatcharr ALSO only auto-creates a Logo row
        for a URL it saw itself while ingesting an M3U. A URL from anywhere
        else -- a saved EPG source's own <icon>, a tv-logo/tv-logos search
        pick -- has no Logo row at all, so logos() never finds it and a
        channel silently ends up with no icon, exactly like an
        unlinked M3U logo would. This is the create half get_or_create_group()
        already does for groups, applied to the same problem for logos.

        Creates FIRST and only looks up on failure, rather than scanning
        the whole Logo table up front. Dispatcharr enforces a unique URL on
        Logo, so a duplicate is a clean 400 that the recovery path below
        resolves into an ordinary lookup. A pre-scan would be a full
        paginated fetch of every logo in the instance, per call -- and the
        one caller (dispatcharr_export.logo_id_for) has already established
        the URL is absent from a map built from that same endpoint, so it
        would be re-answering a question it was just handed the answer to.
        Curating logos for fifty channels turned that into fifty redundant
        full-table fetches against an API that rate-limits.
        """
        try:
            created = self.api("POST", "/api/channels/logos/",
                               {"name": name, "url": url})
            return created["id"]
        except Exception:
            # A duplicate URL (another push, a concurrent request, or a
            # caller with no prior map) lands here -- resolve it into the
            # existing row rather than failing the push. Anything else
            # re-raises once we have confirmed it was not a duplicate.
            for l in self.logos():
                if l.get("url") == url:
                    return l["id"]
            raise

    def groups(self):
        return self.paged("/api/channels/groups/")

    # -- writing --------------------------------------------------------
    #
    # Dispatcharr layers its OWN permission field on top of Django's -- a
    # user can be `is_superuser=True` in Django and still get a bare 403 from
    # every one of these endpoints, because Dispatcharr additionally checks a
    # `user_level` field (0-10) that Django knows nothing about and that
    # `is_superuser`/`is_staff` do not imply. Confirmed live: a freshly
    # created superuser account got 403 on /api/channels/groups/ until
    # `user_level` was set to 10 to match the existing admin account. If a
    # write call here returns 403, that field -- not the JWT or the Django
    # permission flags -- is almost certainly why.

    def get_or_create_group(self, name):
        """Group id for `name`, creating it if no group with that name exists."""
        for g in self.groups():
            if g.get("name", "").strip().lower() == name.strip().lower():
                return g["id"]
        created = self.api("POST", "/api/channels/groups/", {"name": name})
        return created["id"]

    def stream_url_map(self):
        """{url: stream id}, fetched once and cached for this client's lifetime.

        get_or_create_custom_stream() used to re-scan the ENTIRE stream table
        from scratch, via paginated GETs, for every single candidate it
        resolved. Fine on a small catalog; catastrophic on a real one --
        measured live against a genuine 55,938-stream Dispatcharr instance at
        ~40 streams/sec paging speed, that is a ~23 MINUTE linear scan PER
        candidate. A ~150-channel export needing up to 2 lookups each would
        never realistically finish. One upfront fetch plus a dict lookup per
        candidate turns the whole export into a few seconds of resolving.

        A fresh Dispatcharr client is created once per push (see
        client_from_spec() usage in web.py's _run_export), so this cache's
        lifetime already matches "one export" -- no explicit invalidation
        needed between pushes.
        """
        if self._stream_url_map is None:
            native, custom = {}, {}
            for s in self.paged("/api/channels/streams/"):
                url = s.get("url")
                if not url:
                    continue
                (custom if s.get("is_custom") else native)[url] = s["id"]
            # A native (Dispatcharr's own M3U/Xtream-parsed) stream must
            # always win over a custom one sharing the same URL -- never
            # whichever happened to paginate last. Real, live case this
            # fixes: a channel pushed before its provider had a correctly
            # configured Dispatcharr account still had its old custom
            # stream sitting around after the account was fixed. Once
            # Dispatcharr's own refresh produced a NATIVE stream with the
            # identical URL, a plain last-write-wins dict comprehension
            # picked whichever of the two came later in pagination order,
            # essentially at random -- confirmed live: one channel's four
            # candidates split 3 custom / 1 native despite all four
            # existing natively in the corrected account by push time.
            # Native winning unconditionally is exactly what
            # get_or_create_custom_stream() exists to prefer in the first
            # place (see its own docstring); staying on a stale custom
            # stream once a native one exists is precisely the outcome
            # docs/design/per-provider-m3u-accounts.md was written to get
            # away from. The stale custom stream itself is left in place,
            # not deleted -- dispatcharr_export.py's own documented
            # never-delete policy -- it just stops being referenced by any
            # channel once the next push runs.
            self._stream_url_map = {**custom, **native}
        return self._stream_url_map

    def _tighten_max_streams(self, acct, limit, log, why):
        """Shared ratchet: PATCH `acct.max_streams` down to `limit`, never up.

        Used by both enforce_custom_stream_limit() (the one shared "custom"
        account) and enforce_provider_stream_limit() (a real per-provider
        account, see below) -- same operation, same safety property, two
        different accounts it can apply to.
        """
        current = acct.get("max_streams") or 0
        if current == 0 or current > limit:
            self.api("PATCH", f"/api/m3u/accounts/{acct['id']}/",
                     {"max_streams": limit})
            log(f"  tightened Dispatcharr's {why} max_streams "
               f"{current} -> {limit} (this run's provider connection limit)")

    def enforce_custom_stream_limit(self, limit, log=None):
        """Tighten (never loosen) Dispatcharr's shared "custom" M3U
        account's max_streams to at most `limit`.

        Real gap this closes: get_or_create_custom_stream() creates every
        custom stream under Dispatcharr's one special, locked "custom"
        account (required -- Dispatcharr has no per-channel or per-source
        way to create a custom stream otherwise), completely independent of
        whatever REAL provider that stream's URL actually belongs to. That
        account defaults to max_streams=0 (unlimited), and its settings are
        hidden from Dispatcharr's normal M3U-account edit UI (it renders as
        "locked"). Confirmed live: with it left at 0, Dispatcharr enforced
        NO limit at all on channels pushed this way, even though the real
        upstream provider allows exactly 1 concurrent connection --
        completely defeating the whole reason concurrency=1 exists
        throughout this project. The API can still patch it despite the UI
        hiding it; this makes that happen automatically on every push
        instead of relying on someone noticing and fixing it by hand.

        Deliberately only ever tightens. Every probarr provider that has
        ever pushed a custom stream shares this ONE account -- there is no
        way to give per-provider limits within it -- so silently RAISING
        the limit because one run's provider allows more would let that
        run's push loosen protection for every other provider's custom
        streams too. Ratcheting down only, never up, converges to the most
        conservative limit any pushing provider has stated, which is the
        only safe default across an account nothing else can meaningfully
        scope.

        Still needed even once a provider has a real account (see
        enforce_provider_stream_limit): get_or_create_custom_stream()
        already prefers an existing stream by URL over creating a new one
        (see its docstring), so once a provider's real M3U account has been
        refreshed by Dispatcharr, most candidates land there automatically
        with no code change required. But a URL Dispatcharr's own parse
        doesn't have an exact match for -- confirmed live this is real, not
        hypothetical, at roughly a 4% rate on one genuine 43,888-URL catalog
        -- still falls through to a custom stream under the shared account,
        so its limit still needs to be correct too.
        """
        log = log or (lambda msg: None)
        if not limit or limit <= 0:
            return  # "unlimited" is not a limit worth enforcing down to
        acct = next((a for a in self.api("GET", "/api/m3u/accounts/")
                    if a.get("name") == "custom"), None)
        if not acct:
            return
        self._tighten_max_streams(acct, limit, log, "shared 'custom' M3U account")

    def find_account_for_source(self, spec):
        """The real Dispatcharr M3U account whose server_url is `spec`, if
        Dispatcharr has one -- the account get_or_create_custom_stream()
        would already be finding native streams in, if this provider has
        ever been set up (or corrected) to point at the same source probarr
        itself is configured with.

        Matched by EXACT string equality only, deliberately. A looser match
        (same host, ignoring the query string credentials) risks silently
        tightening the wrong account's limit -- Dispatcharr has no field
        that says "this account is probarr's mybunny provider", only
        whatever server_url happens to be saved, so exact match is the only
        comparison that cannot produce a false positive. If nothing matches
        exactly, the honest answer is "no such account exists (yet)", not a
        guess.

        `spec` falsy short-circuits to "no match" rather than falling through
        to the comparison below -- an empty/missing spec (a CLI-driven run
        with no saved provider behind it, say) would otherwise equal a real
        account's own `server_url: None` (the shared "custom" account has
        exactly that) purely by coincidence, and silently tighten the wrong
        account.
        """
        if not spec:
            return None
        return next((a for a in self.api("GET", "/api/m3u/accounts/")
                    if a.get("server_url") == spec), None)

    def enforce_provider_stream_limit(self, spec, limit, log=None):
        """Tighten (never loosen) THIS provider's own real M3U account's
        max_streams to at most `limit`, if Dispatcharr has one matching
        `spec` (probarr's own provider spec -- see find_account_for_source).

        This is the actual point of docs/design/per-provider-m3u-accounts.md:
        unlike the shared "custom" account (enforce_custom_stream_limit,
        above), a provider's own real M3U/Xtream account's max_streams is
        enforced by Dispatcharr against EVERYTHING drawn from it -- Live TV
        channel playback and VOD (Movies/TV Shows) alike -- not just
        whatever probarr happens to push. Ratcheting only, same as the
        shared account: this account is not shared between different
        probarr providers the way "custom" is, but it may still have been
        deliberately set more conservatively for reasons probarr doesn't
        know about (a paid tier change, a household policy), and silently
        raising it is never the safe default.

        A no-op, not an error, when no matching account exists -- most
        providers won't have one until a Dispatcharr account is created or
        corrected to point at the same source (see the design doc's "step
        zero"). The shared "custom" account keeps providing the safety net
        for that case.
        """
        log = log or (lambda msg: None)
        if not limit or limit <= 0:
            return
        acct = self.find_account_for_source(spec)
        if not acct:
            return
        self._tighten_max_streams(acct, limit, log, f"'{acct['name']}' M3U account")

    def get_or_create_account_for_source(self, spec, name, log=None):
        """The real Dispatcharr M3U account matching `spec`, creating one if
        Dispatcharr doesn't have it yet -- the automated version of the "step
        zero" docs/design/per-provider-m3u-accounts.md called out as a manual,
        by-hand prerequisite (`BunnyCustom`'s server_url, corrected via a raw
        API call before any of this existed).

        Only attempted for a plain M3U/Xtream playlist URL (`spec` starting
        with http:// or https://) -- `dispatcharr://` and other non-URL specs
        have no `server_url` string Dispatcharr could ever match verbatim, so
        creating an account for one would just be a namespace with nothing to
        parse. A no-op for those, same as find_account_for_source() already
        is when nothing matches.

        Deliberately never given a URL-less "stub" server_url -- that shape
        was ruled out during scoping (see the design doc's "What's confirmed
        feasible" section): creating an M3U account triggers an immediate,
        one-time refresh attempt regardless of its periodic-refresh setting,
        and an empty server_url turns that into a user-visible "downloading
        failed" notification the moment it's created. Passing `spec` itself
        (always a real, working playlist URL here) means that first refresh
        should succeed instead, though this specific path -- account
        CREATION, as opposed to correcting an existing one's URL by hand --
        has not itself been exercised against a live instance; confirm this
        before relying on it against a Dispatcharr install that alerts on
        M3U failures.

        Only ever CREATES, never renames or re-points an existing account:
        naming collisions and provider renames/credential rotation are
        still-open questions in the design doc (see "Naming/collision"), and
        guessing which existing account "must be" this provider's based on
        name alone risks re-pointing the wrong one. If an account already
        exists under `name` but with a different server_url, a second,
        differently-named account is NOT created either -- Dispatcharr
        enforces unique M3U account names, so that POST would just fail;
        surfaced to the caller via `log` rather than swallowed, since the
        real fix (renaming or correcting the stale account) is a decision
        for a person, not something to guess at here.
        """
        log = log or (lambda msg: None)
        if not spec or not spec.startswith(("http://", "https://")):
            return None
        acct = self.find_account_for_source(spec)
        if acct:
            return acct
        try:
            created = self.api("POST", "/api/m3u/accounts/",
                               {"name": name, "server_url": spec, "is_active": True})
        except http.HttpError as e:
            log(f"  could not create a Dispatcharr M3U account for "
               f"'{name}': {e}")
            return None
        log(f"  created Dispatcharr M3U account '{name}' for its own "
           f"provider (server_url matched, was missing before this push)")
        return created

    def get_or_create_custom_stream(self, name, url):
        """Dispatcharr stream id for `url`, creating a custom stream if needed.

        Needed for exporting candidates that were never Dispatcharr's own --
        probed from a plain M3U, or from a DIFFERENT Dispatcharr instance.
        `channel.streams` only accepts ids from THIS instance's Stream table,
        so an external URL has to become a real Stream row here first.
        Dispatcharr supports exactly this via `is_custom: true`, decoupled
        from any M3U account (confirmed live: created a stream with only
        name+url+is_custom set, no m3u_account, and it worked normally).

        Matched by url first so re-running an export is idempotent -- without
        this, every re-export would create a fresh duplicate custom stream
        for the same channel, and the lineup would grow forever.
        """
        m = self.stream_url_map()
        sid = m.get(url)
        if sid is not None:
            return sid
        created = self.api("POST", "/api/channels/streams/",
                           {"name": name, "url": url, "is_custom": True})
        # Keep the cache correct for the rest of THIS export -- two different
        # curated channels can share a candidate's URL (e.g. a shared
        # fallback), and without this the second one would create a
        # duplicate stream instead of reusing the one just made.
        m[url] = created["id"]
        return created["id"]

    def create_channel(self, payload):
        return self.api("POST", "/api/channels/channels/", payload)

    def update_channel(self, channel_id, payload):
        return self.api("PATCH", f"/api/channels/channels/{channel_id}/", payload)

    def match_epg(self, channel_ids):
        if not channel_ids:
            return
        self.api("POST", "/api/channels/channels/match-epg/",
                 {"channel_ids": channel_ids})

    def get_or_create_epg_source(self, name, url):
        """Dispatcharr EPG source id for `name`, creating one if it doesn't
        exist yet, and kicking off an import for a freshly-created one.

        A probarr-saved EPG source (the ones Curate's "Check EPG" compares
        against) is only useful to DISPATCHARR once Dispatcharr itself knows
        about it too -- a curator's per-channel EPG choice has nothing on the
        Dispatcharr side to link to otherwise. The explicit import call
        matters: a new source parses on its own schedule (refresh_interval,
        up to 24h), and without kicking it immediately, epgdata_map() right
        after creation would find zero rows for it.
        """
        for s in self.api("GET", "/api/epg/sources/"):
            if s.get("name", "").strip().lower() == name.strip().lower():
                return s["id"]
        created = self.api("POST", "/api/epg/sources/",
                           {"name": name, "source_type": "xmltv", "url": url,
                            "is_active": True})
        self.api("POST", "/api/epg/import/", {"id": created["id"]})
        return created["id"]

    def epgdata_map(self):
        """{(epg_source_id, tvg_id): epgdata_id}, fetched once and cached.

        ?epg_source=<id> on this endpoint is silently ignored by Dispatcharr
        (confirmed live: filtered and unfiltered requests returned identical
        results), so a full fetch plus a client-side filter is the only
        reliable way to look one up. Cheap regardless -- ~6,600 rows in ~1s
        on a real instance, nothing like the streams table's scale that made
        stream_url_map() necessary in the first place.
        """
        if self._epgdata_map is None:
            self._epgdata_map = {(d.get("epg_source"), d.get("tvg_id")): d["id"]
                                 for d in self.paged("/api/epg/epgdata/")}
        return self._epgdata_map


def client_from_spec(spec: str) -> "Dispatcharr":
    """Build a Dispatcharr client from a dispatcharr://user:pass@host:port spec.

    Shared by the read path (load(), below) and the export path
    (dispatcharr_export.py), so a saved Providers entry can serve as both a
    source to probe and a target to push curated results back into using
    exactly the same connection.
    """
    u = urllib.parse.urlparse(spec)
    scheme = "https" if u.scheme == "dispatcharrs" else "http"
    base = f"{scheme}://{u.hostname}:{u.port or 9191}"
    return Dispatcharr(base, urllib.parse.unquote(u.username or ""),
                       urllib.parse.unquote(u.password or ""))


def base_url_of(spec: str) -> str:
    """The bare host:port a dispatcharr:// spec points at, for identity
    comparison -- e.g. deciding whether a run's source and an export target
    are the SAME instance, in which case a candidate's stream id can be
    reused directly instead of creating a duplicate custom stream."""
    u = urllib.parse.urlparse(spec)
    return f"{u.hostname}:{u.port or 9191}".lower()


@register("dispatcharr")
def load(spec: str, **_):
    """dispatcharr://user:pass@host:9191"""
    return client_from_spec(spec).streams()
