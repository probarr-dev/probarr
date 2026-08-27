"""Stream verification: does this URL actually deliver clean, real video?

The central lesson this module encodes: **ffprobe metadata passing does not
mean a stream is good.** A stream can report 1920x1080 @ 50fps HEVC and still
decode into continuous corruption. Metadata describes what the provider
*claims*; only decoding tells you what actually arrives. So every candidate
that survives the cheap metadata check gets a real decode pass, and the errors
ffmpeg emits during it are counted.

Cost model: providers frequently cap concurrent connections (one, in the case
this tool was built against). Every connection is therefore spent
deliberately:

  stage 1  ffprobe    ~2-4s   metadata + liveness. Dead streams stop here and
                              never cost a second connection.
  stage 2  ffmpeg     ~Ns     ONE pass producing four things at once -- decode
                              error count, a JPEG thumbnail, a 9x8 grayscale
                              frame for the perceptual hash, and a measured
                              (not declared) bitrate.

Doing those four in one pass rather than four is the difference between a
90-minute run and a six-hour one.
"""
import dataclasses
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from .dhash import (dhash_from_gray, hamming, is_flat, contrast,
                    motion_score, frames_from_raw, MOTION_GRID,
                    MOTION_FRAME_BYTES, STILL_MAD, MIN_CONTRAST)

# stderr lines that indicate the picture itself is damaged, as distinct from
# transport noise. Kept separate because a handful of "error while decoding"
# lines at startup is normal, while a stream of NALU/PPS failures is the
# signature of the genuinely-unwatchable stream that started this project.
_CORRUPTION_RE = re.compile(
    r"NALU|PPS|SPS|corrupt|invalid|concealing|no frame|non-existing|"
    r"missing picture|decode_slice|Invalid data|error while decoding",
    re.I)

# The provider actively refused the connection, as distinct from a network
# fault or a genuinely broken stream. Found by comparing this project's own
# credited reference tool (PiratesIRC's IPTVChecker) against probarr: that
# tool detects HTTP 429/403 in ffmpeg/ffprobe's stderr and backs off the
# whole account, not just the one channel, before hitting the provider
# again. probarr had no equivalent -- a soft rate-limit or per-channel
# backend block came back indistinguishable from "responded, but no frame
# could be decoded", got one fixed 1.5s retry (see retry_empty below), and
# was reported no differently from a genuinely dead stream. That is exactly
# the shape of one specific channel's failures being investigated here:
# the identical URL, probed seconds apart with zero other traffic, gave a
# hard failure once and a clean decode once.
_RATE_LIMIT_RE = re.compile(
    r"\b429\b|Too Many Requests|\b403\b|[Ff]orbidden", re.I)

# A single decode warning during a 10-25s live sample is not evidence of a
# genuinely bad stream -- a status gate of ">0" was tried first and turned
# out to flag almost everything: on one real multi-country provider, only
# 12% of candidates hit literal zero, and the MEDIAN candidate (including
# plenty that looked fine on the actual frame/clip) carried 78 errors. That
# swamps the streams that are actually unwatchable (hundreds of errors) in
# noise from ones with a handful of isolated concealment blips. A few stray
# errors are normal for live broadcast; real corruption climbs steeply past
# that, not gradually, so a small floor separates the two cleanly without
# needing to be exact.
CORRUPTION_OK_MAX = 3

# Errors before the decoder has a reference frame are an artefact of HOW we
# sample, not a property of the stream. Joining a live feed lands mid-GOP, so
# the decoder complains -- "non-existing PPS", "no frame", "decode_slice" --
# until the first keyframe arrives, exactly as a player does for the fraction
# of a second before a channel appears. Counting those condemned 72% of a
# real lineup (447 dirty against 172 ok, median 78 errors).
#
# Proved by the tool's own data: the SAME streams re-probed with a 25s sample
# instead of 10s should show ~2.5x the errors if the corruption were
# continuous. Median observed ratio was 0.29x, and streams scoring 297 and
# 275 came back with 0 and 1. That is not a measurement of the stream.
WARMUP_SECONDS = 2.0

# Errors per second of DECODED video after that warm-up. A genuinely broken
# stream produces them continuously -- the worst measured here ran at ~160/s
# -- while an occasional concealed macroblock on a live broadcast is normal
# and invisible in play. One per second is the point where damage starts
# being plausible to a viewer.
CORRUPTION_RATE_MAX = 1.0

# ffmpeg writes its progress line with a carriage return, interleaved into
# the same stream as the errors, so the most recent one dates every error
# that follows it.
_PROGRESS_RE = re.compile(r"^frame=.*\btime=(\d+):(\d+):([\d.]+)")

STATUS_OK = "ok"
STATUS_DIRTY = "dirty"          # decodes, but with corruption
STATUS_PLACEHOLDER = "placeholder"  # the provider's card, corroborated across channels
STATUS_NO_FRAME = "no_frame"    # metadata only; nothing could be decoded to a picture
STATUS_NO_VIDEO = "no_video"    # responded, but no usable video stream
STATUS_DEAD = "dead"            # no response / timeout / refused


@dataclasses.dataclass
class ProbeOptions:
    sample_seconds: int = 10
    frame_at: float = 2.5        # grab the thumbnail this far in, past startup black
    # Frames per second sampled for the motion measurement. 2fps over the
    # whole window is plenty to separate a frozen card from live television
    # and costs a few KB.
    motion_fps: int = 2
    # Below this mean-absolute-difference the picture is flagged low-motion
    # for a human to glance at. It is ADVISORY, never a pass/fail.
    #
    # Measured against live UK broadcast, the classes genuinely overlap:
    #
    #   BBC Four off-air card   1.12   (animated gradient)
    #   BBC One, live           1.87   (studio interview, fixed camera)
    #   BBC Three off-air card  2.25   (animated gradient)
    #
    # Live content scored between two placeholder cards. No threshold
    # separates them, so probarr does not pretend one does: it flags the low
    # end for review and lets a person read the words on the picture.
    still_mad: float = STILL_MAD
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    user_agent: str = "VLC/3.0.20 LibVLC/3.0.20"
    probe_timeout: int = 20      # ffprobe wall clock
    capture_timeout: int = 45    # ffmpeg wall clock
    measure_bitrate: bool = True
    retry_empty: bool = True     # retry when a capture yields no picture at all

    # Backoff schedule (seconds) for a capture that came back with NOTHING
    # USABLE AT ALL -- see served_nothing() and the note on retry_empty
    # below. Deliberately escalating and spread over ~30s rather than the
    # single 1.5s retry this used to do.
    #
    # Measured, not guessed. Across a real 733-probe run every one of the
    # 44 no_frame results had these exact properties: decoded_seconds 0.00,
    # measured_kbps 0, ~96 decode errors, timed_out False, and a capture
    # that ended after ~5s against a 25s requested window. They arrived in
    # same-channel BURSTS (six candidates of one channel launched within
    # seconds, all six failing, the seventh -- running alone -- succeeding),
    # and every single failing URL was probed clean at another point in the
    # same run. So the stream was fine; the provider simply would not serve
    # that many connections to one channel at once, and said so by handing
    # back undecodable bytes instead of an HTTP error.
    #
    # All 44 had already used the old single 1.5s retry and still failed,
    # because 1.5s later the rest of the burst was still in flight. The
    # burst takes ~20s to drain, which is what this schedule is sized for.
    empty_backoff: tuple = (3.0, 8.0, 20.0)

    # Three images per candidate, all from the same decoded frame:
    #
    #   thumb   small, for the grid
    #   frame   large, for judging the picture as a whole
    #   crop    a 1:1 UNSCALED centre crop
    #
    # The crop exists because scaling defeats the comparison people actually
    # need to make. Judging whether a 1080p encode is worse than a 720p one
    # means looking at blocking, ringing and smeared detail -- all of which
    # disappear the moment the frame is resampled down to thumbnail size.
    # Only native pixels show it.
    thumb_height: int = 240
    frame_height: int = 720
    crop_width: int = 640
    crop_height: int = 360
    # Frames considered when choosing the representative one. Larger is more
    # robust against black/transition frames but buffers more before emitting.
    thumbnail_batch: int = 50
    thumb_quality: int = 5       # ffmpeg -q:v, 2=best 31=worst
    frame_quality: int = 3
    capture_crop: bool = True

    # Off by default: a normal run already remuxes a copy-codec MPEG-TS
    # sample for bitrate measurement and discards it. Diagnose mode keeps
    # that exact same remux instead of throwing it away -- zero extra
    # encoding cost, since it is a stream copy either way -- so a human can
    # actually watch the few seconds of playback that were just measured,
    # rather than infer buffering from numbers alone.
    capture_clip: bool = False

    def resolved(self):
        """Fail loudly and early if the binaries aren't there."""
        for attr in ("ffmpeg", "ffprobe"):
            binary = getattr(self, attr)
            if not shutil.which(binary):
                raise RuntimeError(
                    f"{binary} not found on PATH. probarr needs ffmpeg and ffprobe. "
                    f"The supported install is the Docker image, which bundles both; "
                    f"otherwise install ffmpeg and/or set PROBARR_FFMPEG.")
        return self


def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout), False
    except subprocess.TimeoutExpired as e:
        # A timeout is a real result, not an exception to swallow: a stream
        # that cannot deliver `sample_seconds` of video inside the wall clock
        # is unusable in a player too. Return what was captured before the
        # kill so partial output is still usable.
        return e, True
    except (OSError, ValueError) as e:
        return e, True


def _fps(rate: str) -> float:
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    try:
        num, den = rate.split("/")
        return round(int(num) / int(den), 3) if int(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _headers(opts):
    return ["-user_agent", opts.user_agent]


def probe_metadata(url: str, opts: ProbeOptions) -> Optional[dict]:
    """Stage 1: cheap liveness + declared metadata. None if the stream is dead."""
    cmd = [opts.ffprobe, "-hide_banner", "-v", "error", *_headers(opts),
           "-analyzeduration", "4M", "-probesize", "8M",
           "-show_entries",
           "stream=index,codec_type,codec_name,width,height,r_frame_rate,"
           "bit_rate,channels,profile,pix_fmt:format=bit_rate,format_name,duration",
           "-of", "json", url]
    res, failed = _run(cmd, opts.probe_timeout)
    if failed or res.returncode != 0 or not res.stdout.strip():
        return None
    try:
        info = json.loads(res.stdout)
    except ValueError:
        return None

    streams = info.get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = info.get("format") or {}

    # A source URL that is itself a multi-rendition manifest (an HLS master
    # playlist, or a DASH .mpd with several AdaptationSets) reports one video
    # stream PER quality level here, not one. Found for real: BBC One's DASH
    # source had four (704x396, 960x540 x2, 1280x720), and it was the one
    # channel of twelve that buffered badly in production -- every other
    # channel was a single fixed-rendition source and played fine. A single
    # ffprobe/ffmpeg pass doesn't itself reproduce the buffering (it just
    # decodes whatever rendition it auto-selects and reports clean), so this
    # count is the only signal a probe can actually see of the underlying
    # cause: the relay has to do real ABR selection/switching for this
    # source and nothing else, which is a meaningfully more fragile path
    # through a proxy than a plain single-rendition passthrough.
    #
    # Report the HIGHEST-resolution rendition's metadata (not just the
    # first one found, which for BBC One was misleadingly the lowest).
    v = max(video_streams, key=lambda s: (s.get("width") or 0) * (s.get("height") or 0),
            default=None)

    return {
        "has_video": v is not None,
        "width": (v or {}).get("width", 0) or 0,
        "height": (v or {}).get("height", 0) or 0,
        "fps": _fps((v or {}).get("r_frame_rate", "")),
        "video_codec": (v or {}).get("codec_name", "") or "",
        "video_profile": (v or {}).get("profile", "") or "",
        "pix_fmt": (v or {}).get("pix_fmt", "") or "",
        "audio_codec": (a or {}).get("codec_name", "") or "",
        "audio_channels": (a or {}).get("channels", 0) or 0,
        "video_variant_count": len(video_streams),
        # Declared bitrate is very often absent or wrong on live streams --
        # kept for reference, superseded by the measured figure below.
        "declared_kbps": int((v or {}).get("bit_rate") or fmt.get("bit_rate") or 0) // 1000,
        "container": fmt.get("format_name", "") or "",
        "container_duration": _parse_container_duration(fmt),
    }


def _parse_container_duration(fmt: dict) -> Optional[float]:
    """A finite, parseable `format.duration` from a channel that is
    supposed to be live TV, not evidence of anything -- it is direct
    contradiction. A genuine live relay (MPEG-TS, or an HLS/DASH playlist
    with no fixed end) has no total length to report, and real IPTV
    sources overwhelmingly omit the field entirely or return "N/A" for
    exactly that reason. A stream that instead answers with a real number
    is serving a finite file on a loop -- the provider's own "channel
    unavailable" card, most often -- which is a DIFFERENT signature to the
    cross-stream still-picture matching annotate_placeholders() already
    does: that needs the SAME picture to show up on more than one channel
    before it is willing to call it a placeholder, so a single channel
    quietly looping a lone finite file with no twin elsewhere in the
    lineup would sail through it undetected. This catches that case with
    no cross-channel corroboration needed at all -- one stream, one probe,
    the container format answering a question a live broadcast should
    never be able to answer.
    """
    raw = fmt.get("duration")
    if raw in (None, "", "N/A"):
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _media_duration(path, opts) -> float:
    """Duration of a local file, via ffprobe. No network involved."""
    # Real bug found on a full-codebase review: this used a bare 15s
    # literal while every other ffprobe/ffmpeg call in this file derives
    # its timeout from ProbeOptions -- so raising capture_timeout (e.g.
    # Diagnose mode's longer sample) had no effect here, and measuring the
    # duration of an otherwise successfully captured file could itself
    # time out on a slow/loaded host, silently zeroing measured_kbps for a
    # perfectly good capture with nothing indicating why.
    res, failed = _run([opts.ffprobe, "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       opts.probe_timeout)
    if failed or res.returncode != 0:
        return 0.0
    try:
        return float(res.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def _read_gray(path):
    try:
        if os.path.getsize(path) >= 72:
            with open(path, "rb") as f:
                return f.read(72)
    except OSError:
        pass
    return None


def capture(url: str, opts: ProbeOptions, thumb_path: str,
            frame_path: str = None, crop_path: str = None,
            clip_path: str = None) -> dict:
    """One ffmpeg pass -> decode errors + thumbnail + two hash frames + bitrate.

    Five outputs share a single decode of a single connection. Do not split
    this into separate invocations: on a connection-limited provider each
    extra pass is another serialized round trip, and on any provider it is
    another chance to sample a *different* moment and draw inconsistent
    conclusions about the same stream.

    Two grayscale frames are taken, seconds apart, specifically so stillness
    can be measured -- a placeholder card is the one fault that decodes
    perfectly and reports flawless metadata.
    """
    t_a = min(opts.frame_at, max(0.0, opts.sample_seconds - 1))
    # `thumbnail` picks the most representative frame out of a batch rather
    # than blindly taking the first one past a timestamp.
    #
    # This matters more than it sounds. Taking the first frame after t=2.5s
    # produced a solid black thumbnail for BBC One on a live run -- the stream
    # was perfectly healthy (motion 21, 5 Mbps) but the chosen instant landed
    # on a join/transition frame. A black thumbnail in a tool whose entire
    # premise is "look at the picture" is a total failure of the feature.
    #
    # Every image output and the perceptual hash share this one frame, so what
    # gets hashed is exactly what the operator is shown.
    sel_a = f"select=gte(t\\,{t_a}),thumbnail=n={opts.thumbnail_batch}"
    workdir = tempfile.mkdtemp(prefix="probarr-")
    raw_a = os.path.join(workdir, "a.gray")
    motion_path = os.path.join(workdir, "motion.gray")
    ts_path = os.path.join(workdir, "sample.ts")

    cmd = [
        opts.ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error",
        # Progress lines are what make an error datable: without them every
        # error is equally suspicious, including the ones the decoder always
        # emits before it has locked on.
        "-stats", "-stats_period", "0.5",
        *_headers(opts),
        "-analyzeduration", "4M", "-probesize", "8M",
        "-t", str(opts.sample_seconds),
        "-i", url,
        # (a) full decode, for error counting
        "-an", "-sn", "-f", "null", "-",
        # (b) human-viewable thumbnail. -update 1 is required for a single
        # fixed filename; without it image2 warns and the intent is unclear.
        # scale=-2 keeps the aspect ratio and forces an even width, which JPEG
        # chroma subsampling requires.
        "-map", "0:v:0", "-vf", f"{sel_a},scale=-2:{opts.thumb_height}",
        "-frames:v", "1", "-update", "1", "-q:v", str(opts.thumb_quality),
        "-f", "image2", thumb_path,
        # (c) that same frame as a 9x8 grayscale block, for identity matching
        "-map", "0:v:0", "-vf", f"{sel_a},scale=9:8:flags=area,format=gray",
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", raw_a,
        # (b2) full-size frame, never upscaled -- min() keeps a 576p source at
        # 576p instead of inventing detail it does not have.
        "-map", "0:v:0",
        "-vf", f"{sel_a},scale=-2:min({opts.frame_height}\\,ih)",
        "-frames:v", "1", "-update", "1", "-q:v", str(opts.frame_quality),
        "-f", "image2", frame_path,
        # (d) a 32x32 strip across the WHOLE window, for motion measurement
        "-map", "0:v:0",
        "-vf", f"fps={opts.motion_fps},scale={MOTION_GRID}:{MOTION_GRID}:flags=area,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", motion_path,
    ]
    if opts.capture_crop and crop_path:
        # (b3) 1:1 centre crop at native resolution, no scaling whatsoever.
        # min() against iw/ih so a source smaller than the crop box does not
        # make ffmpeg fail outright.
        cw = f"min(iw\\,{opts.crop_width})"
        ch = f"min(ih\\,{opts.crop_height})"
        cmd += ["-map", "0:v:0",
                "-vf", f"{sel_a},crop={cw}:{ch}",
                "-frames:v", "1", "-update", "1", "-q:v", "2",
                "-f", "image2", crop_path]
    if opts.measure_bitrate:
        # (e) remux without re-encoding, purely to weigh the bytes that
        # actually arrived. Providers under-report or omit bitrate constantly.
        cmd += ["-map", "0:v:0", "-c", "copy", "-f", "mpegts", ts_path]
    if opts.capture_clip and clip_path:
        # (f) a watchable clip: video AND audio, stream-copied (no
        # re-encode, so this costs nothing beyond disk I/O on top of the
        # decode already happening) into MP4 so it plays directly in a
        # browser <video> tag. Separate from the bitrate remux above, which
        # is deliberately video-only and kept small/ephemeral.
        #
        # Fragmented MP4 (frag_keyframe+empty_moov), not +faststart.
        # +faststart writes an EMPTY placeholder moov, then rewrites it at
        # the true position only after the process exits cleanly -- if it is
        # killed first (a timeout, a network stall on this network-dependent
        # capture, anything), the file is left with no moov atom at all and
        # is not a valid MP4 by any player. Confirmed live: exactly this --
        # "moov atom not found", DEMUXER_ERROR_COULD_NOT_OPEN, an unplayable
        # file despite the capture otherwise completing "successfully".
        # Fragmented MP4 writes its (empty) moov up front and streams
        # self-contained moof fragments after it, so whatever was written
        # before any interruption stays valid and playable on its own --
        # every other output here (rawvideo, single-frame image2, mpegts)
        # already tolerates truncation for the same reason; this is what
        # makes MP4 do the same.
        #
        # Audio is TRANSCODED to AAC rather than stream-copied, and that is
        # load-bearing, not tidiness. Fragmented MP4 has to write its header
        # up front (that is the whole point of empty_moov, above), but the
        # MP4 muxer cannot describe an E-AC-3 track until it has parsed some
        # of its packets -- so copying eac3 audio in here fails outright with
        # "Cannot write moov atom before EAC3 packets parsed".
        #
        # ffmpeg then aborts the ENTIRE command, not just this output. Every
        # other output in this single pass -- the thumbnail, the full frame,
        # the crop, the hash frames, the bitrate remux -- is discarded with
        # it, and the probe reports "no frame could be decoded" for a stream
        # that was decoding perfectly. Found for real: an eac3 channel that
        # played fine in a player and passed every Verify run (those capture
        # no clip) failed EVERY Diagnose and re-probe, deterministically,
        # because only those two set capture_clip.
        #
        # Video stays a stream copy, which is where the cost would be; AAC
        # encoding a stereo track is negligible next to the decode already
        # happening.
        cmd += ["-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "copy", "-c:a", "aac",
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", clip_path]

    # thumb_path/frame_path/crop_path are FIXED, deterministic paths -- the
    # same rec_key always maps to the same file, so a re-probe writes over
    # the previous capture rather than a fresh one. That is by design (it is
    # what makes ?v=<probed_at> versioning work), but it has a sharp edge: if
    # ffmpeg fails or is killed before it gets around to writing an output --
    # seen for real, a proxying IPTV manager returning an instant 5XX left
    # ffmpeg dead at 0.1s having written nothing -- the OLD file from the
    # previous successful capture is still sitting at that exact path. The
    # existence check below would then find it, report the capture as having
    # produced a picture, and probe() would mark the stream "ok" from a
    # completely stale image while genuinely fresh data (bitrate, motion,
    # decode errors) all came back zero/empty. Silently showing yesterday's
    # frame as if it were fresh is exactly the failure this tool exists to
    # catch in the PROVIDER's output; it must not also happen in its own.
    #
    # Deleting any pre-existing file at these paths first makes existence
    # after the run mean what it is supposed to mean: ffmpeg wrote it just now.
    for p in (thumb_path, frame_path, crop_path, clip_path):
        if p:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass

    started = time.time()
    res, failed = _run(cmd, opts.capture_timeout)
    elapsed = time.time() - started
    stderr = res.stderr if hasattr(res, "stderr") and res.stderr else b""
    err_text = stderr.decode("utf-8", "replace")
    at, decoded_for = 0.0, 0.0
    err_lines, corruption, startup, steady = [], [], [], []
    for line in err_text.splitlines():
        if not line.strip():
            continue
        m = _PROGRESS_RE.match(line.strip())
        if m:
            at = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            decoded_for = max(decoded_for, at)
            continue          # progress is not an error
        err_lines.append(line)
        if _CORRUPTION_RE.search(line):
            corruption.append(line)
            (startup if at < WARMUP_SECONDS else steady).append(line)

    # Against the video actually decoded, not the wall clock or the requested
    # length -- so a 10s sample and a 25s diagnose of the same stream are
    # directly comparable. They were not: the old gate was an absolute count
    # against a variable sample length, so looking at a channel for longer
    # made it likelier to be condemned.
    window = max(1.0, decoded_for - WARMUP_SECONDS)
    # Checked over the whole stderr text, not just err_lines: ffmpeg's HTTP
    # rejection ("Server returned 403 Forbidden") is often the ONLY line
    # produced before it gives up, and would otherwise never even reach the
    # progress/error split above.
    rate_limited = bool(_RATE_LIMIT_RE.search(err_text))
    out = {
        "decode_errors": len(err_lines),
        "corruption_errors": len(corruption),
        "corruption_startup": len(startup),
        "corruption_steady": len(steady),
        "corruption_per_sec": round(len(steady) / window, 2),
        "decoded_seconds": round(decoded_for, 1),
        "error_samples": (steady or corruption)[:5] or err_lines[:5],
        "capture_seconds": round(elapsed, 1),
        "timed_out": bool(failed),
        "rate_limited": rate_limited,
        "dhash": None,
        "motion": None,
        "motion_frames": 0,
        "low_motion": False,
        "frame32": None,
        "low_contrast": False,
        "measured_kbps": 0,
        "sample_duration": 0.0,
        "thumb": None,
        "frame": None,
        "crop": None,
        "clip": None,
    }

    try:
        ga = _read_gray(raw_a)
        if ga:
            out["low_contrast"] = is_flat(ga)
            out["contrast"] = contrast(ga)
            # A near-uniform frame's hash is noise, so it is deliberately left
            # unset rather than compared against anything.
            if not out["low_contrast"]:
                out["dhash"] = dhash_from_gray(ga)
        if os.path.exists(motion_path):
            with open(motion_path, "rb") as f:
                strip = f.read()
            score, nframes = motion_score(strip)
            out["motion_frames"] = nframes
            if score is not None:
                out["motion"] = round(score, 3)
                out["low_motion"] = score < opts.still_mad
            # Keep one representative frame (1KB, hex) so the cross-stream
            # placeholder pass can compare absolute pixel values, not just
            # dHash structure. See the note above SAME_PICTURE_MAD.
            fr = frames_from_raw(strip)
            if fr:
                out["frame32"] = fr[len(fr) // 2].hex()

        if opts.measure_bitrate and os.path.exists(ts_path):
            size = os.path.getsize(ts_path)
            # Divide by the MEDIA duration of what was captured, never by wall
            # clock. ffmpeg pulls buffered HLS segments far faster than real
            # time -- an 8-second sample routinely downloads in under a second,
            # and using elapsed time inflated every bitrate by 5-10x.
            dur = _media_duration(ts_path, opts) or float(opts.sample_seconds)
            out["sample_duration"] = round(dur, 2)
            if dur > 0:
                out["measured_kbps"] = int(size * 8 / dur / 1000)
        for label, path in (("thumb", thumb_path), ("frame", frame_path),
                            ("crop", crop_path), ("clip", clip_path)):
            if not (path and os.path.exists(path)):
                continue
            size = os.path.getsize(path)
            if label == "clip":
                # A fragmented MP4 (frag_keyframe+empty_moov) that captured
                # zero actual frames is NOT zero bytes -- it still has the
                # ftyp+moov init segment, consistently ~1.2-1.4KB for this
                # two-track (video+audio) layout, just with no moof/mdat
                # fragments after it. That passed a bare size>0 check and got
                # served to the browser as a "successful" clip: technically a
                # valid MP4, but with no samples on any track, which every
                # player correctly refuses to play. Real captured video is
                # tens of KB even for a sub-second fragment, so a floor well
                # above the empty-init-segment size is a reliable signal here,
                # not a fragile magic number tuned to one sample.
                if size > 8192:
                    out[label] = path
            elif size > 0:
                out[label] = path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return out


def served_nothing(cap: dict) -> bool:
    """Did this capture receive a connection that delivered nothing usable?

    Distinct from "this channel is broken", and the distinction is the whole
    point: ffprobe has ALREADY succeeded by the time capture() runs (probe()
    returns STATUS_DEAD before this otherwise), so the provider does have
    something to serve and described it. This is the case where it then
    handed back a stream that decoded to literally zero seconds of video and
    zero bytes, while emitting decode errors the whole way -- the shape a
    connection-limited provider produces instead of refusing cleanly.

    All three conditions together, because each alone is ambiguous:
      no picture     -- could be a thumbnail-selection miss on real video
      zero decoded   -- could be a stream that genuinely just started
      zero bytes     -- could be measure_bitrate being switched off

    Deliberately NOT keyed on the error text. The stderr in the real cases
    is ordinary decoder complaint ("non-existing PPS 0 referenced",
    "decode_slice_header error") -- identical to what a healthy stream emits
    for the fraction of a second before it locks on, which is exactly why
    WARMUP_SECONDS exists. What separates them is not what ffmpeg said, it
    is that nothing whatsoever came out the other end.
    """
    return (cap.get("thumb") is None
            and not cap.get("decoded_seconds")
            and not cap.get("measured_kbps")
            and cap.get("decode_errors", 0) > 0)


def probe(stream, opts: ProbeOptions, thumb_path: str,
          frame_path: str = None, crop_path: str = None,
          clip_path: str = None) -> dict:
    """Full two-stage verification of one stream. Never raises."""
    t0 = time.time()
    meta = probe_metadata(stream.url, opts)
    if meta is None:
        return {"status": STATUS_DEAD, "reason": "no response to ffprobe",
                "total_seconds": round(time.time() - t0, 1)}
    if not meta["has_video"]:
        return {"status": STATUS_NO_VIDEO, "reason": "no video stream", **meta,
                "total_seconds": round(time.time() - t0, 1)}
    if meta.get("container_duration") is not None:
        # Caught here, before ever spending the second (expensive) decode
        # connection -- same principle as STATUS_DEAD/STATUS_NO_VIDEO
        # above, and the exact reason this lives in probe_metadata() rather
        # than capture(): a channel that answers a finite duration to "how
        # long is this live broadcast" has already answered the only
        # question that matters. See _parse_container_duration()'s
        # docstring for why this needs no cross-channel corroboration,
        # unlike annotate_placeholders()'s still-picture matching.
        return {"status": STATUS_PLACEHOLDER, **meta,
                "reason": (f"reports a fixed {meta['container_duration']:.1f}s "
                          "duration; a live channel has none"),
                "total_seconds": round(time.time() - t0, 1)}

    cap = capture(stream.url, opts, thumb_path, frame_path, crop_path, clip_path)
    attempts = 1

    # The clip is an OPTIONAL extra, and it must never be able to cost us the
    # thing the probe actually exists to produce. ffmpeg writes every output
    # of this single pass in one process, so an output it cannot even open --
    # a muxer rejecting the source's audio codec, say -- aborts the whole
    # command and takes the thumbnail, frame, crop and bitrate down with it.
    #
    # The eac3-in-fragmented-MP4 case that motivated this is fixed properly
    # at its source above, but the failure MODE is general: any future codec
    # or container the clip muxer dislikes would silently do the same thing,
    # and it would again look exactly like a dead channel. So if a capture
    # that asked for a clip came back with no picture, immediately try once
    # more WITHOUT the clip before concluding anything about the stream.
    #
    # Deliberately ahead of the retry_empty backoff below, and deliberately
    # not counted as one of its attempts: this is not "the provider might be
    # busy, wait and ask again", it is "our own command may have been
    # unnecessarily fragile, ask again more simply". Retrying the identical
    # broken command on a backoff is pure waste -- a deterministic muxer
    # failure fails identically every time, which is exactly what was
    # observed (four attempts over ~31s, all failing the same way).
    if cap["thumb"] is None and opts.capture_clip and clip_path:
        cap = capture(stream.url, opts, thumb_path, frame_path, crop_path, None)
        attempts += 1
        cap["clip_skipped"] = True

    if cap["thumb"] is None and opts.retry_empty:
        # A capture that produces no picture at all is very often a transient
        # connect failure rather than a broken stream -- seen for real against
        # a proxying IPTV manager, where the first attempt returned in 0.1s
        # having fetched nothing. Retrying costs a connection and avoids
        # condemning a working channel.
        #
        # How hard to retry depends on WHICH kind of empty this is:
        #
        #   served_nothing()  the provider took the connection and delivered
        #                     nothing usable -- measured against real data,
        #                     that is a transient refusal under same-channel
        #                     load and it clears within ~20s, so back off
        #                     properly rather than immediately.
        #   anything else     a one-off miss; the original single quick
        #                     retry is the right cost.
        #
        # Sized against the real failures rather than padded for its own
        # sake: a genuinely broken channel cannot reach here at all (ffprobe
        # would have returned STATUS_DEAD first), so the worst case is a
        # channel whose metadata is fine but which never delivers video --
        # rare, and worth ~30s to be sure about.
        backoff = list(opts.empty_backoff or ()) if served_nothing(cap) else [1.5]
        for delay in backoff:
            time.sleep(delay)
            cap = capture(stream.url, opts, thumb_path, frame_path,
                          crop_path, clip_path)
            attempts += 1
            if cap["thumb"] is not None:
                break
        cap["retried"] = True
    cap["attempts"] = attempts

    result = {**meta, **cap}
    variants = meta.get("video_variant_count", 1)
    result["multi_bitrate_manifest"] = variants > 1
    # Deliberately a SEPARATE, stronger flag rather than folding this into
    # multi_bitrate_manifest above. Tested directly: BBC One's working fix
    # and its original broken source both exposed the same 4 renditions --
    # the HLS master playlist (proven fine in production) flags
    # multi_bitrate_manifest just as positively as the DASH one that
    # actually buffered. Container format, not variant count, was the real
    # differentiator in the one case this has been validated against. A
    # multi-rendition source is a mild, general "more complex relay path"
    # signal either way; multi-rendition-over-DASH specifically is the
    # concrete, evidenced one, and the UI should not present them as equally
    # confident findings.
    result["dash_multi_bitrate"] = variants > 1 and "dash" in (cap.get("container") or "").lower()

    # Live HLS/DASH segments normally download far faster than real time when
    # the CDN/network is healthy -- an 8-10s sample routinely completes in
    # under a second, since ffmpeg pulls whatever is already buffered
    # server-side without waiting. A capture that instead takes close to (or
    # longer than) the sample window itself means delivery could barely keep
    # up with real time, which is exactly what buffering in a real player
    # looks like. `timed_out` catches the extreme case (capture_timeout
    # exceeded); this catches the milder one that still completes but was
    # genuinely slow to.
    result["slow_fetch"] = (not cap.get("timed_out")
                            and cap.get("capture_seconds", 0) >= opts.sample_seconds * 0.9)

    if cap["thumb"] is None:
        # Metadata described a video stream but nothing decoded into a picture.
        # This must never be reported as ok: an earlier version did exactly
        # that, passing a channel that had delivered no frames whatsoever.
        result["status"] = STATUS_NO_FRAME
        if cap.get("rate_limited"):
            # The provider said so explicitly, in HTTP. Rare from the
            # provider this was measured against -- it prefers to hand back
            # garbage (below) -- but free to detect and unambiguous when it
            # does happen.
            result["reason"] = "provider refused the connection (429/403) -- rate limited, not dead"
        elif served_nothing(cap):
            # Say what actually happened rather than blaming the channel.
            # ffprobe saw a real video stream moments earlier, so the
            # provider HAS this stream; it just would not deliver it on
            # this connection, across every retry.
            result["reason"] = (
                f"provider accepted the connection but delivered no decodable "
                f"video at all, on {cap.get('attempts', 1)} attempt(s) over "
                f"~{int(sum(opts.empty_backoff or ()))}s -- the stream itself "
                f"probed fine, so this is the provider declining to serve it "
                f"(usually too many connections to one channel at once)")
            result["provider_declined"] = True
        else:
            result["reason"] = "responded, but no frame could be decoded"
    elif cap.get("corruption_per_sec", 0) > CORRUPTION_RATE_MAX:
        result["status"] = STATUS_DIRTY
        result["reason"] = (f"{cap['corruption_steady']} corruption errors in "
                            f"{cap.get('decoded_seconds', 0)}s of video "
                            f"({cap['corruption_per_sec']}/s)"
                            + (f", {cap['corruption_startup']} more while the "
                               f"decoder locked on"
                               if cap.get("corruption_startup") else ""))
    else:
        # Deliberately NOT a status of its own. Low motion is a hint, not a
        # verdict -- see the note on still_mad in ProbeOptions. The placeholder
        # verdict is assigned later, by the cross-stream pass, which has
        # evidence a single stream cannot provide.
        result["status"] = STATUS_OK
        result["reason"] = ""

    result["total_seconds"] = round(time.time() - t0, 1)
    return result
