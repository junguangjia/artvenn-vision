from __future__ import annotations

import pytest
from PIL import Image

from artvenn_vision.images import prepare, validate_input
from artvenn_vision.storage import VisionError, digest


def test_sources_unchanged_previews_private_and_oriented(tmp_path):
    source = tmp_path / "photos"
    source.mkdir()
    original = source / "portrait.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "Synthetic source metadata"
    Image.new("RGB", (2400, 1200), "gray").save(original, exif=exif)
    before = digest(original)
    run = tmp_path / "run"
    job = prepare(source, run)
    assert digest(original) == before
    preview = run / job["assets"][0]["preview"]
    with Image.open(preview) as image:
        assert image.size == (768, 1536)
        assert image.mode == "RGB"
        assert not image.getexif()
    assert preview.stat().st_mode & 0o777 == 0o600
    assert run.stat().st_mode & 0o777 == 0o700
    assert validate_input(run) == job


def test_windows_are_not_object_identity(photos, tmp_path):
    job = prepare(photos, tmp_path / "run", batch_size=2, same_object=True)
    assert len(job["assets"]) == 3
    assert len(job["segments"]) == 2
    assert job["same_object"] is True


def test_changed_source_refuses_resume(photos, tmp_path):
    run = tmp_path / "run"
    prepare(photos, run)
    (photos / "0.jpg").write_bytes(b"changed")
    with pytest.raises(VisionError, match="source_hash_changed"):
        validate_input(run)


def test_changed_preview_refuses_resume(photos, tmp_path):
    run = tmp_path / "run"
    prepare(photos, run)
    (run / "previews/a0001.jpg").write_bytes(b"changed")
    with pytest.raises(VisionError, match="preview_hash_changed"):
        validate_input(run)


def test_symlink_photo_is_rejected(photos, tmp_path):
    (photos / "linked.jpg").symlink_to(photos / "0.jpg")
    with pytest.raises(VisionError, match="source_symlink_refused"):
        prepare(photos, tmp_path / "run")


def test_output_inside_source_refused(photos):
    with pytest.raises(VisionError, match="output_inside_selected_folder"):
        prepare(photos, photos / "run", recursive=True)


def test_existing_output_never_replaced(photos, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    marker = run / "owner-file"
    marker.write_text("retain")
    with pytest.raises(VisionError, match="output_already_exists"):
        prepare(photos, run)
    assert marker.read_text() == "retain"


def test_subfolders_opt_in(photos, tmp_path):
    child = photos / "nested"
    child.mkdir()
    Image.new("RGB", (50, 50)).save(child / "extra.png")
    assert len(prepare(photos, tmp_path / "flat")["assets"]) == 3
    assert len(prepare(photos, tmp_path / "recursive", recursive=True)["assets"]) == 4


def test_raw_timeout_is_isolated(tmp_path, monkeypatch):
    import subprocess

    from artvenn_vision.images import render_preview

    commands = []

    def timeout(command, **kwargs):
        commands.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("artvenn_vision.images.subprocess.run", timeout)
    with pytest.raises(VisionError, match="raw_decode_timeout"):
        render_preview(tmp_path / "synthetic.nef", tmp_path / "preview.jpg")
    assert commands[0][0][2] == "artvenn_vision.raw_worker"
    assert commands[0][1]["timeout"] == 60
