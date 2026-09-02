"""Full-config backup and restore, as one portable archive.

The gap this closes: "make a backup" meant manually tarring the Docker
volume from outside the app, which nobody using the published image is
going to do, and it's exactly the wrong moment to ask someone to learn that
-- right before switching images, or before trying something risky.

Deliberately NOT a byte-for-byte copy of the whole config directory.
Captured images (thumbs/frames/crops/clips) are left out by default: a run's
own "Clear images" feature already treats them as disposable illustration
rather than the record of truth (results.jsonl is that), and for a run with
a long history they can dwarf everything else combined. Caches
(epg_cache/, catalog_cache/) are left out too, on the same basis channeliq
already treats them everywhere else: they regenerate from their real source
on next use, so backing them up just ships stale data forward.
"""
import io
import os
import tarfile
import time

from .store import RunStore

# Top-level config, not per-run. Everything a fresh install needs to look
# like this one again, short of the actual probe history.
CONFIG_FILES = [
    "providers.json", "lineups.json", "epg_sources.json", "settings.json",
    "aliases.json", "decisions.jsonl",
]
CONFIG_DIRS = ["wantlists"]

# Per-run files worth keeping, excluding the image directories (see above).
RUN_FILES = ["run.json", "wantlist.json", "selection.json", "results.jsonl",
            "push_status.json", "removals.json", "excluded_streams.json"]

IMAGE_DIRS = ["thumbs", "frames", "crops", "clips"]


def export_tar(root, include_images=False):
    """Everything needed to restore this install, as an in-memory tar.gz.

    Returns raw bytes rather than writing to disk -- streamed straight into
    the HTTP response, so nothing is left behind on the server after a
    download the way a "write to a temp file first" approach would.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in CONFIG_FILES:
            path = os.path.join(root, name)
            if os.path.exists(path):
                tar.add(path, arcname=name)
        for name in CONFIG_DIRS:
            path = os.path.join(root, name)
            if os.path.isdir(path):
                tar.add(path, arcname=name)
        for meta in RunStore.list_runs(root):
            run_id = meta.get("run_id")
            if not run_id:
                continue
            run_dir = os.path.join(root, run_id)
            for fname in RUN_FILES:
                fpath = os.path.join(run_dir, fname)
                if os.path.exists(fpath):
                    tar.add(fpath, arcname=f"{run_id}/{fname}")
            if include_images:
                for sub in IMAGE_DIRS:
                    subpath = os.path.join(run_dir, sub)
                    if os.path.isdir(subpath):
                        tar.add(subpath, arcname=f"{run_id}/{sub}")
    return buf.getvalue()


def export_filename():
    return "channeliq-backup-" + time.strftime("%Y%m%d-%H%M%S") + ".tar.gz"


def import_tar(root, data):
    """Restore a backup produced by export_tar(). Overwrites in place.

    A tar file is untrusted input the moment it arrived as a browser
    upload -- a member path like "../../etc/passwd" is a textbook
    path-traversal payload, not a hypothetical one, so every member's
    resolved path is confirmed to land inside `root` BEFORE anything is
    written, and extraction is done by hand rather than via extractall()
    so that check is the only thing deciding what touches disk. Symlinks
    and anything else that isn't a plain file or directory are refused
    outright -- a legitimate backup never contains one.
    """
    root_real = os.path.realpath(root)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"refusing non-file member in backup: {member.name}")
            target = os.path.realpath(os.path.join(root, member.name))
            if target != root_real and not target.startswith(root_real + os.sep):
                raise ValueError(f"refusing unsafe path in backup: {member.name}")
        for member in members:
            target = os.path.realpath(os.path.join(root, member.name))
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(member)
            with open(target, "wb") as dst:
                dst.write(src.read())
    return True
