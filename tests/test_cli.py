"""End-to-end tests: run main.py on a temporary folder."""
import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).parent.parent / "main.py"


def run(*args):
    return subprocess.run([sys.executable, str(MAIN), *args], capture_output=True, text=True, timeout=60)


def make_files(src: Path):
    src.mkdir()
    (src / "a.jpg").write_bytes(b"not a real jpg")
    (src / "song.mp3").write_bytes(b"x")
    (src / "notes.xyz").write_bytes(b"unknown type stays put")


def test_dry_run_moves_nothing(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    r = run("--source", str(src), "--target", str(out), "--dry-run")
    assert r.returncode == 0
    assert (src / "a.jpg").exists() and (src / "song.mp3").exists()
    assert not out.exists()
    assert "Planned (dry-run): 2" in r.stderr + r.stdout


def test_real_run_moves_files_into_type_year_month(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    r = run("--source", str(src), "--target", str(out))
    assert r.returncode == 0
    moved = sorted(p.relative_to(out).parts[0] for p in out.rglob("*") if p.is_file())
    assert moved == ["Audio", "Image"]
    assert not (src / "a.jpg").exists()
    assert (src / "notes.xyz").exists()  # unknown types are left alone


def test_name_collision_never_overwrites(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    run("--source", str(src), "--target", str(out))
    (src / "a.jpg").write_bytes(b"second file, same name")
    run("--source", str(src), "--target", str(out))
    names = sorted(p.name for p in out.rglob("a*.jpg"))
    assert names == ["a.jpg", "a_1.jpg"]


def test_target_inside_source_is_not_reprocessed(tmp_path):
    src = tmp_path / "in"
    make_files(src)
    out = src / "organized"
    run("--source", str(src), "--target", str(out))
    r = run("--source", str(src), "--target", str(out))
    assert r.returncode == 0
    assert len([p for p in out.rglob("*") if p.is_file()]) == 2


def test_missing_source_fails(tmp_path):
    r = run("--source", str(tmp_path / "nope"))
    assert r.returncode == 1
