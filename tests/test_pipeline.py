from __future__ import annotations

import subprocess

import pytest

from artvenn_vision.images import prepare
from artvenn_vision.models import default_profile
from artvenn_vision.pipeline import analyze, grouping, merge_records
from artvenn_vision.storage import VisionError, checkpoint, read_json


@pytest.fixture(autouse=True)
def synthetic_model_boundary(monkeypatch):
    # These tests exercise orchestration; artifact verification is tested separately.
    monkeypatch.setattr("artvenn_vision.pipeline.verify_model", lambda directory, profile: None)


def completed_segment(segment):
    ids = segment["asset_ids"]
    return {
        "segment_id": segment["segment_id"],
        "status": "completed",
        "error_category": None,
        "proposal": {
            "groups": [{"key": "g1", "asset_ids": ids, "fields": []}],
            "roles": [{"asset_id": item, "role": "overview", "evidence": [item]} for item in ids],
            "relationships": [],
            "issues": [],
        },
    }


def test_declared_object_survives_window_boundaries_and_failed_window(photos, tmp_path):
    job = prepare(photos, tmp_path / "run", same_object=True, batch_size=2)
    output = grouping(job, [completed_segment(job["segments"][0])])
    assert output["authority"] == "user_declaration"
    assert output["objects"] == [
        {"key": "declared_object", "asset_ids": ["a0001", "a0002", "a0003"]}
    ]
    assert output["human_review_required"] is True


def test_mixed_collection_cross_window_identity_unresolved(photos, tmp_path):
    job = prepare(photos, tmp_path / "run", batch_size=2)
    output = grouping(job, [completed_segment(segment) for segment in job["segments"]])
    assert output["cross_window_identity"] == "unresolved"
    assert len(output["objects"]) == 2


def test_persisted_proposal_revalidated(photos, tmp_path):
    job = prepare(photos, tmp_path / "run")
    record = completed_segment(job["segments"][0])
    record["proposal"]["groups"][0]["asset_ids"] = ["not-an-input"]
    with pytest.raises(ValueError, match="invalid_group_assets"):
        merge_records(job, [record], {})


def test_resume_runs_only_failed_windows(photos, tmp_path, monkeypatch):
    run = tmp_path / "run"
    job = prepare(photos, run, batch_size=2)
    calls = []

    class Child:
        returncode = 0

        def __init__(self, command, **kwargs):
            request = read_json(__import__("pathlib").Path(command[command.index("--request") + 1]))
            output = __import__("pathlib").Path(command[command.index("--output") + 1])
            calls.append([segment["segment_id"] for segment in request["segments"]])
            wanted = calls[-1]
            records = [
                completed_segment(segment)
                for segment in job["segments"]
                if segment["segment_id"] in wanted
            ]
            if len(calls) == 1:
                records[1].update(status="failed", proposal=None, error_category="invalid_json")
            checkpoint(output, {"status": "partial", "segments": records})

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("artvenn_vision.pipeline.subprocess.Popen", Child)
    first = analyze(run, tmp_path / "model", default_profile())
    assert first["status"] == "partial"
    assert first["input_fingerprint"] == job["fingerprint"]
    assert first["generation"] == {"max_tokens": 4096, "segment_timeout_seconds": 180}
    second = analyze(run, tmp_path / "model", default_profile())
    assert second["status"] == "completed"
    assert second["reused_segments"] == 1
    assert calls == [["s0001", "s0002"], ["s0002"]]
    cached = analyze(run, tmp_path / "model", default_profile())
    assert cached["segments"] == second["segments"]
    assert cached["reused_segments"] == 2
    assert cached["input_fingerprint"] == job["fingerprint"]
    assert cached["generation"] == second["generation"]
    assert len(calls) == 2
    with pytest.raises(VisionError, match="resume_configuration_changed"):
        analyze(run, tmp_path / "model", default_profile(), max_tokens=2048)


def test_timeout_preserves_completed_checkpoint(photos, tmp_path, monkeypatch):
    run = tmp_path / "run"
    job = prepare(photos, run, batch_size=2)
    stopped = []

    class Child:
        returncode = -15

        def __init__(self, command, **kwargs):
            from pathlib import Path

            output = Path(command[command.index("--output") + 1])
            checkpoint(
                output, {"status": "running", "segments": [completed_segment(job["segments"][0])]}
            )

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("synthetic-worker", timeout)

    monkeypatch.setattr("artvenn_vision.pipeline.subprocess.Popen", Child)
    monkeypatch.setattr("artvenn_vision.pipeline.stop_child", lambda child: stopped.append(True))
    result = analyze(run, tmp_path / "model", default_profile(), timeout=30)
    assert result["status"] == "partial"
    assert result["segments"][0]["status"] == "completed"
    assert result["segments"][1]["error_category"] == "overall_timeout"
    assert stopped == [True]
    assert not (run / ".analysis.lock").exists()


def test_existing_lock_is_preserved(photos, tmp_path):
    run = tmp_path / "run"
    prepare(photos, run)
    (run / ".analysis.lock").write_text("another writer")
    with pytest.raises(FileExistsError):
        analyze(run, tmp_path / "model", default_profile())
    assert (run / ".analysis.lock").read_text() == "another writer"


def test_completed_resume_reconstructs_authority(photos, tmp_path, monkeypatch):
    run = tmp_path / "run"
    job = prepare(photos, run)

    class Child:
        returncode = 0

        def __init__(self, command, **kwargs):
            from pathlib import Path

            output = Path(command[command.index("--output") + 1])
            checkpoint(output, {"segments": [completed_segment(job["segments"][0])]})

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("artvenn_vision.pipeline.subprocess.Popen", Child)
    result = analyze(run, tmp_path / "model", default_profile())
    result["grouping"]["authority"] = "user_declaration"
    result["human_review_required"] = False
    result["approved"] = True
    checkpoint(run / "result.json", result)
    restored = analyze(run, tmp_path / "model", default_profile())
    assert restored["grouping"]["authority"] == "ai_proposal"
    assert restored["human_review_required"] is True
    assert "approved" not in restored


def test_large_completed_run_can_resume(photos, tmp_path, monkeypatch):
    from artvenn_vision.schema import PROMPT_VERSION
    from artvenn_vision.storage import fingerprint

    run = tmp_path / "run"
    job = prepare(photos, run)
    original = job["assets"][0]
    job["assets"] = [dict(original, asset_id=f"a{index:04d}") for index in range(512)]
    job["segments"] = [
        {"segment_id": f"s{index:04d}", "asset_ids": [asset["asset_id"]]}
        for index, asset in enumerate(job["assets"])
    ]
    job["fingerprint"] = fingerprint(
        {key: value for key, value in job.items() if key != "fingerprint"}
    )
    checkpoint(run / "input.json", job)
    profile = read_json(default_profile())
    binding = fingerprint(
        {
            "input": job["fingerprint"],
            "model": profile,
            "prompt": PROMPT_VERSION,
            "max_tokens": 4096,
            "segment_timeout": 180,
        }
    )
    records = [completed_segment(segment) for segment in job["segments"]]
    for record in records:
        group = record["proposal"]["groups"][0]
        group["fields"] = [
            {"field": name, "value": "x" * 1200, "evidence": group["asset_ids"]}
            for name in ["title", "persons", "period_original", "object_form"]
        ]
        record["proposal"]["issues"] = [
            {"kind": "synthetic_long_text", "asset_ids": group["asset_ids"], "message": "x" * 1800}
        ] * 4
    checkpoint(run / "result.json", {"binding": binding, "segments": records})
    assert (run / "result.json").stat().st_size > 4 * 1024 * 1024
    monkeypatch.setattr(
        "artvenn_vision.pipeline.subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("Completed run must not infer again"),
    )
    result = analyze(run, tmp_path / "model", default_profile())
    assert result["status"] == "completed"
    assert len(result["segments"]) == 512
    assert result["input_fingerprint"] == job["fingerprint"]
    assert result["generation"] == {"max_tokens": 4096, "segment_timeout_seconds": 180}
