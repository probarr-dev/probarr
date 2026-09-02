"""Tracks curator overrides of the algorithm's top-ranked pick, over time.

rank.py's score_key() encodes a fixed set of priorities (integrity before
quality, pixel rate, measured bitrate, HEVC as a tiebreak only, ...). Whether
those priorities actually match what a human picks is an empirical question,
and the honest way to answer it is to record every time a curator's saved
choice disagrees with the algorithm's #1 candidate -- not just once, but
across runs and over time, so the ruleset can eventually be tuned against
real decisions instead of guesses.

One line per override, both candidates' full scoring-relevant flags included
(not just their ids) so a later pass can look for a pattern -- e.g. "curator
always prefers the HD stream over the marginally-higher-bitrate one with any
corruption at all" would show up as a cluster in this log, and that's the
kind of finding that should change score_key(), not just this one pick.

Deliberately global (one file per channeliq instance, not per-run) so patterns
across many runs accumulate in one place rather than being scattered.
"""
import json
import os
import time

FILENAME = "decisions.jsonl"


def _path(root):
    return os.path.join(os.path.abspath(root), FILENAME)


def record(root, entry: dict):
    entry = {**entry, "recorded": time.time()}
    tmp_path = _path(root)
    with open(tmp_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_all(root):
    """All logged overrides, oldest first. [] if nothing has been recorded yet."""
    path = _path(root)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _candidate_summary(c: dict):
    """The scoring-relevant fields for one candidate, as shaped in
    curate.build_payload()'s per-candidate dict -- not the raw probe record.
    """
    return {k: c.get(k) for k in (
        "id", "name", "status", "rank", "w", "h", "fps", "kbps",
        "vcodec", "acodec", "ach", "corrupt", "dup", "lowmo", "abr",
        "dashabr", "slowfetch",
    )}


def log_override(root, run_id, channel_key, channel_title, algorithm_pick,
                 curator_pick):
    """Record one channel's curator-vs-algorithm disagreement.

    algorithm_pick / curator_pick: candidate dicts shaped like the ones in
    curate.build_payload()'s "candidates" list (has "id", "rank", and every
    scoring flag). Caller is responsible for only calling this when the two
    ids actually differ -- this module does not itself decide what counts as
    an override.
    """
    record(root, {
        "run_id": run_id,
        "channel_key": channel_key,
        "channel_title": channel_title,
        "algorithm_pick": _candidate_summary(algorithm_pick),
        "curator_pick": _candidate_summary(curator_pick),
    })


def analyse(root):
    """Turn the override log into a tuning signal.

    Writing the log was only half the point -- until something reads it,
    "the curator disagreed with the ranking 40 times" is a fact sitting in
    a file nobody opens. This aggregates the overrides into the shape that
    can actually change rank.py: for each scoring dimension, how often the
    stream the human chose was WORSE on that dimension than the one the
    algorithm ranked first.

    A dimension the curator consistently accepts a worse value on is one
    score_key() is weighting too highly; one they consistently move toward
    is a signal it is weighting too little, or missing entirely. That is a
    judgement for a person to make -- this reports the evidence, it does
    not retune anything by itself.
    """
    rows = read_all(root)
    if not rows:
        return {"total": 0, "dimensions": [], "recent": []}

    # (label, extractor, higher_is_better)
    dims = [
        ("resolution", lambda c: (c.get("w") or 0) * (c.get("h") or 0), True),
        ("fps", lambda c: c.get("fps") or 0, True),
        ("bitrate", lambda c: c.get("kbps") or 0, True),
        ("audio channels", lambda c: c.get("ach") or 0, True),
        ("corruption errors", lambda c: c.get("corrupt") or 0, False),
    ]
    out = []
    for label, get, higher_better in dims:
        worse = better = same = 0
        for r in rows:
            a, ch = r.get("algorithm_pick") or {}, r.get("curator_pick") or {}
            av, cv = get(a), get(ch)
            if av == cv:
                same += 1
            elif (cv < av) if higher_better else (cv > av):
                worse += 1      # curator accepted a worse value here
            else:
                better += 1     # curator moved toward a better value here
        out.append({"dimension": label, "curator_took_worse": worse,
                   "curator_took_better": better, "same": same})

    # Flags are categorical, not ordered -- reported as "how often the
    # curator moved AWAY from a stream carrying this flag", which is the
    # only direction that means anything for them.
    for flag, label in (("lowmo", "low motion"), ("dup", "placeholder"),
                        ("dashabr", "DASH multi-bitrate"), ("slowfetch", "slow fetch")):
        moved_away = sum(1 for r in rows
                        if (r.get("algorithm_pick") or {}).get(flag)
                        and not (r.get("curator_pick") or {}).get(flag))
        if moved_away:
            out.append({"dimension": f"avoided '{label}'",
                       "curator_took_worse": 0, "curator_took_better": moved_away,
                       "same": 0})

    recent = [{"channel": r.get("channel_title"), "run": r.get("run_id"),
              "from": (r.get("algorithm_pick") or {}).get("name"),
              "to": (r.get("curator_pick") or {}).get("name")}
             for r in rows[-25:]][::-1]
    return {"total": len(rows), "dimensions": out, "recent": recent}
