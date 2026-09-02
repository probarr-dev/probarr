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

### Fixes
- Deleting a run now releases the Dispatcharr claims it made — previously
  a channel a deleted run had pushed stayed marked "ours" forever and never
  reappeared in Unclaimed (found live: 138 stale claims on production).
- `_dropped_urls()` referenced an undefined variable, silently swallowed by
  its own error handling — the "dropped stream" failure counts on
  candidate cards had never actually worked, for any run.
- Watchtower no longer tries (and fails) to pull the test instance's
  locally-built image from Docker Hub.

### In progress, not yet active
Watchdog: ongoing per-channel maintenance driven by Dispatcharr's own
event log (flag on a real channel_error, demote the affected stream in
ranking immediately, re-check on an escalating schedule, auto-promote and
push a clean fallback, graduate off the watchlist after a stable window).
The decision logic, ranking hook, and Settings page are built and tested,
but the background poller that actually watches Dispatcharr's events and
drives the schedule hasn't been written yet — the Settings toggle exists
but doesn't do anything live yet.
