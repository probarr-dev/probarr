# channeliq

> **Renamed from probarr.** Same project, same data format, nothing to
> migrate. `python3 -m probarr ...` and `PROBARR_*` env vars still work
> exactly as before -- the image carries both names. **The repo and image
> path have NOT moved yet** -- still `probarr-dev/probarr` and
> `ghcr.io/probarr-dev/probarr` -- so don't change those in your compose
> file; this will be announced separately if/when they do move. If something
> broke on your next pull and you're not sure why, it's almost certainly
> this rename; please open an issue and it'll get fixed properly rather
> than worked around in Discord.

**Verify, compare and visually curate IPTV streams.**

Providers list the same channel dozens of times — `UK: Meridian Sports 1`,
`UKFHD | Meridian Sports 1`, `UKUHD: Meridian Sports 1 UHD`, `HEVC FHD Meridian
Sports 1`. Most are dead, corrupted, or serving a placeholder card. channeliq
works out which ones actually play, ranks them, and shows you the pictures so
you can make the final call.

Any M3U or Xtream source in; M3U, XMLTV or Dispatcharr out.

![Curating a channel: ranked candidates with real thumbnails, corruption counts and a live EPG comparison](docs/screenshots/curate.jpg)

---

## Contents

- [Install](#install)
- [Your first run](#your-first-run) — start here
- [Set your concurrency first](#set-your-concurrency-first)
- [Wantlists: telling channeliq what you want](#wantlists-telling-channeliq-what-you-want)
- [Browsing a provider when you don't know what to ask for](#browsing-a-provider-when-you-dont-know-what-to-ask-for)
- [Curating a run](#curating-a-run)
- [Checking a stream is really the right channel](#checking-a-stream-is-really-the-right-channel)
- [What the statuses mean](#what-the-statuses-mean)
- [When it doesn't do what you expected](#when-it-doesnt-do-what-you-expected) — read this one
- [Exporting](#exporting)
- [Lineups: keeping a channel list current](#lineups-keeping-a-channel-list-current)
- [Settings worth knowing about](#settings-worth-knowing-about)
- [Command line](#command-line)
- [How ranking works](#how-ranking-works)
- [Why channeliq decodes instead of trusting metadata](#why-channeliq-decodes-instead-of-trusting-metadata)
- [Security](#security)
- [Credits](#credits) · [License](#license)

---

## Install

Docker is the supported path — it bundles ffmpeg and needs nothing on the host,
identically on Windows, macOS and Linux.

```bash
docker run -d --name channeliq -p 7799:7799 -v ./config:/config ghcr.io/probarr-dev/probarr:latest
```

Open `http://localhost:7799`.

`/config` is the only thing worth keeping: every run, wantlist, provider and
curation decision lives there.

<details>
<summary>Building it yourself, or running without Docker</summary>

The published image is built straight from this repo by GitHub Actions
(`.github/workflows/docker-publish.yml`) on every push to `main`, so `:latest`
is always exactly what's on `main` — nothing hand-uploaded. To build it
yourself (it takes seconds — stdlib only, no dependency resolution):

```bash
git clone https://github.com/probarr-dev/probarr.git
cd probarr
docker build -t channeliq .
docker run -d --name channeliq -p 7799:7799 -v ./config:/config channeliq
```

It runs as a plain script too, if you have `ffmpeg`, `ffprobe` and Python 3.9+.
There are no Python dependencies at all:

```bash
python3 -m channeliq --root ./config verify --source playlist.m3u
```
</details>

---

## Your first run

Four steps, all in the browser. The CLI can do the same things but nothing here
needs it.

### 1. Add your provider

**Providers** → paste your playlist URL, or `xtream://` / `dispatcharr://`
credentials. Hit **Test connection** before saving — it will tell you how many
channels it actually parsed, which catches a wrong URL immediately (a typo'd
address often returns an HTML error page with HTTP 200, and that used to parse
as a few dozen bogus "channels").

While you're here, add an EPG source too if you have one — an XMLTV URL under
**EPG sources**. It's optional, but it unlocks the single most useful check
channeliq does (see [checking a stream is really the right
channel](#checking-a-stream-is-really-the-right-channel)).

### 2. Set your concurrency

Go to **Settings** and set concurrency to what your subscription actually
allows. This matters more than anything else on that page — see
[below](#set-your-concurrency-first) for why getting it wrong silently corrupts
your results rather than erroring.

### 3. Tell it which channels you want

On a big provider you need a **wantlist**, or channeliq would try to probe all
55,000 listed streams. Two ways:

- **Channels** (`/browse`) — pick a provider, load it, tick what you want, save
  it as a wantlist. No probing, near-instant even on a huge catalogue. This is
  the easy path if you don't already have a list.
- **Wantlists** (`/wantlists`) — paste or import a text list if you already
  know exactly what you want. Format is in
  [wantlists](#wantlists-telling-channeliq-what-you-want).

### 4. Run it, then curate

**+ New Run** → pick your provider and wantlist → **Start verifying**.
Progress streams live. When it finishes you land in **Curate**, where you pick
a stream per channel and export.

From then on, `http://localhost:7799/` takes you straight back to Curate for
your most recent run. The full run list is under **Runs**.

---

## Set your concurrency first

**The default is 1, on purpose.** Many providers cap simultaneous connections,
and exceeding that cap does not return a clean error — it returns plausible
garbage that looks exactly like a dead stream. Probe in parallel past your
limit and you will silently record a lineup of "dead" channels that are
perfectly fine.

Set it in **Settings** (or `--concurrency`) to what your subscription allows,
leaving headroom for whoever is actually watching television. A three-stream
account probes roughly three times faster than a one-stream one. The settings
page estimates run time live as you change the number.

Each saved provider can also carry its own limit, so a permissive provider
isn't held back by a restrictive one.

---

## Wantlists: telling channeliq what you want

The single most important input on a large provider. Without one, verifying
means probing every candidate for every listed stream — not a long job, an
impossible one.

Build one by ticking channels in **Channels** (`/browse`), or write it by hand:

```
# channels.txt — number optional, |tvg-id optional
101: BBC One
102: BBC Two
BBC Four
401: Meridian Sports Main Event | meridian.main.uk
```

`/wantlists` gives you a live preview of exactly what channeliq parsed, warning
about duplicates and unparseable lines before you save. Saved lists are used by
name (`--wantlist uk-lineup`), and saving over an existing name **appends**
rather than replacing, so you can extend a list as you browse a second
provider.

**Channels that match nothing are reported loudly, not skipped.** The usual
cause is a naming difference rather than a missing channel, and the fix is an
alias nobody will write if the omission is silent. Inexact matches are flagged
too — a guess you can't see is a guess you can't correct.

If a channel is genuinely filed under a name the matcher would never try, add
an **alias** in Settings, or use **Find streams** on the channel itself in
Curate to attach anything from the catalogue by hand.

### Region and quality tags

Before any of the matching above happens, channeliq strips **packaging** off
the raw name: a leading country marker ("UK:", "US:") and quality/format
words ("HD", "RAW", "4K"…) built into the app already cover the common
cases. A provider that uses its own non-country prefixes for a tier or
source ("OD:", "PLAY+:", "ZG:") — or a quality word channeliq has never
seen ("GOLD") — isn't covered by that built-in list, and without it the
prefix stays glued to the front of the name forever: `OD: NPO 1` normalises
to `ODNPO1`, which will never match a wantlist entry for `NPO 1` no matter
how the name is spelled otherwise.

**Settings → Manage tags** is a durable, editable version of both lists:
add your provider's own prefixes/words, remove one you don't want treated
as packaging, or hit **Restore defaults** to drop your own changes and go
back to whatever channeliq's built-in list currently is. Applies to every run
and to Browse Channels. New Run also has a one-off **Custom prefixes**
field for a prefix worth using just this one time, without saving it
permanently.

---

## Browsing a provider when you don't know what to ask for

**Channels** (`/browse`) is the answer to "I don't have a wantlist and don't
know what to type."

Pick a saved provider, load it, and channeliq groups the raw channel names — no
ffmpeg, no waiting, near-instant even on a huge catalogue, because it's the
same text-grouping a run does before probing starts. Forty spellings of the
same channel collapse into one row with a count and an expandable list of what
got grouped, so you can see the matcher working rather than trust it blindly.

Tick what you want, save as a wantlist, start a run.

---

## Curating a run

`/run/<id>/curate` is built for working through a long list: channels on the
left with status dots, candidates on the right, driven from the keyboard.

| Key | Action |
|---|---|
| `↑` `↓` / `j` `k` | move between channels |
| `1`–`9` | make that candidate the first stream |
| `f` | add the next candidate to the channel |
| `x` | exclude the channel from every export |
| `Enter` | confirm and advance |
| `c` or `space` | in the image viewer, toggle full frame / 1:1 crop |
| `Esc` | close the viewer |

Hovering a status dot tells you what it means.

### Picking streams

A channel holds an **ordered list** of streams, not just a primary and a
fallback — Dispatcharr fails over down that list, so a third good candidate has
somewhere to go. Drag the numbered rows to reorder.

Selections save server-side automatically, so they survive a different browser
or machine.

### Per-channel actions

- **Find streams** — every stream the provider offers for this channel, probed
  or not, plus a search of the whole catalogue for variants the matcher didn't
  connect. Tick what's worth probing; only this channel is touched.
- **Diagnose this channel** — re-probes every candidate with a longer sample
  (25s) and *keeps the video clip*, so you can watch the few seconds that were
  measured. For when a channel misbehaves in a real player and a still frame
  doesn't explain why.
- **Check EPG** — see [below](#checking-a-stream-is-really-the-right-channel).
- **Mark watermark area** — see [below](#the-watermark-check).
- **Duplicate** — a second copy of the channel so it can sit in another group
  too, same streams, no re-probing.
- **Changes (N)** — what moved for this channel since the last scan.
- The **✎** next to the group name sets this channel's group. For moving many
  channels at once, use the **Groups** view instead — drag between groups, or
  drop one channel on another to swap their numbers.

![Groups view: drag channels between groups, reorder within a group without disturbing anything else's numbering](docs/screenshots/groups.jpg)

### Re-probing a single candidate

Each candidate has a **↻** button, for when a capture landed in an ad break, on
a channel ident, or on the one dark shot in a bright programme.

Re-probes go through a queue rather than running on the spot. The button is
trivially spammable, and inline probing would open one connection per click —
straight through an allowance that may be a single stream, in the exact
situation where exceeding it is most misleading (the resulting "dead stream"
looks like the button diagnosing a real fault). The queue runs at most
`concurrency` probes at once, paces launches, refuses to queue the same stream
twice, and applies a short cooldown.

### What you're looking at

Each candidate is captured three ways from one decoded frame: a grid thumbnail,
a full frame, and a **1:1 native centre crop**. The crop matters because
scaling defeats the comparison people actually need — judging whether a 1080p
encode is worse than a 720p one means seeing blocking and ringing at native
pixels.

Frames are chosen with ffmpeg's `thumbnail` filter rather than by timestamp.
Taking the first frame past a fixed time produced a solid black thumbnail for a
perfectly healthy channel in testing, which is a total failure in a tool whose
premise is "look at the picture".

An **aspect ratio off** tag appears on any candidate whose shape disagrees with
the rest of the channel's — the visible signature of a stretched or
wrongly-letterboxed feed.

---

## Checking a stream is really the right channel

This is the check no probe can perform. A stream can be alive, clean,
high-bitrate and showing entirely the wrong programme.

### The guide check

Add an XMLTV source (Providers → EPG sources, or `--epg`) and channeliq records
**what the guide said should be playing at the exact moment each frame was
captured**, and prints it under that candidate's own picture. Wrong programme
under a right-looking picture is then a glance, not an investigation.

Guide and playlist channel ids rarely line up, so matching falls back to
display names — and **refuses to guess when ambiguous**, because attaching the
wrong region's listings is worse than showing none.

**Check EPG** on a channel compares every saved EPG source's *live* "on now"
side by side, so you can see which source actually agrees with the picture, and
pin the channel to a specific source or a specific guide entry. That choice is
remembered on the lineup and reused by later runs and by the Dispatcharr push.

### The watermark check

Some feeds are the right name and the wrong content, with no EPG mismatch to
give it away. **Mark watermark area** lets you drag a box around the channel's
on-screen logo on one known-good picture. Every other candidate then shows that
same area cropped out of *its own* frame, right next to its screenshot — so a
wrong feed is something you notice by looking, the same way you'd notice
anything else on the card.

The box is stored as fractions of the image, so it survives candidates being
different resolutions. Nothing is computed for a channel nobody has marked.

### Channel logos

The **Logo** section of Check EPG lets you pick which picture represents a
channel: the provider's own, whichever matched EPG source's icon, or a search
of the [tv-logo/tv-logos](https://github.com/tv-logo/tv-logos) catalogue.

The pick is remembered on the lineup and pushed to Dispatcharr with everything
else. channeliq never downloads or stores a logo image — see
[credits](#credits).

---

## What the statuses mean

| Status | Meaning |
|---|---|
| `ok` | decoded a real, moving picture with no corruption |
| `dirty` | decodes, but with corruption errors — watchable at best |
| `placeholder` | the same still picture is served for several channels |
| `no_frame` | responded to ffprobe, but no frame could be decoded |
| `no_video` | responded, but carries no video stream |
| `dead` | no response |

Advisory flags, computed on every probe, never a verdict on their own:

- **low motion** — the picture barely moves. Often an off-air card, but
  measured against live UK broadcast the classes genuinely overlap: BBC Four's
  off-air card scored 1.12, BBC Three's 2.25, and a *live* BBC One studio
  interview scored 1.87 — right between the two. No threshold separates them,
  so channeliq flags the low end and lets you read the words on the picture.
- **multi-bitrate manifest** — the source is an HLS master playlist or a DASH
  `.mpd` with several renditions rather than a fixed-quality stream. Shown as
  information, deliberately **not** penalised.
- **DASH multi-bitrate** — the stronger, evidenced signal, and the only one of
  these that carries a ranking penalty. Tested directly: a channel's DASH
  source and its HLS fix exposed the *same* four renditions, yet only the DASH
  one caused real buffering through a relay in production. Variant count didn't
  predict it; container format did.
- **slow fetch** — the capture took close to real-time or longer to download.
  Healthy live segments arrive far faster than real-time.
- **dropped Nx** — this exact stream has genuinely failed over N times in real
  use, read from Dispatcharr's own event log. Real playback evidence, not a
  probe guess.

---

## When it doesn't do what you expected

Every question below has actually been asked. Each one is a real behaviour
with a real reason — none of them are bugs you need to work around, and
where one *was* a bug it says so and says which version fixed it.

**The short version:** if a channel didn't match, it's a naming/tag problem
([here](#my-channels-didnt-match-anything)). If the counts look wrong, it's
almost always the depth-of-4 rule ([here](#it-only-probed-some-of-my-streams)).
If everything failed at once, check concurrency first
([here](#everything-came-back-dead)).

### My channels didn't match anything

The single most common problem, and it's almost never a missing channel —
it's packaging on the front of the name.

channeliq strips country markers (`UK:`, `US:`) and quality words (`HD`,
`RAW`, `4K`) before matching. It does **not** know your provider's own
prefixes. So `OD: NPO 1` normalises to `ODNPO1`, and a wantlist entry for
`NPO 1` will never match it, however you spell the rest.

**Fix:** Settings → **Manage tags** → add `OD`, `PLAY+`, `ZG`, `BE-VIP`, or
whatever yours uses. With or without the trailing colon both work. This is
durable — it applies to every future run and to Browse Channels.

There's also a **Custom prefixes** box on the New Run form. That one is
one-off, for a prefix you don't want to save. If you're going to type the
same thing twice, put it in Manage tags instead.

Still not matching after that? In order:

1. **Browse Channels** (`/browse`) — find the channel and see what the
   matcher actually grouped. Forty spellings collapse into one row, so you
   can watch it work rather than guess.
2. **Settings → Aliases** — for a channel genuinely filed under a name no
   amount of tag-stripping would reach (`Sky Sports Main Event` vs `SSME`).
3. **Find streams** on the channel in Curate — attach anything from the
   catalogue by hand. Always works, needs no configuration, doesn't scale.

### It only probed some of my streams

Expected. The run log says so explicitly:

```
skipped ZIGGOTV / ZIGGO TV (via Dispatcharr): already has 4 clean candidate(s)
```

Once a channel has **4** streams that came back clean, the rest are skipped.
Candidates are probed best-declared-first, so the ones skipped are the ones
already ranked below four known-good streams. Probing them costs a provider
connection to learn nothing.

So "86 of 106 probed" is the feature working, not a failure.

Two things worth knowing:

- **This only applies at concurrency 1.** At 2 or more there is no early
  stop at all — cancelling probes already in flight isn't worth the
  complexity — so a run at higher concurrency probes *everything*. If your
  runs feel enormous, this is usually why.
- **It was 2 until recently**, which capped how many streams a push could
  ever pick from. If you're on an older run, re-verify to pick up the
  extra two.

To probe everything deliberately: `--clean-target 0` on the CLI.

### It only pushed one stream / is it limited to 2?

No. The number is **4**, and it's a default rather than a ceiling.

| What you did | What gets pushed |
|---|---|
| Nothing — never opened the channel | top **4** playable candidates, best first |
| Curated an order in Curate | **all of them**, in your order, no cap |
| Chose **Separate channel** mode | **2** — one channel plus one `FALLBACK:` channel |

"Separate" is genuinely capped at two, by design: it creates a second real
channel in your lineup, and turning one curated channel into five is not
something to do quietly. Use **Native** if you want a deeper chain — that's
Dispatcharr's own `streams: [...]` failover list, and it takes as many as
you give it.

> **If you saw exactly one stream pushed**, that was a real bug, fixed in
> the release that renamed probarr → ChannelIQ. A channel that had only ever
> had a *group* set on it showed one candidate instead of four, and touching
> it saved that. Re-pulling fixes new channels, but any channel already
> narrowed on disk needs **+ Add to channel** clicking once per channel —
> no re-run or re-probe needed.

### Everything says "placeholder"

A placeholder verdict means the stream reported a fixed total length. Live
TV has no total length, so normally this means the provider is serving a
looped "channel unavailable" card.

The card now names the container that reported it:

```
reports a fixed 600.0s duration (mpegts); a live channel has none
reports a fixed 600.0s duration (hls);    a live channel has none
```

That word in brackets is the whole diagnosis:

- **`(mpegts)`** — trust it. A live MPEG-TS relay has no length to report,
  so a number really does mean a finite file on a loop. Your provider is
  serving cards; nothing on this end will change that.
- **`(hls)` or `(dash)`** — treat with suspicion. A healthy live playlist
  can legitimately report the length of the segment window it currently
  publishes. If a whole lineup says placeholder and they're all HLS with
  the same suspiciously round duration (600s = 60 × 10s segments), that's
  the shape of a false positive — please open an issue with that line.

### Everything came back "dead"

Check concurrency before anything else. It's the one setting channeliq
cannot work out for itself, and getting it wrong doesn't fail cleanly: an
over-limit provider returns plausible-looking garbage that reads as a dead
stream. A run that's 90% dead against a provider you know works is this,
nearly every time.

Set it to the number of simultaneous connections your subscription actually
allows — 1 if you don't know. Per-provider overrides live on the provider
itself, so a generous provider isn't held back by a strict one.

### It says a candidate is "another country's feed"

The frame rate gave it away: UK and European broadcast is 25 or 50fps, and
a candidate at 29.97/59.94 is very often a US feed filed under a European
name.

It's a **flag, not a verdict** — it never blocks a stream on its own, and a
provider that simply transcodes everything to 30fps will trip it
legitimately. Look at the picture; that's what the thumbnails are for.

### I re-ran it and it barely did anything

Lineup re-verifies carry forward still-fresh results instead of re-probing
them: if a stream's provider-side id hasn't changed and it was probed
within **`freshness_hours`** (default 6 days), the previous verdict stands.

That's the point — a routine weekly run spends its connections only on what
might actually have changed. Set `freshness_hours` to 0 in Settings to
disable it and always probe everything. Ad-hoc runs (no lineup) never carry
anything forward, because there's no previous run to compare against.

### Channels arrived in Dispatcharr with no number, or the wrong one

Numbers come from your **wantlist**, not from the streams. A channel with
probe results but no wantlist entry has no number to push, so it's reported
in the preview and skipped rather than being given whatever number happens
to be free.

Always use **Preview changes** before a push. It shows creations, updates,
"already correct", and everything being skipped and why.

### "Needs you" — what does it actually want?

Open the channel; the box at the top lists the specific reasons in plain
words. It means one of: nothing clean to pick from, a candidate that's the
provider's holding card, an EPG mismatch, or the ranking changed since you
last looked.

If you've looked and it's fine, click **This is fine — stop asking**. That
sticks until the *evidence* changes — new candidates, a different status,
a new EPG mismatch — so it isn't permanent blindness, and it isn't nagging
you about something you've already judged.

### What should I do next?

Roughly in order of how much they pay back:

1. **Save your channel list as a Lineup.** Re-verifying a lineup carries
   forward fresh results and keeps your curation decisions across runs.
   Without one, every run starts from scratch.
2. **Give that lineup a schedule** (every N days, at an hour you pick) so
   re-verifying happens without you remembering to.
3. **Consider Watchdog** (Settings, off by default). It reads Dispatcharr's
   own event log and reacts to channels genuinely failing in real playback
   — demoting the broken stream, re-checking on a backoff, promoting a
   clean fallback, and marking a channel `⚠ DOWN:` when nothing works. It
   pushes to Dispatcharr **unattended**, which is why it's opt-in: every
   other push in channeliq is confirmed by a person first.

---

## Exporting

Three outputs, all from the Curate page:

- **Export M3U** — a playlist of your picks, with numbers, groups, logos and
  guide ids.
- **Export EPG** — an XMLTV keyed to the same ids as that playlist. A player
  needs both.
- **Push changes** — straight into Dispatcharr, if you run it.

### Pushing to Dispatcharr

**Push changes** creates or updates channels, sets streams in your curated
order, links logos and re-matches EPG. Run it again after tweaking your picks
and it re-asserts rather than duplicates.

**Preview changes** shows exactly what would happen before anything is written
— creations, updates, "already correct", staged deletions, and channels the
provider has stopped carrying. Worth using; every silent-success bug this
exporter has had shared the shape of "reported done, applied something else".

The target is a saved **Provider**, same concept as a source. If the run was
itself sourced from a saved Dispatcharr provider, the export defaults to
pushing back into that exact instance with no extra configuration. You can also
probe from one place and publish to another.

Two fallback strategies, presented as an explicit choice with no default —
it's a real trade-off, not a detail to bury:

- **Native** — one channel, `streams: [primary, fallback, …]`. Dispatcharr's
  own failover switches automatically. No lineup clutter; the fallback isn't
  individually selectable.
- **Separate channel** — a second channel named `FALLBACK: …`. Doubles the
  lineup, but it's visible and pickable by hand.

Candidates that already belong to the target instance reuse their existing
stream id. Everything else is matched by URL against every stream the target
already has — including ones Dispatcharr parsed itself from a real M3U/Xtream
account, which take priority over an older custom stream sharing the same URL.
Only a URL matching nothing gets a custom stream created, and that
match-by-URL is what stops re-exporting piling up duplicates. See
[docs/design/per-provider-m3u-accounts.md](docs/design/per-provider-m3u-accounts.md)
for why landing on native streams matters beyond tidiness: a real M3U account's
connection limit is enforced against Live TV and VOD together, which a custom
stream is invisible to.

**channeliq never deletes from Dispatcharr on its own.** A channel dropped from
your curated set is reported in the preview and left alone; removing it is an
explicit action (**Remove** on the channel, with "also from Dispatcharr").

### Importing what Dispatcharr already has

**+ → Import from Dispatcharr** reads the channels already in your Dispatcharr
and matches them against this run, so an existing lineup arrives with its
current stream shown next to real, probed alternatives. Nothing already
verified in this run is re-probed, so importing an existing lineup is cheap.

---

## Lineups: keeping a channel list current

A **run** is one verification pass — a snapshot. A **lineup** (`/lineups`) is
the durable thing a run is a snapshot *of*: "my Sky channels", not "the run
from Tuesday". It holds the provider, wantlist and EPG a run starts from, plus
the accumulated per-channel decisions — group, EPG source, logo, watermark box,
renames — that every later run inherits instead of asking again.

channeliq only ever reads your provider's list. To pick up a provider adding,
removing or changing streams, **re-verify the lineup** (a button on `/lineups`,
or on a schedule) rather than starting a fresh run each time:

- A newly available channel gets picked up, because re-verifying re-matches
  your wantlist against the provider's *current* catalogue every time.
- A channel the provider has dropped shows as **missing** ("no candidate
  streams matched") instead of silently vanishing, and is called out in the
  Dispatcharr push preview rather than quietly skipped.
- It's cheap, not a blind redo: a candidate whose stream hasn't changed on the
  provider's end since its last verdict, within the **freshness window**
  (Settings, default 6 days), is carried straight forward. Only genuinely new
  or changed streams spend a connection.

Set a lineup to re-verify on a schedule and this happens without you.

---

## Settings worth knowing about

| Setting | Why it matters |
|---|---|
| **Concurrency** | The one that silently corrupts results if set too high — see [above](#set-your-concurrency-first). |
| **Sample seconds** | How long each stream is decoded for. Longer finds more intermittent corruption; costs proportionally more time. |
| **Freshness window** | How long a previous verdict is trusted on re-verify (default 6 days). |
| **Frame / thumbnail height** | Capture resolution. Bigger frames, bigger `/config`. |
| **Aliases** | For a channel your provider spells in a way the matcher would never guess. |
| **Manage tags** | Region/quality words to strip as packaging before matching — add your provider's own non-standard prefixes here. See [above](#region-and-quality-tags). |
| **Failover display** | Whether to read Dispatcharr's event log for real-world failure counts. |

`/settings` also has a full backup export/import of everything in `/config`.

---

## Command line

The browser flow doesn't need it, but it exists for scripting and cron, and
runs the same code (`channeliq/runner.py` is the single implementation both
share).

```bash
# Verify a playlist and build a contact sheet
channeliq verify --source https://example.com/list.m3u --regions UK

# Only the channels you want, with expected programmes from a guide
channeliq verify --source list.m3u --wantlist channels.txt \
               --epg https://example.com/guide.xml.gz

# Rebuild the sheet from a stored run
channeliq sheet --run 20260821-081343

# See exactly how a title is matched — the matcher fails silently otherwise
channeliq explain "UKUHD: Meridian Sports 1 UHD" --source playlist.m3u
```

---

## How ranking works

1. **Integrity before quality, always.** A clean 720p feed beats a corrupted 4K
   one — the corrupt stream is unwatchable and its metadata says nothing.
2. Higher pixel rate (width × height × fps). 1080p50 genuinely beats 1080p25.
3. Higher *measured* bitrate — measured, because declared bitrate is missing or
   fictional on most live streams.
4. **HEVC as a tiebreak only.** It is not a quality signal; some of the worst
   corruption found while building this was HEVC.

Ranking is a starting point, not the answer. The whole point of the pictures is
that you overrule it when it's wrong.

---

## Why channeliq decodes instead of trusting metadata

There are many playlist checkers. They answer *"is this URL alive?"*. channeliq
answers *"which of these forty candidates should be my Meridian Sports 1, and
is it actually showing Meridian Sports 1?"*

**It decodes rather than reading metadata.** A stream can report a flawless
1920x1080@50 HEVC and still decode into continuous `Skipping invalid
undecodable NALU` errors — perfect metadata, unwatchable picture. channeliq
decodes a real sample and counts the errors.

**It detects provider placeholder cards.** When a provider is out of
connections it serves a banner, re-encoded per "channel" so no checksum
matches. channeliq compares frames perceptually and flags a still picture served
across several different channels.

**It shows you the frames.** Some faults are only visible to a person: the
guide says one film and a different film is playing. No probe finds that. A
grid of thumbnails finds it instantly.

---

## Security

channeliq has **no authentication** and is intended for a trusted LAN. Don't
expose it directly to the internet; put it behind a reverse proxy with auth if
you need remote access.

Credentials are never committed: `scripts/check-secrets.sh` runs as a
pre-commit hook (install with `scripts/install-hooks.sh`). Git history is
permanent, so deleting a leaked secret later doesn't remove it.

Provider URLs routinely carry subscription credentials, so contact sheets and
anything else shareable carry **redacted** URLs. The API never hands out a
provider's real spec — the UI only ever sees the redacted form.

---

## Credits

A few ideas here were borrowed outright from other open-source tools in the
Dispatcharr community, and it's worth naming where from rather than quietly
absorbing the idea:

- **[Podium](https://github.com/lpukatch/podium)** (Coffee/lpukatch) — the
  freshness-window idea (re-verifying skips a candidate whose stream hasn't
  changed since its last verdict) and giving each provider its own concurrency
  lane instead of one global limit.
- **[Lineuparr](https://github.com/PiratesIRC/Dispatcharr-Lineuparr-Plugin)**
  (PiratesIRC) — trailing country-tag detection ("Cartoon Network | US", not
  just "UK: Cartoon Network"), the staged token-sort fuzzy-matching fallback
  with adjustable sensitivity, and the starter-lineup-file concept.
- **[StreamFlow](https://github.com/krinkuto11/streamflow)** (krinkuto11) —
  per-account concurrency limiting during parallel checks, which shaped how
  channeliq's own lanes are scoped.

None of this is literal ported code — different language, different
architecture — but the design decisions are theirs first. Go look at what
they've built; each does real things channeliq doesn't.

The in-app logo picker searches
**[tv-logo/tv-logos](https://github.com/tv-logo/tv-logos)** (CC BY-SA 4.0),
using the same GitHub-contents-API fetch approach Lineuparr uses for the same
repository. channeliq never downloads, mirrors, or redistributes a logo image —
every result is a link straight to that repository's own
`raw.githubusercontent.com` hosting, fetched directly by the browser (or by
Dispatcharr, once a pick is pushed). channeliq's own cache holds only the
directory listings (country and filename lists), never image bytes.

Bug reports and code review from the Dispatcharr Discord have fixed real
things here, including an EPG parser that held whole guides in memory and an
export path that skipped dropped channels silently. Issues and PRs welcome.

Particular thanks to **[knmplace](https://github.com/knmplace)**, whose PRs
have landed real fixes and features here — credential redaction on the
settings endpoint, the EPG cache stampede/memory fixes, Windows test-fixture
bugs, the cross-origin write guard, the Browse Channels country/category
filter and active-lineup view, and opt-in Dispatcharr M3U account creation
among them — and to **Mandzo**, whose real-world testing (a provider naming
its streams in small-caps/superscript Unicode, a local M3U source path that
only existed on the host and not inside the container) surfaced bugs no
amount of writing tests in a vacuum would have found.

## License

MIT — see [LICENSE](LICENSE).

## Getting started (from the browser)

1. **Providers** — add your IPTV subscription (a playlist URL, or
   `xtream://`/`dispatcharr://` credentials). "Test connection" confirms it
   before you save it.
2. **Wantlists** — optional, but the only realistic option on a large
   provider: paste or import the channels you actually want.
3. **+ New Run** — pick a provider and (optionally) a wantlist, hit
   *Start verifying*. Progress streams live; when it finishes you land
   straight in Curate.
4. **Curate** — pick a stream per channel, export the M3U.

Nothing here requires the CLI. It still exists for scripting/cron use, and
does exactly what the browser flow does under the hood (`channeliq/runner.py`
is the one implementation both share).

## Using Dispatcharr as a source

Dispatcharr can be a **provider** too, not just an export target — useful
if you'd rather probe against what Dispatcharr has already ingested than
maintain a second, separate connection straight to the underlying IPTV
subscription. Two different things happen when Dispatcharr is your
provider, and it's worth being clear on which is which:

**By default**, channeliq reads Dispatcharr's *entire raw ingested stream
table* — every stream from every M3U account it has, not just the ones
currently assigned to a channel. If Dispatcharr already has an active M3U
account pointed at the same subscription you'd otherwise connect to
directly, this is a full, like-for-like replacement: the same breadth of
alternate streams to compare, the same candidate discovery, nothing lost.
Every probe still connects **directly to the raw upstream URL** — same as
probing that provider straight, Dispatcharr is only being used as the
catalogue.

**The "Dispatcharr proxy" option** (New Run, shown once a Dispatcharr
provider is selected) is a different, narrower thing: it adds ONE extra
candidate — alongside every raw one, never instead of them — for a channel
that's *already assigned* in Dispatcharr, routed through Dispatcharr's own
live proxy instead of the raw URL. That candidate is probed exactly the
way a real player watching through Dispatcharr would see it, and it's the
only way a probe shows up in Dispatcharr's own live Stats page (a raw
candidate's connection never touches Dispatcharr at all, so Dispatcharr
has no way to know it happened).

The real reason to reach for it: if **channeliq itself doesn't have the
network path a provider needs** (a VPN, a specific geo-IP) but Dispatcharr
already does, routing through Dispatcharr's proxy means Dispatcharr makes
the actual upstream connection, not channeliq — sidestepping that mismatch
entirely for whatever Dispatcharr already has assigned.

**That said, the strongly preferred fix for a network-path mismatch is
installing channeliq behind the same VPN/proxy Dispatcharr already uses.**
The proxy option only ever covers a channel Dispatcharr already has —
it can't discover or compare a genuinely better alternate the way probing
the raw catalogue can, since Dispatcharr's proxy has no concept of a
stream that isn't already assigned to a channel. Running channeliq on the
same network path keeps full candidate discovery working everywhere, not
just for what's already been chosen.

## Exporting to Dispatcharr

If you already run Dispatcharr, "Export to Dispatcharr" on the Curate page
pushes your curated picks straight into it — creates or updates channels,
sets streams, links logos, re-matches EPG. Same self-healing pattern as a
plain re-run: run the export again after tweaking your picks and it
re-asserts rather than duplicates.

The export target is a saved **Provider** — the same concept as a source,
deliberately. If the run was itself sourced from a saved Dispatcharr
provider, the export panel defaults to pushing back into that exact
instance, no extra configuration needed. You can still choose a different
saved Dispatcharr provider as the target (probe from one place, publish to
another).

Two fallback strategies, presented as an explicit choice with no default —
this is a real trade-off, not a technical detail to bury:

- **Native**: one channel, `streams: [primary, fallback]`. Dispatcharr's own
  failover switches automatically. No lineup clutter; the fallback isn't
  individually selectable.
- **Separate channel**: a second channel named `FALLBACK: …`, streaming only
  the fallback. Doubles the lineup, but it's visible and pickable by hand.

Candidates that already belong to the target Dispatcharr instance reuse
their existing stream id directly. Everything else is matched by URL
against every stream the target already has — including ones Dispatcharr
parsed itself from a real M3U/Xtream account, which take priority over an
older custom stream sharing the same URL if both exist. Only a URL that
matches nothing gets a real custom stream created (`is_custom: true`), and
that match-by-URL is what keeps re-exporting from ever piling up
duplicates. See
[docs/design/per-provider-m3u-accounts.md](docs/design/per-provider-m3u-accounts.md)
for why landing on Dispatcharr's own native streams matters beyond
tidiness: a real M3U account's connection limit is enforced against Live
TV playback and VOD together, which a custom stream is invisible to
regardless of which account it's filed under.

The export panel's "change" options include an opt-in checkbox — off by
default — to create that real Dispatcharr M3U account for this run's own
provider if one doesn't exist yet, instead of leaving every candidate to
fall back to the shared "custom" account. It's off by default because
creating an account is a real, visible change to your Dispatcharr instance
(a new entry in its own UI, an immediate one-time refresh), not something
worth doing silently on every push.

## Browsing a source without probing

`/browse` (linked from Wantlists) is the answer to "I don't have a wantlist
and don't know what to type." Pick a saved Provider, load it, and channeliq
groups the raw channel names — no ffmpeg, no waiting, near-instant even on a
huge catalogue, since it's the same text-grouping a run already does before
probing starts. Forty spellings of the same channel collapse into one row
with a count and an expandable list of what got grouped, so you can actually
see the matcher working rather than trust it blindly. Tick what you want,
save it as a wantlist; saving over an existing name appends rather than
replacing, so a starter list can be extended as you browse a second
provider.

## Two things learned from a real buffering report

**Advisory flags, computed on every probe, free:**

- `multi_bitrate_manifest` — the source is a multi-rendition manifest (an
  HLS master playlist or a DASH `.mpd` with several AdaptationSets), rather
  than a single fixed-quality stream. Detected by counting video streams in
  the metadata probe, which was already being fetched.
- `dash_multi_bitrate` — the stronger, evidenced signal. Tested directly: a
  channel's DASH source and its HLS fix exposed the *same* four renditions,
  yet only the DASH one caused real buffering through a relay in production.
  Variant count alone didn't predict it; container format did. Only this
  flag carries a ranking penalty — `multi_bitrate_manifest` alone is shown
  as informational, deliberately not penalised, because the data doesn't
  support treating it as a fault on its own.
- `slow_fetch` — the capture took close to real-time or longer to download.
  Healthy live segments normally arrive far faster than real-time; a source
  that can't keep up is a genuine buffering signal, computed from timing
  data already gathered for bitrate measurement.

**Diagnose this channel** (Curate, per channel) — for when one channel
misbehaves in a real player and a single still frame doesn't explain why.
Re-probes every candidate for that channel with a longer sample (25s) and
keeps the video clip instead of discarding it, so you can actually watch
the few seconds that were measured. Clips are fragmented MP4
(`frag_keyframe+empty_moov`), not `+faststart` — the latter needs a clean
process exit to rewrite its index, and a killed or timed-out capture left a
`moov atom not found` file that no player could open. Fragmented MP4 writes
its index up front, so a clip stays valid even if the capture is cut short.
