from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from artvenn_vision.annotations import apply_bulk_patch
from artvenn_vision.images import prepare
from artvenn_vision.models import default_profile
from artvenn_vision.review_store import ReviewStore
from artvenn_vision.schema import PROMPT_VERSION
from artvenn_vision.storage import VisionError, checkpoint, digest, fingerprint


def completed(segment):
    ids = segment["asset_ids"]
    return {
        "segment_id": segment["segment_id"],
        "status": "completed",
        "proposal": {
            "groups": [
                {
                    "key": "g1",
                    "asset_ids": ids,
                    "fields": [
                        {"field": "title", "value": "AI title suggestion", "evidence": [ids[0]]},
                    ],
                }
            ],
            "roles": [{"asset_id": item, "role": "overview", "evidence": [item]} for item in ids],
            "relationships": [],
            "issues": [],
        },
    }


def synthetic_import(job, segments):
    return {
        "schema_version": "artvenn-vision-result-v1",
        "status": "partial",
        "input_fingerprint": job["fingerprint"],
        "segments": segments,
        "prompt_version": "synthetic-test-proposals-v1",
        "model": {"revision": "a" * 40, "origin": "existing_local_artvenn_proposals"},
        "imported_source": {
            "kind": "hash_bound_local_proposal_import",
            "source_proposals_sha256": fingerprint(segments),
            "asset_source_sha256": {
                asset["asset_id"]: asset["source_sha256"] for asset in job["assets"]
            },
            "segments_sha256": fingerprint(segments),
            "synthetic": True,
        },
    }


@pytest.fixture
def run(photos, tmp_path):
    target = tmp_path / "run"
    job = prepare(photos, target, batch_size=2)
    checkpoint(
        target / "result.json",
        synthetic_import(
            job,
            [
                completed(job["segments"][0]),
                {
                    "segment_id": job["segments"][1]["segment_id"],
                    "status": "failed",
                    "proposal": None,
                },
            ],
        ),
    )
    return target


def unified(snapshot, title="One inscription"):
    draft = copy.deepcopy(snapshot["draft"])
    draft["objects"].append({"object_id": "human-object", "title": title, "asset_ids": []})
    return apply_bulk_patch(draft, list(draft["photos"]), {"object_id": "human-object"})


def test_partial_ai_result_shows_every_asset_without_inventing_missing_proposals(run):
    input_before, ai_before = digest(run / "input.json"), digest(run / "result.json")
    with ReviewStore(run) as store:
        snapshot = store.snapshot()
        assert snapshot["revision"] == 0 and snapshot["confirmed_revision"] is None
        assert len(snapshot["assets"]) == len(snapshot["draft"]["photos"]) == 3
        assert len(snapshot["groups"]) == 1
        assert snapshot["processed_asset_ids"] == ["a0001", "a0002"]
        assert snapshot["unprocessed_asset_ids"] == ["a0003"]
        assert snapshot["draft"]["photos"]["a0003"]["object_id"] is None
        assert snapshot["draft"]["photos"]["a0003"]["labels"] == {}
        assert not snapshot["human_confirmed"]
        assert all("source_path" not in asset for asset in snapshot["assets"])
    assert (run / "review.sqlite").stat().st_mode & 0o777 == 0o600
    assert digest(run / "input.json") == input_before
    assert digest(run / "result.json") == ai_before


def test_save_reopen_confirm_edit_preserves_ai_and_immutable_history(run):
    with ReviewStore(run) as store:
        initial = store.snapshot()
        draft = unified(initial)
        draft = apply_bulk_patch(
            draft,
            ["a0001", "a0003"],
            {
                "role": "detail",
                "labels": {
                    "representation": {"op": "set", "value": "stone"},
                    "surfaces": {"op": "set", "value": ["front"]},
                    "content": {"op": "set", "value": ["main_text", "damage"]},
                },
            },
        )
        saved = store.save(0, draft)
        assert saved["revision"] == 1 and not saved["human_confirmed"]
        assert saved["groups"] == initial["groups"]
    with ReviewStore(run) as store:
        snapshot = store.snapshot()
        assert snapshot["draft"] == saved["draft"]
        confirmed = store.confirm(1, "Local reviewer")
        assert confirmed["human_confirmed"] and confirmed["confirmed_revision"] == 1
        assert store.confirm(1, "Local reviewer")["confirmation"] == confirmed["confirmation"]
        with pytest.raises(VisionError, match="already_confirmed"):
            store.confirm(1, "Different reviewer")
        changed = apply_bulk_patch(
            snapshot["draft"],
            ["a0001"],
            {
                "labels": {
                    "content": {"op": "remove", "value": ["damage"]},
                    "representation": {"op": "clear"},
                }
            },
        )
        newer = store.save(1, changed)
        assert newer["revision"] == 2 and newer["confirmed_revision"] == 1
        assert not newer["human_confirmed"]
        assert newer["draft"]["photos"]["a0001"]["labels"] == {
            "content": ["main_text"],
            "surfaces": ["front"],
        }
        assert newer["draft"]["photos"]["a0003"] == saved["draft"]["photos"]["a0003"]
        for table in ["bindings", "revisions", "confirmations"]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable_review"):
                store.db.execute(f"DELETE FROM {table}")
        assert store.db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 3
        assert store.db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 1


def test_expected_revision_and_exact_membership_guards(run):
    with ReviewStore(run) as store, ReviewStore(run) as other:
        draft = unified(store.snapshot())
        store.save(0, draft)
        with pytest.raises(VisionError, match="revision_conflict"):
            other.save(0, draft)
        with pytest.raises(VisionError, match="revision_conflict"):
            other.confirm(0, "Reviewer")
        missing, extra = copy.deepcopy(draft), copy.deepcopy(draft)
        missing["photos"].pop("a0001")
        extra["photos"]["foreign"] = copy.deepcopy(extra["photos"]["a0001"])
        for invalid in [missing, extra]:
            with pytest.raises(VisionError, match="asset_coverage_invalid"):
                store.save(1, invalid)
        invalid = copy.deepcopy(draft)
        invalid["objects"][0]["asset_ids"].remove("a0001")
        with pytest.raises(VisionError, match="membership_mismatch"):
            store.save(1, invalid)
        assert store.snapshot()["revision"] == 1


def test_explicit_human_confirmation_cannot_be_implicit_or_unnamed(run):
    with ReviewStore(run) as store:
        with pytest.raises(VisionError, match="must_be_saved"):
            store.confirm(0, "Reviewer")
        saved = store.save(0, store.snapshot()["draft"])
        with pytest.raises(VisionError, match="unassigned_photos"):
            store.confirm(saved["revision"], "Reviewer")
        saved = store.save(1, unified(store.snapshot(), title=""))
        with pytest.raises(VisionError, match="reviewer_required"):
            store.confirm(saved["revision"], "  ")
        with pytest.raises(VisionError, match="object_name_required"):
            store.confirm(saved["revision"], "Reviewer")
        assert store.snapshot()["confirmed_revision"] is None


def test_export_is_metadata_only_deterministic_and_distinguishes_history_from_current(
    run, tmp_path
):
    with ReviewStore(run) as store:
        store.save(0, unified(store.snapshot()))
        with pytest.raises(VisionError, match="not_confirmed"):
            store.export(tmp_path / "refused")
        pending = store.export(tmp_path / "pending", include_unconfirmed=True)
        dataset = json.loads(Path(pending["dataset_file"]).read_text())
        assert pending["status"] == "saved_unconfirmed"
        assert dataset["current_annotations"] == []
        assert len(dataset["unconfirmed_annotations"]) == 3
        store.confirm(1, "Reviewer")
        first = store.export(tmp_path / "first")
        second = store.export(tmp_path / "second")
        assert first["dataset_id"] == second["dataset_id"]
        assert Path(first["dataset_file"]).read_bytes() == Path(second["dataset_file"]).read_bytes()
        dataset = json.loads(Path(first["dataset_file"]).read_text())
        assert len(dataset["current_annotations"]) == 3
        assert dataset["unconfirmed_annotations"] == []
        assert dataset["confirmations"][0]["reviewer"] == "Reviewer"
        assert dataset["ai_provenance"]["imported_source"]["synthetic"] is True
        assert dataset["ai_provenance"]["model"]["revision"] == "a" * 40
        assert dataset["ai_provenance"]["prompt_version"] == "synthetic-test-proposals-v1"
        assert dataset["ai_provenance"]["input_fingerprint"] == store.job["fingerprint"]
        serialized = json.dumps(dataset)
        assert str(run) not in serialized
        assert "source_path" not in serialized and 'preview"' not in serialized
        assert {path.name for path in Path(first["path"]).iterdir()} == {
            "dataset.json",
            "manifest.json",
            "checksums.sha256",
            "photo-annotation-v1.schema.json",
            "algorithm-extension-v1.schema.json",
            "algorithm-dataset-v1.schema.json",
        }
        with pytest.raises(VisionError, match="output_already_exists"):
            store.export(tmp_path / "first")
        draft = store.snapshot()["draft"]
        draft["objects"][0]["title"] = "Revised name"
        store.save(1, draft)
        pending = store.export(tmp_path / "new-pending", include_unconfirmed=True)
        dataset = json.loads(Path(pending["dataset_file"]).read_text())
        assert dataset["current_annotations"] == []
        assert len(dataset["confirmations"]) == 1
        assert len(dataset["revisions"]) == 3


def test_manifest_proposal_and_source_byte_changes_cannot_be_silently_reused(run, tmp_path):
    with ReviewStore(run) as store:
        draft = unified(store.snapshot())
        store.save(0, draft)
        source = Path(store.job["assets"][0]["source_path"])
        original = source.read_bytes()
        source.write_bytes(b"changed source")
        with pytest.raises(VisionError, match="source_hash_changed"):
            store.confirm(1, "Reviewer")
        with pytest.raises(VisionError, match="source_hash_changed"):
            store.export(tmp_path / "source-refused", include_unconfirmed=True)
        source.write_bytes(original)
        result = json.loads((run / "result.json").read_text())
        result["segments"][0]["proposal"]["groups"][0]["fields"][0]["value"] = "Changed proposal"
        result["imported_source"]["segments_sha256"] = fingerprint(result["segments"])
        checkpoint(run / "result.json", result)
        with pytest.raises(VisionError, match="ai_proposals_changed"):
            store.save(1, draft)
    with pytest.raises(VisionError, match="source_binding_changed"):
        ReviewStore(run)


def test_declared_object_is_user_intent_and_not_invented_ai_analysis(photos, tmp_path):
    target = tmp_path / "declared"
    prepare(photos, target, same_object=True)
    with ReviewStore(target) as store:
        snapshot = store.snapshot()
        assert snapshot["groups"] == [] and snapshot["processed_asset_ids"] == []
        assert len(snapshot["unprocessed_asset_ids"]) == 3
        assert snapshot["initial_grouping_authority"] == "user_declaration"
        assert len(snapshot["draft"]["objects"]) == 1
        assert not snapshot["human_confirmed"]


def test_101_photos_preserve_all_bytes_groups_and_records_through_bulk_confirm_export(tmp_path):
    folder = tmp_path / "originals"
    folder.mkdir()
    for index in range(101):
        Image.new("RGB", (20, 16), (index, 40, 100)).save(folder / f"{index:03}.jpg")
    target = tmp_path / "run101"
    job = prepare(folder, target)
    checkpoint(
        target / "result.json",
        synthetic_import(job, [completed(segment) for segment in job["segments"][:-1]]),
    )
    hashes = {path.name: digest(path) for path in folder.iterdir()}
    input_hash, ai_hash = digest(target / "input.json"), digest(target / "result.json")
    with ReviewStore(target) as store:
        before = store.snapshot()
        assert len(before["assets"]) == 101 and len(before["groups"]) == 12
        assert len(before["unprocessed_asset_ids"]) == 5
        draft = apply_bulk_patch(
            unified(before),
            list(before["draft"]["photos"]),
            {
                "labels": {
                    "representation": {"op": "set", "value": "stone"},
                    "surfaces": {"op": "set", "value": ["front"]},
                }
            },
        )
        store.save(0, draft)
        store.confirm(1, "Synthetic fixture reviewer")
        summary = store.export(tmp_path / "dataset101")
        assert summary["counts"]["assets"] == summary["counts"]["current_annotations"] == 101
        assert store.snapshot()["groups"] == before["groups"]
        assert len(json.loads(Path(summary["dataset_file"]).read_text())["draft"]["photos"]) == 101
    assert {path.name: digest(path) for path in folder.iterdir()} == hashes
    assert digest(target / "input.json") == input_hash and digest(target / "result.json") == ai_hash
    assert job["fingerprint"] == fingerprint(
        {key: value for key, value in job.items() if key != "fingerprint"}
    )


def test_nonprivate_or_symlink_database_is_refused_without_changing_target(run, tmp_path):
    path = run / "review.sqlite"
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"retain me")
    path.symlink_to(foreign)
    with pytest.raises(VisionError, match="database_unsafe"):
        ReviewStore(run)
    assert foreign.read_bytes() == b"retain me"
    path.unlink()
    with ReviewStore(run):
        pass
    path.chmod(0o644)
    with pytest.raises(VisionError, match="database_unsafe"):
        ReviewStore(run)


@pytest.mark.parametrize(
    "mutation", ["legacy", "input", "asset_hash", "segment_hash", "extra_source"]
)
def test_imported_proposals_require_complete_exact_original_source_binding(run, mutation):
    result = json.loads((run / "result.json").read_text())
    if mutation == "legacy":
        result.pop("input_fingerprint")
    elif mutation == "input":
        result["input_fingerprint"] = "b" * 64
    elif mutation == "asset_hash":
        result["imported_source"]["asset_source_sha256"]["a0001"] = "b" * 64
    elif mutation == "segment_hash":
        result["imported_source"]["segments_sha256"] = "b" * 64
    else:
        result["imported_source"]["asset_source_sha256"]["foreign"] = "b" * 64
    checkpoint(run / "result.json", result)
    with pytest.raises(VisionError, match="result_source_unbound"):
        ReviewStore(run)
    assert not (run / "review.sqlite").exists()


def test_native_model_provenance_is_binding_verified_and_export_projection_is_path_free(
    run, tmp_path
):
    result = json.loads((run / "result.json").read_text())
    result.pop("imported_source")
    profile = json.loads(default_profile().read_text())
    profile["ignored_local_metadata"] = "/private/local/model/directory"
    result.update(
        {
            "model": profile,
            "prompt_version": PROMPT_VERSION,
            "generation": {"max_tokens": 512, "segment_timeout_seconds": 30},
        }
    )
    result["binding"] = fingerprint(
        {
            "input": result["input_fingerprint"],
            "model": profile,
            "prompt": PROMPT_VERSION,
            "max_tokens": 512,
            "segment_timeout": 30,
        }
    )
    checkpoint(run / "result.json", result)
    with ReviewStore(run) as store:
        store.save(0, unified(store.snapshot()))
        store.confirm(1, "Reviewer")
        summary = store.export(tmp_path / "native-export")
        dataset = json.loads(Path(summary["dataset_file"]).read_text())
        provenance = dataset["ai_provenance"]
        assert provenance["generation"] == result["generation"]
        assert provenance["binding"] == result["binding"]
        assert provenance["model"]["weights"] == profile["weights"]
        assert "ignored_local_metadata" not in provenance["model"]
        assert "/private/local/model" not in json.dumps(dataset)
    result["generation"]["max_tokens"] = 1024
    checkpoint(run / "result.json", result)
    with pytest.raises(VisionError, match="result_source_unbound"):
        ReviewStore(run)


def test_original_coordinate_frame_retains_encoded_dimensions_and_exif_orientation(tmp_path):
    folder = tmp_path / "oriented-original"
    folder.mkdir()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (30, 10)).save(folder / "oriented.jpg", exif=exif)
    target = tmp_path / "oriented-run"
    prepare(folder, target, same_object=True)
    with ReviewStore(target) as store:
        draft = store.snapshot()["draft"]
        draft["objects"][0]["title"] = "Oriented inscription"
        store.save(0, draft)
        store.confirm(1, "Reviewer")
        summary = store.export(tmp_path / "oriented-export")
        dataset = json.loads(Path(summary["dataset_file"]).read_text())
        exported = dataset["assets"][0]
        assert exported["original_frame"]["status"] == "verified"
        frame = exported["original_frame"]["frame"]
        assert (frame["width"], frame["height"], frame["exifOrientation"]) == (30, 10, 6)
        assert frame["sourceSha256"] == exported["source_sha256"]
        assert frame["orientationApplied"] is False
        assert store.job["assets"][0]["processing"]["preview_dimensions"] == [10, 30]


def test_unreadable_original_frame_is_unknown_instead_of_using_preview_dimensions(monkeypatch):
    from artvenn_vision.review_store import _original_frame

    def unsupported(_path):
        raise UnidentifiedImageError("unsupported_original_metadata")

    from PIL import UnidentifiedImageError

    monkeypatch.setattr("artvenn_vision.review_store.Image.open", unsupported)
    frame = _original_frame(
        {
            "asset_id": "a0001",
            "source_sha256": "a" * 64,
            "source_path": "/unused/original.raw",
            "processing": {"source_dimensions": [1000, 2000]},
        }
    )
    assert frame == {"status": "unknown", "frame": None, "reason": "original_metadata_unavailable"}
