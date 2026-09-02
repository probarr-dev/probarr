"""Perceptual difference-hash (dHash) over a 9x8 grayscale frame.

Used here for PLACEHOLDER DETECTION, and it is worth being precise about what
that can and cannot find, because the obvious framing is wrong.

The tempting claim is "hash every channel's frame, and channels that hash the
same are the same feed relabelled". That does not work. Two streams probed
minutes apart show different frames *even when they are genuinely the same
feed*, because live content moves on in between. Detecting duplicate live
feeds would require capturing both within a second or two of each other, which
is exactly what a connection-limited provider forbids.

What frame hashing detects reliably is a **static image**. Providers answer
"connection busy", "channel unavailable" or an out-of-hours channel with a
placeholder card, re-encoded at whatever resolution that particular "channel"
is nominally served at. So:

  primary signal    a stream whose picture does not change over several
                    seconds is showing a still, not live television
  corroborating     when several channels serve the *same* still, that still
                    is almost certainly the provider's placeholder rather than
                    one channel legitimately off-air

A byte hash (md5/sha256) is useless for the corroborating step, since the same
card re-encoded at a different resolution has a completely different checksum.
A dHash compares relative brightness between neighbouring pixels, so it
survives re-encoding.

Deliberately implemented here rather than pulled from Pillow/imagehash: the
9x8 grayscale downscale is something ffmpeg already does for free during the
frame grab, so the whole dependency disappears for ~15 lines of code.
"""

GRID_W = 9  # one extra column: 8 comparisons per row
GRID_H = 8
RAW_SIZE = GRID_W * GRID_H

# Two frames within this Hamming distance (of 64 bits) are treated as the same
# picture. Genuinely different live content typically differs by 20-30+ bits;
# re-encodes of one banner land at 0-6.
DEFAULT_DUP_THRESHOLD = 8

# Two frames from the SAME stream, seconds apart, within this distance means
# the picture is not moving. Tighter than the cross-stream threshold because
# there is no re-encoding difference to absorb -- it is the same decoder on
# the same stream, so real motion shows up immediately.
STILL_THRESHOLD = 3

# Minimum spread between the darkest and brightest cell of the 9x8 block for
# the hash to mean anything. Below this the frame is a near-uniform wash (a
# dark scene, a fade, a black slate) and its hash is dominated by noise --
# comparing it to anything produces false matches. Found in testing: two
# unrelated BBC channels that both happened to be on a dark shot hashed within
# 6 bits of each other and were wrongly grouped.
MIN_CONTRAST = 12


def dhash_from_gray(raw: bytes) -> str:
    """64-bit dHash of a 9x8 8-bit grayscale buffer, as 16 hex chars."""
    if len(raw) < RAW_SIZE:
        raise ValueError(f"expected {RAW_SIZE} grayscale bytes, got {len(raw)}")
    bits = 0
    for row in range(GRID_H):
        base = row * GRID_W
        for col in range(GRID_W - 1):
            bits <<= 1
            if raw[base + col] > raw[base + col + 1]:
                bits |= 1
    return format(bits, "016x")


def hamming(a: str, b: str) -> int:
    """Bit distance between two hex dHashes."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def contrast(raw: bytes) -> int:
    """Spread between the darkest and brightest cell of the block."""
    return (max(raw) - min(raw)) if raw else 0


def is_flat(raw: bytes, tolerance: int = MIN_CONTRAST) -> bool:
    """True if the frame carries too little contrast for its hash to be trusted.

    A fully black frame hashes to 0000000000000000 and would collide with every
    other black frame, inventing a large bogus placeholder group. A merely
    *dark* frame is nearly as bad. Callers should treat these as 'no usable
    picture for comparison' rather than as a finding.
    """
    return contrast(raw) < tolerance


# dHash alone is not sufficient to say two frames are the same picture, and
# placeholder cards are the worst case for it. dHash records only whether each
# pixel is brighter than its right-hand neighbour, discarding absolute
# brightness and colour entirely. A smooth gradient therefore hashes to
# almost-all-zeros no matter WHAT gradient it is.
#
# Measured: BBC Four's purple off-air card hashed 0808000030000808 and BBC
# Three's green one hashed 0000000000000008 -- 5 bits apart, well inside the
# match threshold, despite being obviously different pictures. Two unrelated
# channels were declared the same placeholder.
#
# The fix is to require agreement on absolute pixel values too, using the
# 32x32 grayscale frame already captured for motion measurement. Purple and
# green differ enormously there. Both tests must pass.
SAME_PICTURE_MAD = 10.0


def frame_mad(a: bytes, b: bytes) -> float:
    """Mean absolute difference between two equal-length grayscale frames."""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def group_identical(hashes, threshold=DEFAULT_DUP_THRESHOLD, frames=None,
                    mad_threshold=SAME_PICTURE_MAD):
    """Cluster {key: hexhash} into groups of mutually near-identical frames.

    Returns {key: group_id} containing only keys that share their picture with
    at least one other key. Single-linkage clustering via union-find, so a
    card served to twenty channels forms one group rather than 190 pairs.

    Only meaningful for frames already known to be still: see the module
    docstring for why matching moving content across channels does not work.
    """
    keys = [k for k, v in hashes.items() if v]
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    frames = frames or {}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if hamming(hashes[a], hashes[b]) > threshold:
                continue
            # Second, independent test on absolute pixel values. Skipped only
            # when a frame is unavailable, in which case dHash alone decides.
            fa, fb = frames.get(a), frames.get(b)
            if fa and fb and frame_mad(fa, fb) > mad_threshold:
                continue
            union(a, b)

    clusters = {}
    for k in keys:
        clusters.setdefault(find(k), []).append(k)

    out, gid = {}, 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        gid += 1
        for m in members:
            out[m] = gid
    return out


# --- motion measurement -------------------------------------------------
#
# Separate from dHash on purpose. dHash answers "is this the same picture?"
# at a deliberately coarse 9x8, which is exactly right for matching a
# placeholder card re-encoded at different resolutions -- and exactly wrong
# for detecting movement.
#
# Measured on live television: a fixed studio camera (BBC Breakfast) differed
# by only 2 bits of 64 across five seconds at 9x8, indistinguishable from a
# genuinely frozen card. Downscaling that far destroys the very detail that
# distinguishes a talking presenter from a still image.
#
# So motion is measured on a 32x32 grid sampled across the whole capture
# window, as mean absolute difference between consecutive frames.

MOTION_GRID = 32
MOTION_FRAME_BYTES = MOTION_GRID * MOTION_GRID

# Mean absolute 8-bit difference between consecutive frames, below which the
# picture is flagged as suspiciously static for a human to check. Set to catch
# the low end generously, because it costs a glance and misses nothing:
# ordinary programming measured 4-20 in testing, while both genuine off-air
# cards AND one live fixed-camera studio shot fell below 2.5.
STILL_MAD = 2.5


def frames_from_raw(raw: bytes, frame_bytes: int = MOTION_FRAME_BYTES):
    return [raw[i:i + frame_bytes]
            for i in range(0, len(raw) - frame_bytes + 1, frame_bytes)]


def motion_score(raw: bytes, frame_bytes: int = MOTION_FRAME_BYTES):
    """Mean absolute difference between consecutive frames, 0-255.

    Returns (score, frames_compared). None when there is too little to judge.
    """
    frames = frames_from_raw(raw, frame_bytes)
    if len(frames) < 2:
        return None, len(frames)
    diffs = []
    for a, b in zip(frames, frames[1:]):
        diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / float(frame_bytes))
    # Mean rather than max: a single decode glitch or a hard cut should not
    # make a frozen card look alive, and averaging over the window smooths
    # both out.
    return (sum(diffs) / len(diffs)), len(frames)
