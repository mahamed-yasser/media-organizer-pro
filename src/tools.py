"""Helpers added in v2: photo dates, duplicate detection, undo log and report."""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

UNDO_FILE = ".media-organizer-undo.json"
MAX_UNDO_RUNS = 20


def photo_date(path: Path) -> datetime:
    """Date a photo was taken (EXIF DateTimeOriginal), else the file's modified time."""
    if path.suffix.lower() in {".jpg", ".jpeg", ".tiff", ".webp"}:
        try:
            from PIL import Image
            with Image.open(path) as im:
                exif = im.getexif()
                raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)  # taken, else modified
                if raw:
                    return datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class DuplicateIndex:
    """Remember content hashes so exact duplicates (same bytes, any name) can be skipped."""

    def __init__(self, target: Path):
        self.seen: dict[tuple[int, str], Path] = {}
        if target.is_dir():
            for p in target.rglob("*"):
                if p.is_file() and not p.name.startswith("."):
                    self._add(p)

    def _add(self, p: Path):
        self.seen[(p.stat().st_size, file_hash(p))] = p

    def original_of(self, p: Path):
        """Path of an identical file already seen, or None. Records p when it is new."""
        key = (p.stat().st_size, file_hash(p))
        if key in self.seen:
            return self.seen[key]
        self.seen[key] = p
        return None


def load_undo(target: Path) -> list:
    try:
        data = json.loads((target / UNDO_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_undo_run(target: Path, moves: list):
    if not moves:
        return
    runs = load_undo(target)
    runs.append({"at": datetime.now().isoformat(timespec="seconds"), "moves": moves})
    (target / UNDO_FILE).write_text(json.dumps(runs[-MAX_UNDO_RUNS:], indent=2), encoding="utf-8")


def undo_last_run(target: Path):
    """Restore the files of the last run. Copies made with --copy are deleted, moves are moved back.

    Returns (restored, skipped). A file is skipped if it is gone or its original spot is taken.
    """
    runs = load_undo(target)
    if not runs:
        return 0, 0
    run = runs.pop()
    restored = skipped = 0
    for m in reversed(run["moves"]):
        src, dest = Path(m["from"]), Path(m["to"])
        if not dest.exists():
            skipped += 1
        elif m.get("copy"):
            st = dest.stat()
            if (st.st_size, st.st_mtime_ns) != (m.get("size"), m.get("mtime_ns")):
                skipped += 1  # the copy was changed after the run: keep it, it is no longer a plain copy
            else:
                dest.unlink()
                restored += 1
        elif src.exists():
            skipped += 1
        else:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            restored += 1
        d = dest.parent
        while d != target and target in d.parents:  # remove folders the run created, only if empty
            try:
                d.rmdir()
            except OSError:
                break
            d = d.parent
    (target / UNDO_FILE).write_text(json.dumps(runs, indent=2), encoding="utf-8")
    return restored, skipped


def write_report(path: Path, stats: dict, actions: list):
    path.write_text(json.dumps({"created": datetime.now().isoformat(timespec="seconds"),
                                "stats": stats, "files": actions}, indent=2), encoding="utf-8")
