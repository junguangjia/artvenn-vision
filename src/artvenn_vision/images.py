"""Read selected local images and create bounded, metadata-free RGB previews."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .storage import VisionError, checkpoint, digest, fingerprint, read_json, require

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
RAW_EXTENSIONS = {".arw", ".dng", ".cr2", ".nef"}
MAX_PIXELS = 80_000_000
MAX_EDGE = 1536


def regular_source(root: Path, path: Path) -> None:
    require(path.is_relative_to(root), "source_outside_selected_folder")
    require(path.is_file(), "source_not_regular_file")
    for component in [path, *path.parents]:
        require(not component.is_symlink(), "source_symlink_refused")
        if component == root:
            break
    require(0 < path.stat().st_size <= 256 * 1024 * 1024, "source_file_size_exceeded")


def render_preview(source: Path, target: Path) -> dict[str, Any]:
    if source.suffix.lower() in RAW_EXTENSIONS:
        result = target.with_name(f"raw-{uuid.uuid4().hex}.json")
        try:
            child = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "artvenn_vision.raw_worker",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--result",
                    str(result),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise VisionError("raw_decode_timeout") from None
        require(result.exists(), "raw_decode_process_failed")
        value = read_json(result)
        require(
            child.returncode == 0 and value.get("status") == "completed",
            value.get("error_category", "raw_decode_process_failed"),
        )
        return value["processing"]
    with Image.open(source) as original:
        require(original.width * original.height <= MAX_PIXELS, "image_pixel_bound_exceeded")
        dimensions = [original.width, original.height]
        image = ImageOps.exif_transpose(original).convert("RGB")
    return save_preview(image, target, dimensions)


def save_preview(image: Image.Image, target: Path, dimensions: list[int]) -> dict[str, Any]:
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    # A new RGB image carries no EXIF, filename, GPS or ICC metadata into inference.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    with target.open("xb") as handle:
        os.chmod(target, 0o600)
        clean.save(handle, "JPEG", quality=92)
    return {
        "source_dimensions": dimensions,
        "preview_dimensions": list(clean.size),
        "recipe": "oriented-rgb-jpeg-1536-v1",
    }


def prepare(
    folder: Path,
    output: Path,
    *,
    recursive: bool = False,
    same_object: bool = False,
    batch_size: int = 8,
) -> dict[str, Any]:
    require(folder.is_dir() and not folder.is_symlink(), "invalid_selected_folder")
    root = folder.resolve()
    destination = output.absolute()
    require(not destination.exists() and not destination.is_symlink(), "output_already_exists")
    require(not destination.resolve().is_relative_to(root), "output_inside_selected_folder")
    require(type(batch_size) is int and 1 <= batch_size <= 8, "invalid_batch_size")
    candidates = root.rglob("*") if recursive else root.iterdir()
    files = sorted(
        (
            path
            for path in candidates
            if path.suffix.lower() in IMAGE_EXTENSIONS | RAW_EXTENSIONS
            and not any(part.startswith(".") for part in path.relative_to(root).parts)
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    require(len(files) > 0, "no_supported_images")
    destination.mkdir(parents=True, mode=0o700)
    previews = destination / "previews"
    previews.mkdir(mode=0o700)
    assets: list[dict[str, Any]] = []
    for index, source in enumerate(files, start=1):
        regular_source(root, source)
        before = digest(source)
        asset_id = f"a{index:04d}"
        preview = previews / f"{asset_id}.jpg"
        processing = render_preview(source, preview)
        require(digest(source) == before, "source_changed_during_preparation")
        assets.append(
            {
                "asset_id": asset_id,
                "source_path": str(source),
                "source_sha256": before,
                "preview": f"previews/{asset_id}.jpg",
                "preview_sha256": digest(preview),
                "processing": processing,
            }
        )
    segments = [
        {
            "segment_id": f"s{index // batch_size + 1:04d}",
            "asset_ids": [asset["asset_id"] for asset in assets[index : index + batch_size]],
        }
        for index in range(0, len(assets), batch_size)
    ]
    job = {
        "schema_version": "artvenn-vision-input-v1",
        "source_root": str(root),
        "same_object": same_object,
        "assets": assets,
        "segments": segments,
    }
    job["fingerprint"] = fingerprint(job)
    checkpoint(destination / "input.json", job)
    return job


def validate_input(run: Path) -> dict[str, Any]:
    from .storage import read_json

    job = read_json(run / "input.json", 256 * 1024 * 1024)
    require(
        isinstance(job, dict) and job.get("schema_version") == "artvenn-vision-input-v1",
        "invalid_input_schema",
    )
    original = {key: value for key, value in job.items() if key != "fingerprint"}
    require(job.get("fingerprint") == fingerprint(original), "input_manifest_changed")
    for asset in job["assets"]:
        source = Path(asset["source_path"])
        regular_source(Path(job["source_root"]), source)
        require(digest(source) == asset["source_sha256"], "source_hash_changed")
        preview = run / asset["preview"]
        require(
            preview.resolve().is_relative_to(run.resolve()) and not preview.is_symlink(),
            "preview_outside_run",
        )
        require(
            preview.is_file() and digest(preview) == asset["preview_sha256"], "preview_hash_changed"
        )
    return job
