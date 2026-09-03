# Changelog

Not every internal commit — the notable, user-visible stuff.

## Unreleased

### Renamed: probarr → ChannelIQ
Dropping the `-arr` suffix. Package, CLI, env vars, Docker image internals,
docs and UI branding all renamed. Both `python3 -m probarr` and
`python3 -m channeliq` keep working (as do `PROBARR_*` env vars alongside
the new `CHANNELIQ_*` ones), after a rough first hour where the documented
cron/script invocation broke on the first pull — sorry about that, fixed
properly rather than reverted. New retro, diagnostic-icon-styled favicon,
now also shown inline in the topbar next to the wordmark.

### Ranking stability ("Changed" alert flip-flop)
- Bitrate ranking now compares each candidate against the channel's own
  *currently confirmed pick*, not a fixed tolerance grid — a rival within
  ~15% of the pick's bitrate no longer contests it on bitrate alone, and a
  real difference still decides outright.
- Tightened bitrate tolerance from 35% → 15%: the old value was inherited
  from an earlier bucket-based approach and was letting real ~20-30%
  differences get swallowed and decided by a minor codec tiebreak instead,
  ahead of corruption count.
- The "Changed" box is always visible again (not tucked behind a button),
  and each channel gets its own **Dismiss** — acknowledges the exact
  current text without silencing a genuinely different future change.

### Runs list
- **Needs you** / **Changed** health pills per run, computed server-side so
  they always agree with what Curate itself would show.
- Runs actually needing a look sort to the top; the topbar rolls up a
  "N need you" total so the whole picture is visible without opening
  anything.

### Curate
- Channel list is now grouped under collapsible headers (same group used
  everywhere else), each with a "select all in group" checkbox feeding the
  existing bulk-action mechanism.
- Bulk edit page gained an opt-in **Edit Mode**: batches Set group/Set EPG
  source/Exclude/Clear watermark into a local undo/redo stack instead of
  saving each one immediately, with Commit/Discard to close it out.

### Failover depth: probing and pushing now agree
Probing stopped collecting candidates once a channel had **2** clean ones,
while the push wanted the top **4** — so an uncurated channel could never
offer more than two streams however many the provider actually listed. This
is what reached us as "is it limited to 2 streams per channel?", and what a
run log was showing as `skipped X: already has 2 clean candidate(s)`. Both
ends now read one constant (`rank.FALLBACK_DEPTH`), with a test that fails
if they ever drift again.

Runs made before this keep whatever they probed; a re-verify picks up the
extra candidates.

### Runs now warn when the wrong country's feeds are leaking in
The "no Regions filter set" note used to fire on VOLUME alone (candidates
per channel over 6). A reported run sat at 4.4 per channel — under any
volume threshold — while its candidates carried **sixteen** different
country markers for a 42-channel Dutch lineup. It duly filled that lineup
with Polish, French and Australian feeds, and in places the Dutch feed was
never probed at all, skipped because two foreign ones came back clean
first.

The note now also fires on DIVERSITY, and names the countries it actually
found, so "set Regions" is an instruction you can act on rather than a
riddle. Also spelled out in the README: **Regions** ("which country?") and
**Custom prefixes** ("what packaging should be ignored?") are different
knobs, and prefixes will never filter by country.

### New setting: max streams per channel
A hard ceiling on candidates probed per channel, default **12**, in Settings
(`--max-candidates` on the CLI; **0** for no cap).

The depth rule above is adaptive and only fires once enough candidates come
back *clean* — so it never triggers on a channel whose candidates are all
dead, and it deliberately doesn't apply at all when **Streams at once** is
above 1. Nothing bounded either case, and a web-started run passed no
ceiling whatsoever. On a multi-country provider a generic name ("TLC",
"CNN") can pool into dozens of candidates, so that was a real runaway.

Can't be set below the clean-target of 4: a ceiling under it would make the
adaptive rule unreachable and silently cap every uncurated push at the
ceiling instead. **Find streams** and **Import from Dispatcharr** now honour
this setting too, instead of their own hardcoded 6.

### Fixes
- The "placeholder" verdict now names the container that reported the fixed
  duration — `reports a fixed 600.0s duration (hls)`. On MPEG-TS a finite
  duration means what this check assumes; on HLS/DASH it can just be the
  length of the segment window a healthy live playlist currently publishes,
  so a whole lineup coming back placeholder is now diagnosable at a glance
  instead of being a mystery.
- Curate showed only ONE candidate as "in the channel" for a channel that
  had only ever had a `group` written to it, and persisted that single-stream
  failover chain if you then touched it — the client-side default disagreed
  with both the server's and the auto-picker's.
- Candidate cards rendered a stray `undefined` after the "60Hz — likely a US
  feed" badge, on every off-cadence stream, since that badge was added.
- A run's one-off **Custom prefixes** are now stored with the run. They were
  used for matching and then thrown away, so anything that re-matched the
  same names afterwards (Find streams, the EPG panel) quietly used a
  narrower vocabulary than the run itself had.
- The contact sheet's download is now `contact-sheet-picks.json`. It was
  offered as `selection.json` — a different shape entirely, next to the
  run's real `selection.json`, where saving it would have silently
  overwritten your curation.
- Deleting a run now releases the Dispatcharr claims it made — previously
  a channel a deleted run had pushed stayed marked "ours" forever and never
  reappeared in Unclaimed (found live: 138 stale claims on production).
- `_dropped_urls()` referenced an undefined variable, silently swallowed by
  its own error handling — the "dropped stream" failure counts on
  candidate cards had never actually worked, for any run.
- Watchtower no longer tries (and fails) to pull the test instance's
  locally-built image from Docker Hub.

### Watchdog (opt-in, off by default in Settings)
Ongoing per-channel maintenance driven by Dispatcharr's own event log:
- Flags a channel on a real channel_error/channel_reconnect and demotes
  the affected stream in ranking immediately -- not waiting for a
  re-probe to confirm what Dispatcharr just reported directly.
- Re-checks on an escalating schedule (30 min, doubling up to a 48h cap),
  resetting straight back to the start on any renewed trouble.
- A channel with genuinely no usable candidate is renamed with a
  "⚠ DOWN:" marker in Dispatcharr rather than left looking normal, and
  its existing candidates keep being re-checked -- never a catalogue
  search for new ones, only what it already has.
- Promotes and pushes a clean fallback automatically once one outranks
  the demoted pick, and restores a "DOWN"-marked name the moment a
  candidate is clean again.
- Graduates off the watchlist (and its demotion lifts) after the
  configured stable window with no further trouble.
- A channel down to its LAST usable stream is re-checked like any other.
  It used to be skipped on the reasoning that there was no fallback to
  promote — which meant its results never changed, so it could never be
  re-checked, never be marked DOWN when that last stream died, and never
  graduate, while being the channel most worth watching.
- "Events to flag" above 1 now accumulates across checks. Events were only
  ever counted within a single two-minute poll, so anything above the
  default of 1 would rarely (or never) fire.
- Never deletes a Dispatcharr channel -- matches this codebase's
  existing "never delete automatically" rule for pushes.
