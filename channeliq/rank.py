"""Ranking verified candidates for one logical channel.

Ordering rules, in priority order:

1. **Playable before unplayable.** Dead, frameless and placeholder streams
   rank below everything that decodes into a moving picture. Note what this
   does NOT say: a stream logging decode errors still PLAYS -- the decoder
   conceals them, like a scratched DVD -- so it competes on picture with a
   clean one rather than being pushed beneath it. Ranking a 1.5 Mbps stream
   above a 7 Mbps one for logging no errors gave a visibly worse picture.
2. Bigger picture, then more bits spent on it, then higher frame rate --
   in that order, never multiplied together. 1080p50 genuinely beats
   1080p25 at the same bitrate, but not at a third of it.
3. Higher *measured* bitrate. Measured, because declared bitrate is missing or
   fictional on most live streams.
4. **HEVC only as a tiebreak.** It is tempting to treat HEVC as a quality
   signal; it is not. Some of the worst corruption found while building this
   was in HEVC streams. It earns a nudge between otherwise-equal candidates
   for being more efficient at the same bitrate, and nothing more.
5. More audio channels, then fewer decode errors.
"""
from .probe import (STATUS_OK, STATUS_DIRTY, STATUS_PLACEHOLDER,
                    STATUS_NO_FRAME, STATUS_NO_VIDEO, STATUS_DEAD)

# How many ranked candidates make up a channel's failover chain when nobody
# has curated one by hand. Lives HERE, at the bottom of the import graph, so
# the two ends of the pipeline cannot drift apart: verify.py stops probing a
# channel once it has this many clean candidates, and web.py's push picks
# this many when a channel has no explicit selection (AUTO_FALLBACK_DEPTH,
# and its client-side mirror in curate.py's JS).
#
# Real bug this fixes: probing stopped at 2 while the push wanted 4, so an
# uncurated channel could never have more than two `ok` candidates for the
# push to choose from no matter how many the provider actually offered --
# reported as "is channeliq limited to 2 streams per channel?", and visible
# in a run log as "skipped X: already has 2 clean candidate(s)".
FALLBACK_DEPTH = 4

# A still picture ranks below a corrupted one on purpose. Corruption is often
# transient and the channel is at least the right channel; a placeholder card
# is not the content at all.
# `ok` and `dirty` share a tier ON PURPOSE. The original rule was
# "integrity before quality, always" -- a clean 720p feed beats a corrupted
# 4K one -- and against real viewing that turned out to be wrong. Streams
# carrying decode errors play perfectly well: the decoder conceals them, the
# same way a scratched DVD still plays. Ranking a 1.5 Mbps stream above a
# 7 Mbps one because the first logged no errors gave a visibly worse
# picture, confirmed by watching both.
#
# So the tiers now separate PLAYS from DOES NOT PLAY. Dead, frameless and
# placeholder streams are unusable and stay at the bottom; anything that
# decodes into a moving picture competes on picture. The error count is
# kept, shown, and used only to break a tie between otherwise-equal
# candidates.
_STATUS_RANK = {STATUS_OK: 0, STATUS_DIRTY: 0, STATUS_PLACEHOLDER: 2,
                STATUS_NO_FRAME: 3, STATUS_NO_VIDEO: 4, STATUS_DEAD: 5}

# Broadcast frame-rate families. UK and European linear television is PAL --
# 25 or 50 fps, always. North America is NTSC: 29.97 or 59.94. A candidate
# whose cadence disagrees with the rest of the lineup it sits in is, with
# very few exceptions, a different country's feed wearing the right name.
#
# This matters more than it looks, because the ranking's pixel-rate term is
# width x height x fps -- so a mislabelled 1080p59.94 US feed scored 124M
# against the correct 1080p25 UK feed's 52M and was promoted above every
# genuine candidate. Confirmed on a real lineup: Comedy Central offered six
# 25fps streams and three at 29.97/59.94, every one of them labelled "UK:",
# and the ranking chose an American one.
CADENCE = {}
for _f in (23.98, 24.0):
    CADENCE[_f] = "film"
for _f in (25.0, 50.0):
    CADENCE[_f] = "pal"
for _f in (29.97, 30.0, 59.94, 60.0):
    CADENCE[_f] = "ntsc"


def cadence_of(fps):
    """The broadcast family a frame rate belongs to, or None if unrecognised.

    Rounded to two places because ffprobe reports 29.97 as 30000/1001 and
    30.0 as 30/1, which differ in the third decimal.
    """
    if not fps:
        return None
    return CADENCE.get(round(float(fps), 2))


def dominant_cadence(records, threshold=0.8):
    """The cadence a whole run is in, or None when it is genuinely mixed.

    A LINEUP-level consensus, deliberately not a per-channel one. Per-channel
    majority voting is worse than useless here: the case that motivated this
    had four of six candidates carrying the wrong country, so the vote would
    have elected the wrong feed and flagged the correct ones as the oddity.
    A lineup, by contrast, is overwhelmingly one country by construction --
    measured at 585 PAL against 34 NTSC on a real UK run -- so the run as a
    whole is a trustworthy reference where a single channel is not.

    `film` is never dominant and never counted against: 23.98 is a legitimate
    cadence for a movie channel in any country.
    """
    counts = {}
    for r in records:
        c = cadence_of(r.get("fps"))
        if c in ("pal", "ntsc"):
            counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values())
    if total < 20:
        return None            # too small a sample to call a house style
    top = max(counts, key=counts.get)
    return top if counts[top] / total >= threshold else None


# A still shared with other channels is the provider's placeholder. Pushed
# below everything else, but kept rather than deleted: occasionally a channel
# really is off air at probe time and will be fine later.
PLACEHOLDER_PENALTY = 1

# A rival within roughly this fraction of the CURRENT PICK's bitrate does
# not outrank it on bitrate alone -- see score_key()'s `incumbent_kbps`.
# Real complaint that motivated this: channeliq's own "Changed" alert kept
# firing "X now ranks above your pick" between one re-verify and the next,
# with no real difference in either stream -- the actual cause was this
# exact sort term, comparing raw measured_kbps. A single live stream's
# bitrate moves with what's ON SCREEN (an action scene versus a static
# studio shot), so two probes of the SAME feed a few seconds apart were
# never going to report identical numbers, and the documented real-world
# case was a ~4% wobble.
#
# First attempt here was a fixed log-spaced bucket grid (bucketing every
# candidate's bitrate independently of any other, not just the incumbent's).
# It worked, but every discrete bucket has edges, and a pair sitting right on
# one still flip-flopped exactly like before, just at a different threshold
# -- fixing the reported case while leaving the class of bug in place.
# Comparing against the actual incumbent instead removes the edge entirely:
# there is nothing to straddle when the reference point is "how far from the
# stream that's ALREADY primary", because the incumbent is always, trivially,
# a zero-distance match against itself.
#
# 35% was this constant's value under THAT bucket grid, and stayed wrong
# after the grid was removed: it was widened that far only to guarantee two
# genuinely-close values landed in the same discrete bucket despite the
# grid's own quantization error, not because 35% reflects real probe noise.
# With no grid left to compensate for, that margin just swallowed real
# differences -- confirmed live: a confirmed pick and a rival measuring
# two-thirds its bitrate (34.6% apart) tied on bitrate and lost the tiebreak
# to the rival's codec, without corruption count (222 errors against the
# rival's near-zero) ever being consulted. 15% comfortably covers the
# ~4% noise this exists for while leaving a real 20-35% gap decisive again.
BITRATE_TOLERANCE = 0.15


def score_key(r: dict, incumbent_kbps=None, demoted_stream_id=None):
    status = r.get("status", STATUS_DEAD)
    area = (r.get("width", 0) or 0) * (r.get("height", 0) or 0)
    fps = float(r.get("fps", 0) or 0)
    hevc = 0 if "hevc" in (r.get("video_codec", "") or "").lower() else 1
    return (
        _STATUS_RANK.get(status, 9),
        # `demoted_stream_id` -- see watchdog.py -- is not a probe's guess:
        # it names the stream Dispatcharr's OWN system-events log just
        # reported a real channel_error or channel_reconnect against, i.e.
        # a viewer's player actually failed over. That is stronger evidence
        # than anything a 10-25s sample can produce, so it is weighed
        # immediately after integrity (still ahead of a placeholder card
        # only because "unusable at all" always outranks "usable but just
        # reported trouble"), well before any quality term -- a demoted
        # stream still beats a genuinely broken one, but loses to any other
        # OK candidate regardless of resolution or bitrate.
        # Compared against rec_key-or-stream_id, not stream_id alone --
        # that is the same identity curate.py's candidate "id" and every
        # selection's primary/streams entries use (see build_payload),
        # and watchdog.py's demoted_stream_id is set from exactly one of
        # those (a channel's current confirmed pick).
        1 if (demoted_stream_id and
              (r.get("rec_key") or r.get("stream_id")) == demoted_stream_id)
        else 0,
        PLACEHOLDER_PENALTY if r.get("placeholder_group") else 0,
        1 if r.get("low_contrast") else 0,
        # Immediately after the integrity checks and ahead of every quality
        # term, because a cadence that disagrees with the lineup is not a
        # quality problem -- it is the wrong channel. Placed below slow_fetch
        # at first, which was not enough: on the real Comedy Central pool
        # every UK stream happened to be flagged slow while the two American
        # ones were not, so the US feeds still won before cadence was ever
        # consulted. The wrong country at 1080p is not a better answer than
        # the right country at 720p, however it is delivered.
        1 if r.get("off_cadence") else 0,
        # Ranked ahead of raw resolution, not just as a late tiebreak: a
        # slow real-world fetch is a reliability concern, and integrity
        # beats quality here the same way a clean 720p stream already beats
        # a corrupted 4K one.
        #
        # dash_multi_bitrate carries a real penalty; plain multi_bitrate_
        # manifest deliberately does not. Tested directly: the DASH source
        # that actually buffered in production and the HLS source that fixed
        # it both expose the same four renditions -- variant count alone did
        # not predict the problem, container format did. Penalising every
        # multi-rendition source equally would have ranked the (fine) HLS
        # fix no better than the (broken) DASH original.
        1 if r.get("dash_multi_bitrate") else 0,
        # slow_fetch dropped from ranking. Measured across a real 628-stream
        # lineup: it flagged 87% of everything usable, and average bitrate
        # was near-identical flagged vs not (3478 vs 3475 kbps) -- not the
        # bitrate-punishing bias it looked like, just a threshold that does
        # not hold for this provider's ~10s segment delivery, where "close
        # to real-time to fetch" is normal rather than a sign of trouble.
        # Still recorded and shown; just not treated as evidence of anything.
        # Resolution, then how much data is actually spent on it, and only
        # then frame rate. Multiplying the three together (the old
        # "pixel rate") let a 1080p50 stream at 1.6 Mbps beat a 1080p25 at
        # 5.8 Mbps -- twice the frames, a third of the bits, a visibly worse
        # picture. It is the same arithmetic that promoted a mislabelled
        # 59.94fps American feed over the correct British one. Frame rate
        # still decides between two streams of equal size and bitrate, which
        # is where it genuinely matters (sport at 50fps against 25).
        -area,
        # `incumbent_kbps` is the CURRENTLY CONFIRMED PICK's measured
        # bitrate, passed in by the caller (curate.build_payload) -- not
        # discovered from the candidate pool itself. A candidate within
        # BITRATE_TOLERANCE of it sorts as though it measured exactly the
        # incumbent's own bitrate, tying it on this term and falling through
        # to fps/hevc/audio/corruption below, which do not carry the same
        # probe-to-probe measurement noise. The incumbent itself always ties
        # with itself here (zero distance), so it never loses its own slot to
        # noise; a rival genuinely outside the tolerance is left un-snapped
        # and wins or loses on its real, larger difference, same as before.
        # With no incumbent (nothing picked yet, e.g. a channel's first ever
        # probe), this has no effect and bitrate compares on raw kbps.
        -(incumbent_kbps if incumbent_kbps and r.get("measured_kbps")
          and abs(r["measured_kbps"] - incumbent_kbps) <= BITRATE_TOLERANCE * incumbent_kbps
          else (r.get("measured_kbps", 0) or 0)),
        -fps,
        hevc,
        -(r.get("audio_channels", 0) or 0),
        # Last, and a tiebreak only: between two streams of the same size,
        # rate and codec, prefer the one that decoded more cleanly. It is
        # not a reason to take a materially worse picture.
        round(r.get("corruption_per_sec", 0) or 0, 1),
        r.get("corruption_errors", 0) or 0,
    )


def rank(results, incumbent_kbps=None, demoted_stream_id=None):
    """Sort probe results best-first. Pure; does not mutate input order.

    `incumbent_kbps`/`demoted_stream_id` -- see score_key(); passed
    straight through.
    """
    return sorted(results, key=lambda r: score_key(r, incumbent_kbps,
                                                   demoted_stream_id))


def pick(results, depth=2):
    """Return the best `depth` candidates -- [primary, fallback, ...].

    Only genuinely usable streams are eligible: a dead or video-less stream is
    never offered as a fallback, because failing over to it is worse than no
    failover at all.
    """
    # STATUS_PLACEHOLDER deliberately excluded. Found on a full-codebase
    # review contradicting itself against this module's own _STATUS_RANK
    # comment above ("Dead, frameless and placeholder streams are unusable
    # and stay at the bottom") -- a placeholder is a provider's holding
    # card, not the channel's real content, and treating it as a usable
    # pick would silently reintroduce exactly the bug class
    # annotate_placeholders() elsewhere in this codebase exists to detect.
    usable = [r for r in rank(results)
              if r.get("status") in (STATUS_OK, STATUS_DIRTY)]
    return usable[:depth]


def explain_choice(results):
    """Human-readable reason the winner won. Surfaced in the UI and logs."""
    ranked = rank(results)
    if not ranked:
        return "no candidates"
    best = ranked[0]
    if best.get("status") != STATUS_OK:
        return f"best available is {best.get('status')} ({best.get('reason', '')})"
    clean = sum(1 for r in ranked if r.get("status") == STATUS_OK)
    bits = [f"{best.get('width')}x{best.get('height')}@{best.get('fps')}fps",
            f"{best.get('measured_kbps')}kbps", best.get("video_codec", "")]
    return f"{' '.join(b for b in bits if b)}; {clean}/{len(ranked)} candidates clean"
