"""Resume matching successful windows and preserve explicit user grouping."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .images import validate_input
from .models import validate_profile, verify_model
from .schema import PROMPT_VERSION, validate_proposal
from .storage import checkpoint, fingerprint, private_new, read_json, require

MAX_RESULT_BYTES = 256 * 1024 * 1024


def grouping(job: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    if job["same_object"]:
        return {
            "authority": "user_declaration",
            "human_review_required": True,
            "objects": [
                {
                    "key": "declared_object",
                    "asset_ids": [asset["asset_id"] for asset in job["assets"]],
                }
            ],
            "cross_window_identity": "declared_by_user",
        }
    objects = [
        {"key": f"{segment['segment_id']}_{group['key']}", "asset_ids": group["asset_ids"]}
        for segment in segments
        if segment["status"] == "completed"
        for group in segment["proposal"]["groups"]
    ]
    return {
        "authority": "ai_proposal",
        "human_review_required": True,
        "objects": objects,
        "cross_window_identity": "unresolved" if len(job["segments"]) > 1 else "single_window",
    }


def merge_records(
    job: dict[str, Any], retained: list[dict[str, Any]], attempt: dict[str, Any]
) -> list[dict[str, Any]]:
    expected = {segment["segment_id"]: segment["asset_ids"] for segment in job["segments"]}
    found = {}
    for record in retained + attempt.get("segments", []):
        require(
            isinstance(record, dict) and record.get("segment_id") in expected,
            "unexpected_checkpoint_segment",
        )
        key = record["segment_id"]
        require(key not in found, "duplicate_checkpoint_segment")
        require(record.get("status") in {"completed", "failed"}, "invalid_checkpoint_status")
        if record["status"] == "completed":
            validate_proposal(record.get("proposal"), expected[key])
        found[key] = record
    return [
        found.get(
            segment["segment_id"],
            {
                "segment_id": segment["segment_id"],
                "status": "failed",
                "proposal": None,
                "error_category": attempt.get("error_category", "segment_not_completed"),
            },
        )
        for segment in job["segments"]
    ]


def stop_child(child: subprocess.Popen) -> None:
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=3)


def analyze(
    run: Path,
    model_dir: Path,
    profile_path: Path,
    *,
    timeout: int = 900,
    segment_timeout: int = 180,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    run = run.absolute()
    require(run.is_dir() and not run.is_symlink(), "invalid_run_directory")
    require(type(timeout) is int and 30 <= timeout <= 3600, "invalid_overall_timeout")
    require(
        type(segment_timeout) is int and 30 <= segment_timeout <= 600, "invalid_segment_timeout"
    )
    require(type(max_tokens) is int and 512 <= max_tokens <= 6144, "invalid_token_limit")
    # One writer per run; never adopt an existing lock or mutate a competing run.
    lock = run / ".analysis.lock"
    with private_new(lock):
        pass
    try:
        return _analyze(run, model_dir, profile_path, timeout, segment_timeout, max_tokens)
    finally:
        lock.unlink()


def _analyze(
    run: Path,
    model_dir: Path,
    profile_path: Path,
    timeout: int,
    segment_timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    job = validate_input(run)
    profile = validate_profile(read_json(profile_path))
    verify_model(model_dir, profile)
    binding = fingerprint(
        {
            "input": job["fingerprint"],
            "model": profile,
            "prompt": PROMPT_VERSION,
            "max_tokens": max_tokens,
            "segment_timeout": segment_timeout,
        }
    )
    result_path = run / "result.json"
    retained = []
    if result_path.exists():
        previous = read_json(result_path, MAX_RESULT_BYTES)
        require(previous.get("binding") == binding, "resume_configuration_changed")
        retained = [segment for segment in previous["segments"] if segment["status"] == "completed"]
        # Revalidate persisted proposals before treating them as successful checkpoints.
        merge_records(job, retained, {})
        if len(retained) == len(job["segments"]):
            # Never accept cached top-level authority or approval flags.
            previous = {
                key: previous.get(key)
                for key in {
                    "schema_version",
                    "binding",
                    "status",
                    "human_review_required",
                    "cloud",
                    "mock",
                    "model",
                    "prompt_version",
                    "segments",
                    "grouping",
                    "attempt",
                    "attempt_seconds",
                    "reused_segments",
                }
            }
            previous.update(
                schema_version="artvenn-vision-result-v1",
                status="completed",
                human_review_required=True,
                cloud=False,
                mock=False,
                model=profile,
                prompt_version=PROMPT_VERSION,
                segments=retained,
                grouping=grouping(job, retained),
                reused_segments=len(retained),
            )
            checkpoint(result_path, previous)
            return previous
    retained_ids = {segment["segment_id"] for segment in retained}
    assets = {asset["asset_id"]: asset for asset in job["assets"]}
    request = {
        "model_path": str(model_dir.resolve()),
        "profile": profile,
        "max_tokens": max_tokens,
        "segment_timeout_seconds": segment_timeout,
        "segments": [
            {
                "segment_id": segment["segment_id"],
                "batch": [
                    {
                        "asset_id": identifier,
                        "preview_path": str(run / assets[identifier]["preview"]),
                    }
                    for identifier in segment["asset_ids"]
                ],
            }
            for segment in job["segments"]
            if segment["segment_id"] not in retained_ids
        ],
    }
    attempt_id = uuid.uuid4().hex
    request_path = run / f"attempt-{attempt_id}.input.json"
    output_path = run / f"attempt-{attempt_id}.result.json"
    checkpoint(request_path, request)
    failure = None
    started = time.monotonic()
    with private_new(run / f"attempt-{attempt_id}.runtime.log") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "artvenn_vision.worker",
                "--request",
                str(request_path),
                "--output",
                str(output_path),
            ],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            failure = "overall_timeout"
            stop_child(child)
        except KeyboardInterrupt:
            failure = "cancelled"
            stop_child(child)
    attempt = read_json(output_path, MAX_RESULT_BYTES) if output_path.exists() else {"segments": []}
    if failure:
        attempt["error_category"] = failure
    elif child.returncode and not attempt.get("error_category"):
        attempt["error_category"] = "inference_attempt_failed"
    segments = merge_records(job, retained, attempt)
    completed = sum(segment["status"] == "completed" for segment in segments)
    result = {
        "schema_version": "artvenn-vision-result-v1",
        "binding": binding,
        "status": "completed"
        if completed == len(segments)
        else "partial"
        if completed
        else "failed",
        "human_review_required": True,
        "cloud": False,
        "mock": False,
        "model": profile,
        "prompt_version": PROMPT_VERSION,
        "segments": segments,
        "grouping": grouping(job, segments),
        "attempt": {key: value for key, value in attempt.items() if key != "segments"},
        "attempt_seconds": round(time.monotonic() - started, 3),
        "reused_segments": len(retained),
    }
    checkpoint(result_path, result)
    return result
