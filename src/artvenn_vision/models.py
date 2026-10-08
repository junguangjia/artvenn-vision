"""Explicit, pinned model artifacts; analysis never downloads models."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from .storage import checkpoint, digest, read_json, require

REQUIRED_FILES = {
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
}
ARTIFACT_EXTENSIONS = {".json", ".txt", ".jinja"}


def model_artifacts(directory: Path) -> list[dict[str, Any]]:
    return [
        {"name": path.name, "size_bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(directory.iterdir())
        if path.suffix in ARTIFACT_EXTENSIONS and path.is_file()
    ]


def default_profile() -> Path:
    return Path(str(files("artvenn_vision").joinpath("profiles/qwen3-vl-4b.json")))


def validate_profile(profile: Any) -> dict[str, Any]:
    require(
        isinstance(profile, dict) and profile.get("schema_version") == "artvenn-vision-model-v1",
        "invalid_model_profile",
    )
    require(
        isinstance(profile.get("model_id"), str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", profile["model_id"]) is not None,
        "invalid_model_id",
    )
    require(
        isinstance(profile.get("revision"), str)
        and re.fullmatch(r"[a-f0-9]{40}", profile["revision"]) is not None,
        "model_revision_must_be_exact_commit",
    )
    require(
        profile.get("model_type") == "qwen3_vl" and profile.get("quantization_bits") == 4,
        "only_qwen3_vl_4bit_supported",
    )
    weights = profile.get("weights")
    require(isinstance(weights, list) and 0 < len(weights) <= 64, "invalid_model_weights")
    names = set()
    for weight in weights:
        require(isinstance(weight, dict), "invalid_weight_entry")
        name = weight.get("name")
        require(
            isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+\.safetensors", name) is not None
            and name not in names,
            "invalid_weight_name",
        )
        names.add(name)
        require(
            type(weight.get("size_bytes")) is int and weight["size_bytes"] > 0,
            "invalid_weight_size",
        )
        require(
            isinstance(weight.get("sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", weight["sha256"]) is not None,
            "invalid_weight_hash",
        )
    artifacts = profile.get("artifacts")
    require(isinstance(artifacts, list) and 0 < len(artifacts) <= 128, "invalid_model_artifacts")
    artifact_names = set()
    for artifact in artifacts:
        require(isinstance(artifact, dict), "invalid_artifact_entry")
        name = artifact.get("name")
        require(
            isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+\.(json|txt|jinja)", name) is not None
            and name not in artifact_names,
            "invalid_artifact_name",
        )
        artifact_names.add(name)
        require(
            type(artifact.get("size_bytes")) is int and artifact["size_bytes"] >= 0,
            "invalid_artifact_size",
        )
        require(
            isinstance(artifact.get("sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"]) is not None,
            "invalid_artifact_hash",
        )
    require(REQUIRED_FILES <= artifact_names, "missing_required_model_artifacts")
    return profile


def verify_model(directory: Path, profile: dict[str, Any]) -> None:
    validate_profile(profile)
    require(directory.is_dir(), "missing_local_model")
    # Existing Hugging Face cache files may be symlinks to immutable cache blobs.
    for name in REQUIRED_FILES:
        require((directory / name).is_file(), "incomplete_local_model")
    config = read_json((directory / "config.json").resolve())
    # MLX-VLM 0.7.4 executes model_file even with trust_remote_code=False.
    # This package supports its built-in Qwen3-VL implementation only.
    require("model_file" not in config, "custom_model_code_refused")
    require(
        config.get("model_type") == profile["model_type"]
        and config.get("quantization", {}).get("bits") == profile["quantization_bits"],
        "model_config_mismatch",
    )
    actual_names = {path.name for path in directory.glob("*.safetensors")}
    require(
        actual_names == {weight["name"] for weight in profile["weights"]},
        "model_weight_files_mismatch",
    )
    for weight in profile["weights"]:
        path = directory / weight["name"]
        require(
            path.is_file() and path.stat().st_size == weight["size_bytes"],
            "model_weight_size_mismatch",
        )
        require(digest(path) == weight["sha256"], "model_weight_hash_mismatch")
    require(model_artifacts(directory) == profile["artifacts"], "model_artifact_hash_mismatch")


def register_model(directory: Path, model_id: str, revision: str, output: Path) -> dict[str, Any]:
    require(not output.exists() and not output.is_symlink(), "output_already_exists")
    require(
        not output.resolve().is_relative_to(directory.resolve()), "profile_inside_model_refused"
    )
    config = read_json((directory / "config.json").resolve())
    profile = {
        "schema_version": "artvenn-vision-model-v1",
        "model_id": model_id,
        "revision": revision,
        "model_type": config.get("model_type"),
        "quantization_bits": config.get("quantization", {}).get("bits"),
        "weights": [
            {"name": path.name, "size_bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(directory.glob("*.safetensors"))
        ],
        "artifacts": model_artifacts(directory),
    }
    validate_profile(profile)
    verify_model(directory, profile)
    checkpoint(output, profile)
    return profile


def download_model(directory: Path, profile_path: Path) -> dict[str, Any]:
    """Download only the explicit public revision, without using a cached login token."""
    profile = validate_profile(read_json(profile_path))
    require(not directory.exists(), "model_destination_already_exists")
    from huggingface_hub import snapshot_download

    directory.mkdir(parents=True, mode=0o700)
    snapshot_download(
        repo_id=profile["model_id"],
        revision=profile["revision"],
        token=False,
        local_dir=str(directory),
        max_workers=2,
        allow_patterns=["*.json", "*.txt", "*.jinja", *[w["name"] for w in profile["weights"]]],
    )
    verify_model(directory, profile)
    return profile
