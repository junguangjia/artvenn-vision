from __future__ import annotations

import copy

import pytest

from artvenn_vision.annotations import (
    apply_bulk_patch,
    apply_label_patch,
    taxonomy,
    validate_contract,
    validate_extension,
    validate_labels,
)
from artvenn_vision.storage import VisionError


def test_professional_axes_are_independent_and_unknown_is_not_absent():
    labels = {
        "object_kind": "inscription",
        "representation": "rubbing",
        "capture_method": "scan",
        "coverage": "detail",
        "surfaces": ["back"],
        "parts": ["head"],
        "content": ["stele_title", "damage"],
        "version_label": " First rubbing ",
        "notes": None,
    }
    normalized = validate_labels(labels)
    assert normalized["representation"] == "rubbing"
    assert normalized["surfaces"] == ["back"]
    assert normalized["content"] == ["damage", "stele_title"]
    assert normalized["version_label"] == "First rubbing"
    assert normalized["notes"] is None
    assert "positions" not in normalized
    assert validate_labels({"surfaces": ["unknown"]}) != validate_labels({})
    assert "frontispiece" in taxonomy()["positions"]["items"]["enum"]


def test_side_reference_and_verified_absence_require_evidence():
    with pytest.raises(VisionError, match="side_reference_required"):
        validate_labels({"surfaces": ["left"]})
    assert validate_labels({"surfaces": ["left"], "side_reference": "facing_front"})
    with pytest.raises(VisionError, match="coverage_evidence_required"):
        validate_labels({"back": "verified_absent"}, "object_coverage")
    assert validate_labels({"back": "not_captured"}, "object_coverage")
    assert validate_labels(
        {"back": "verified_absent", "coverage_evidence": "Direct inspection"}, "object_coverage"
    )


@pytest.mark.parametrize(
    "values",
    [
        {"content": ["main_text", "unknown"]},
        {"parts": ["body", "not_applicable"]},
        {"surfaces": ["front", "front"]},
        {"position_index": True},
        {"surfaces": "front"},
        {"notes": "text\x00"},
        {"invented_axis": "value"},
        {"coverage": "invented"},
    ],
)
def test_invalid_or_contradictory_labels_are_refused(values):
    with pytest.raises(VisionError):
        validate_labels(values)


def test_sparse_label_operations_preserve_omitted_and_clear_is_explicit():
    labels = {"representation": "stone", "content": ["main_text", "damage"], "notes": "Keep"}
    original = copy.deepcopy(labels)
    changed = apply_label_patch(
        labels, {"content": {"op": "remove", "value": ["damage"]}, "notes": {"op": "clear"}}
    )
    assert changed == {"representation": "stone", "content": ["main_text"]}
    assert labels == original
    changed = apply_label_patch(changed, {"content": {"op": "add", "value": ["seal"]}})
    assert changed["content"] == ["main_text", "seal"]
    changed = apply_label_patch(changed, {"representation": {"op": "set", "value": None}})
    assert "representation" in changed and changed["representation"] is None
    with pytest.raises(VisionError):
        apply_label_patch(changed, {"representation": {"op": "add", "value": ["stone"]}})


def test_group_and_single_bulk_selection_is_exact_without_erasing_ai_groups():
    draft = {
        "objects": [
            {"object_id": "one", "title": "First", "asset_ids": ["a1", "a2"]},
            {"object_id": "two", "title": "Second", "asset_ids": ["a3"]},
        ],
        "photos": {
            item: {
                "object_id": "one" if item != "a3" else "two",
                "role": "unspecified",
                "labels": {},
            }
            for item in ["a1", "a2", "a3"]
        },
    }
    original = copy.deepcopy(draft)
    result = apply_bulk_patch(
        draft,
        ["a2", "a3"],
        {
            "object_id": "one",
            "role": "detail",
            "labels": {"content": {"op": "set", "value": ["main_text"]}},
        },
    )
    assert len(result["objects"]) == 1
    assert result["objects"][0]["asset_ids"] == ["a1", "a2", "a3"]
    assert result["photos"]["a1"] == original["photos"]["a1"]
    assert result["photos"]["a3"]["labels"] == {"content": ["main_text"]}
    assert draft == original
    for selection in [[], ["a1", "a1"], ["foreign"]]:
        with pytest.raises(VisionError, match="selection_invalid"):
            apply_bulk_patch(draft, selection, {})


@pytest.fixture
def region():
    source = {
        "assetId": "a1",
        "logicalAssetId": "a1",
        "sourceSha256": "a" * 64,
        "frame": {
            "version": "artvenn-original-frame/v1",
            "assetId": "a1",
            "sourceSha256": "a" * 64,
            "width": 200,
            "height": 100,
            "exifOrientation": 6,
            "coordinateSystem": "original_encoded_pixels_top_left",
            "orientationApplied": False,
        },
    }
    return {
        "schema_version": "artvenn-algorithm-extension/v1",
        "kind": "region",
        "id": "r1",
        "source": source,
        "geometry": {"type": "rectangle", "x": 10, "y": 20, "width": 80, "height": 30},
        "content": ["main_text"],
        "reading_order": 0,
        "transcription": {"diplomatic": None, "normalized": None, "state": "uncertain"},
        "review": {"status": "candidate", "decision_id": None},
    }


def test_region_contract_binds_encoded_source_frame_and_separate_human_review(region):
    assert validate_extension(region) == region
    for path, value in [
        (("geometry", "x"), float("nan")),
        (("geometry", "width"), 400),
        (("source", "frame", "sourceSha256"), "b" * 64),
        (("review", "status"), "human_confirmed"),
    ]:
        invalid = copy.deepcopy(region)
        current = invalid
        for key in path[:-1]:
            current = current[key]
        current[path[-1]] = value
        with pytest.raises(VisionError):
            validate_extension(invalid)
    region["review"] = {"status": "human_confirmed", "decision_id": "explicit-human-decision"}
    assert validate_extension(region)["review"]["status"] == "human_confirmed"


def test_algorithm_result_cannot_promote_predicted_regions_to_human_truth(region):
    result = {
        "schema_version": "artvenn-algorithm-extension/v1",
        "kind": "algorithm_result",
        "run_id": "ocr-run",
        "base_dataset_id": "base",
        "annotation_dataset_id": "labels",
        "task": "ocr",
        "model": {"name": "Example OCR", "revision": "immutable-revision"},
        "parameters_sha256": "b" * 64,
        "inputs": [copy.deepcopy(region["source"])],
        "status": "candidate",
        "regions": [region],
        "registration": None,
    }
    assert validate_extension(result)["status"] == "candidate"
    result["regions"][0]["review"] = {"status": "human_confirmed", "decision_id": "forged"}
    with pytest.raises(VisionError, match="result_input_mismatch"):
        validate_extension(result)
    result["regions"][0]["review"] = {"status": "candidate", "decision_id": None}
    result["task"] = "registration"
    with pytest.raises(VisionError, match="task_mismatch"):
        validate_extension(result)


def test_closed_contract_resolves_references_and_all_of_without_accepting_wrong_types():
    schema = {
        "$defs": {"identifier": {"type": "string", "pattern": "^a[0-9]+$"}},
        "allOf": [
            {
                "type": "object",
                "required": ["id"],
                "additionalProperties": False,
                "properties": {"id": {"$ref": "#/$defs/identifier"}},
            }
        ],
    }
    validate_contract({"id": "a123"}, schema)
    for invalid in [{}, {"id": 123}, {"id": "foreign"}, {"id": "a123", "extra": True}]:
        with pytest.raises(VisionError, match="schema_invalid"):
            validate_contract(invalid, schema)


@pytest.mark.parametrize(
    "mutation", ["hash", "orientation", "missing_dimension", "infinite", "extra"]
)
def test_reserved_region_contract_checks_complete_original_identity_and_finite_geometry(
    region, mutation
):
    if mutation == "hash":
        region["source"]["sourceSha256"] = "invalid"
    elif mutation == "orientation":
        region["source"]["frame"]["exifOrientation"] = True
    elif mutation == "missing_dimension":
        region["source"]["frame"].pop("width")
    elif mutation == "infinite":
        region["geometry"]["height"] = float("inf")
    else:
        region["geometry"]["arbitrary"] = "value"
    with pytest.raises(VisionError):
        validate_extension(region)
