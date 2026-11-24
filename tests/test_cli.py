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
    moved = sorted(p.relative_to(out).parts[0] for p in out.rglob("*") if p.is_file() and not p.name.startswith("."))
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
    assert len([p for p in out.rglob("*") if p.is_file() and not p.name.startswith(".")]) == 2


def test_missing_source_fails(tmp_path):
    r = run("--source", str(tmp_path / "nope"))
    assert r.returncode == 1


def files_in(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and not p.name.startswith("."))


def test_undo_restores_files_and_removes_empty_folders(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    run("--source", str(src), "--target", str(out))
    assert not (src / "a.jpg").exists()
    r = run("--undo", "--target", str(out))
    assert r.returncode == 0
    assert (src / "a.jpg").read_bytes() == b"not a real jpg" and (src / "song.mp3").exists()
    assert files_in(out) == [] and not (out / "Image").exists()
    assert "restored 0" in run("--undo", "--target", str(out)).stderr + run("--undo", "--target", str(out)).stdout


def test_undo_two_runs_one_at_a_time(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"1")
    run("--source", str(src), "--target", str(out))
    (src / "b.mp3").write_bytes(b"2")
    run("--source", str(src), "--target", str(out))
    run("--undo", "--target", str(out))
    assert (src / "b.mp3").exists() and not (src / "a.jpg").exists()
    run("--undo", "--target", str(out))
    assert (src / "a.jpg").exists()


def test_copy_keeps_originals_and_undo_deletes_copies(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    run("--source", str(src), "--target", str(out), "--copy")
    assert (src / "a.jpg").exists() and len(files_in(out)) == 2
    run("--undo", "--target", str(out))
    assert (src / "a.jpg").exists() and files_in(out) == []


def test_dedupe_skips_identical_content_under_other_name(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "one.jpg").write_bytes(b"same bytes")
    (src / "copy of one.jpg").write_bytes(b"same bytes")
    (src / "different.jpg").write_bytes(b"other bytes")
    r = run("--source", str(src), "--target", str(out), "--dedupe")
    assert r.returncode == 0
    assert len(files_in(out)) == 2
    assert "Duplicates: 1" in r.stderr + r.stdout
    assert len([p for p in src.iterdir() if p.suffix == ".jpg"]) == 1  # the duplicate stays in the source


def test_no_recursive_ignores_subfolders(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    (src / "deep").mkdir()
    (src / "deep" / "x.jpg").write_bytes(b"x")
    run("--source", str(src), "--target", str(out), "--no-recursive")
    assert (src / "deep" / "x.jpg").exists()
    run("--source", str(src), "--target", str(tmp_path / "out2"))
    assert not (src / "deep" / "x.jpg").exists()


def test_report_json_and_document_count(tmp_path):
    import json
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    (src / "cv.pdf").write_bytes(b"d")
    rep = tmp_path / "report.json"
    r = run("--source", str(src), "--target", str(out), "--report", str(rep))
    data = json.loads(rep.read_text())
    assert data["stats"]["documents"] == 1 and data["stats"]["moved"] == 3
    assert {f["action"] for f in data["files"]} == {"moved"}


def test_exif_date_decides_folder(tmp_path):
    from PIL import Image
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    im = Image.new("RGB", (8, 8))
    ex = Image.Exif()
    ex.get_ifd(0x8769)[0x9003] = "2019:07:04 12:00:00"
    im.save(src / "trip.jpg", exif=ex)
    run("--source", str(src), "--target", str(out))
    assert files_in(out) == ["Image/2019/July/trip.jpg"]


def test_undo_needs_target(tmp_path):
    assert run("--undo").returncode == 1


# ---- safety and config ----
def test_undo_never_overwrites_new_file_at_original_path(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"original")
    run("--source", str(src), "--target", str(out))
    (src / "a.jpg").write_bytes(b"NEW file made later")
    run("--undo", "--target", str(out))
    assert (src / "a.jpg").read_bytes() == b"NEW file made later"
    assert [p for p in out.rglob("a.jpg")][0].read_bytes() == b"original"  # still safe in the target


def test_undo_keeps_edits_to_a_moved_file(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "n.txt").write_bytes(b"v1")
    run("--source", str(src), "--target", str(out))
    next(out.rglob("n.txt")).write_bytes(b"v2 edited")
    run("--undo", "--target", str(out))
    assert (src / "n.txt").read_bytes() == b"v2 edited"


def test_copy_undo_keeps_a_copy_that_was_edited(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "n.txt").write_bytes(b"v1")
    (src / "m.txt").write_bytes(b"untouched")
    run("--source", str(src), "--target", str(out), "--copy")
    next(out.rglob("n.txt")).write_bytes(b"edited after copying!")
    run("--undo", "--target", str(out))
    assert next(out.rglob("n.txt")).read_bytes() == b"edited after copying!"  # not deleted
    assert not list(out.rglob("m.txt"))                                          # unchanged copy removed
    assert (src / "n.txt").read_bytes() == b"v1" and (src / "m.txt").exists()   # originals intact


def test_symlinks_are_ignored(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"s")
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "real.jpg").write_bytes(b"r")
    (src / "link.jpg").symlink_to(outside / "secret.jpg")
    (src / "linkdir").symlink_to(outside, target_is_directory=True)
    run("--source", str(src), "--target", str(out))
    assert (outside / "secret.jpg").exists() and (src / "link.jpg").is_symlink()
    assert [p.name for p in out.rglob("*.jpg")] == ["real.jpg"]


def test_second_run_is_a_no_op(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    run("--source", str(src), "--target", str(out))
    before = files_in(out)
    r = run("--source", str(src), "--target", str(out))
    assert r.returncode == 0 and files_in(out) == before
    assert "Moved:      0" in r.stderr + r.stdout
    run("--undo", "--target", str(out))        # undo of the empty second run must not exist...
    assert (src / "a.jpg").exists() is True    # ...so this restores the first run


def test_permission_failure_is_reported_and_other_files_still_move(tmp_path):
    import os
    src, out = tmp_path / "in", tmp_path / "out"
    make_files(src)
    locked = src / "locked"
    locked.mkdir()
    (locked / "stuck.jpg").write_bytes(b"stuck")
    os.chmod(locked, 0o555)
    try:
        if os.access(locked, os.W_OK):
            import pytest
            pytest.skip("account ignores permissions")
        r = run("--source", str(src), "--target", str(out))
        assert r.returncode == 1
        assert (locked / "stuck.jpg").read_bytes() == b"stuck"
        assert not list(out.rglob("stuck*.jpg"))              # no stray copy left behind
        assert (out / "Audio").exists() or list(out.rglob("song.mp3"))
        run("--undo", "--target", str(out))
        assert (src / "song.mp3").exists() and (locked / "stuck.jpg").exists()
    finally:
        os.chmod(locked, 0o755)


def test_folder_format_is_used_and_validated(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "song.mp3").write_bytes(b"x")
    r = run("--source", str(src), "--target", str(out), "--folder-format", "{type}")
    assert r.returncode == 0 and files_in(out) == ["Audio/song.mp3"]
    (src / "song.mp3").write_bytes(b"x")  # the first run moved it
    for bad in ("{type}/{foo}", "../escape", "/abs/{type}", "{type"):
        r = run("--source", str(src), "--target", str(tmp_path / "o2"), "--folder-format", bad)
        assert r.returncode == 1, bad
        assert (src / "song.mp3").exists() and not (tmp_path / "o2").exists(), bad


def test_config_file_works_and_rejects_unknown_keys(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    (src / "song.mp3").write_bytes(b"x")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f'source_dir: "{src}"\ntarget_dir: "{out}"\nfolder_format: "{{type}}/{{%Y}}"\n')
    r = run("--source", str(src), "--config", str(cfg))
    assert r.returncode == 0 and len(files_in(out)) == 1 and files_in(out)[0].count("/") == 2
    cfg.write_text("source_dir: x\nfolder_fromat: oops\n")
    r = run("--source", str(src), "--config", str(cfg))
    assert r.returncode == 1 and "folder_fromat" in r.stderr + r.stdout


def test_shipped_config_yaml_is_valid():
    from pathlib import Path as P
    import sys
    sys.path.insert(0, str(P(__file__).parent.parent / "src"))
    from config import Config
    cfg = Config.from_yaml(P(__file__).parent.parent / "config.yaml")
    assert cfg.folder_format == "{type}/{%Y}/{%B}"
