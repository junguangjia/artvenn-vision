"""Versioned professional labels and reserved algorithm interfaces, without inference."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

from .schema import ROLES
from .storage import VisionError, fingerprint, require

ANNOTATION_VERSION = "artvenn-photo-annotation/v1"
EXTENSION_VERSION = "artvenn-algorithm-extension/v1"
SCHEMAS = Path(__file__).with_name("schemas")


def annotation_schema() -> dict[str, Any]:
    return json.loads((SCHEMAS / "photo-annotation-v1.schema.json").read_text())


def extension_schema() -> dict[str, Any]:
    return json.loads((SCHEMAS / "algorithm-extension-v1.schema.json").read_text())


def taxonomy() -> dict[str, Any]:
    return annotation_schema()["oneOf"][0]["properties"]["values"]["properties"]


def _matches(value: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> bool:
    """Validate the closed subset used by the bundled, dependency-free contracts."""
    root = schema if root is None else root
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return False
        target = root
        try:
            for key in reference[2:].split("/"):
                target = target[key.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            return False
        if not isinstance(target, dict) or not _matches(value, target, root):
            return False
    if "allOf" in schema and not all(_matches(value, part, root) for part in schema["allOf"]):
        return False
    if "oneOf" in schema and sum(_matches(value, part, root) for part in schema["oneOf"]) != 1:
        return False
    if "anyOf" in schema and not any(_matches(value, part, root) for part in schema["anyOf"]):
        return False
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and not any(
        type(value) is type(item) and value == item for item in schema["enum"]
    ):
        return False
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        actual = (
            "null"
            if value is None
            else "boolean"
            if type(value) is bool
            else "integer"
            if type(value) is int
            else "number"
            if type(value) is float
            else "string"
            if isinstance(value, str)
            else "object"
            if isinstance(value, dict)
            else "array"
            if isinstance(value, list)
            else "invalid"
        )
        if actual not in types and not (actual == "integer" and "number" in types):
            return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(value):
            return False
        if schema.get("additionalProperties") is False and not set(value).issubset(properties):
            return False
        if any(
            not _matches(item, properties[key], root)
            for key, item in value.items()
            if key in properties
        ):
            return False
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict) and any(
            not _matches(item, additional, root)
            for key, item in value.items()
            if key not in properties
        ):
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            return False
        if schema.get("uniqueItems") and len({fingerprint(item) for item in value}) != len(value):
            return False
        if "items" in schema and any(not _matches(item, schema["items"], root) for item in value):
            return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", math.inf
        ):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            return False
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    return True


def validate_labels(values: Any, kind: str = "photo") -> dict[str, Any]:
    """Omission, an explicit unknown value, null and an empty set remain distinct."""
    payload = {"schema_version": ANNOTATION_VERSION, "kind": kind, "values": values}
    require(_matches(payload, annotation_schema()), "annotation_value_invalid")
    for value in values.values():
        if isinstance(value, list):
            require(
                len(value) <= 1 or not ({"unknown", "not_applicable"} & set(value)),
                "annotation_uncertainty_conflict",
            )
        if isinstance(value, str):
            require(
                not any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value),
                "annotation_value_invalid",
            )
    if kind == "photo" and ({"left", "right"} & set(values.get("surfaces", []))):
        require(
            values.get("side_reference") == "facing_front", "annotation_side_reference_required"
        )
    if kind == "object_coverage" and "verified_absent" in values.values():
        require(
            bool((values.get("coverage_evidence") or "").strip()),
            "annotation_coverage_evidence_required",
        )
    return {
        key: sorted(value)
        if isinstance(value, list)
        else value.strip()
        if isinstance(value, str)
        else value
        for key, value in values.items()
    }


def apply_label_patch(values: dict[str, Any], operations: Any) -> dict[str, Any]:
    """A sparse patch never clears omitted labels; clear is an explicit operation."""
    require(isinstance(operations, dict), "annotation_patch_invalid")
    properties = taxonomy()
    result = copy.deepcopy(values)
    for field, operation in operations.items():
        require(field in properties and isinstance(operation, dict), "annotation_patch_invalid")
        op = operation.get("op")
        require(
            isinstance(op, str) and op in {"set", "add", "remove", "clear"},
            "annotation_patch_invalid",
        )
        require(
            set(operation) == ({"op"} if op == "clear" else {"op", "value"}),
            "annotation_patch_invalid",
        )
        if op == "clear":
            result.pop(field, None)
        elif op == "set":
            result[field] = copy.deepcopy(operation["value"])
        else:
            require(properties[field].get("type") == "array", "annotation_patch_invalid")
            supplied = operation["value"]
            require(_matches(supplied, properties[field]), "annotation_patch_invalid")
            existing = result.get(field, [])
            require(isinstance(existing, list), "annotation_patch_invalid")
            result[field] = (
                sorted(set(existing) | set(supplied))
                if op == "add"
                else [item for item in existing if item not in supplied]
            )
    return validate_labels(result)


def apply_bulk_patch(draft: dict[str, Any], asset_ids: Any, patch: Any) -> dict[str, Any]:
    """Edit precisely the chosen photos while retaining AI proposal membership separately."""
    require(
        isinstance(asset_ids, list)
        and bool(asset_ids)
        and all(isinstance(item, str) and item in draft["photos"] for item in asset_ids)
        and len(set(asset_ids)) == len(asset_ids),
        "annotation_selection_invalid",
    )
    require(
        isinstance(patch, dict) and set(patch).issubset({"labels", "role", "object_id"}),
        "annotation_patch_invalid",
    )
    if "role" in patch:
        require(isinstance(patch["role"], str) and patch["role"] in ROLES, "invalid_photo_role")
    if "object_id" in patch:
        require(
            patch["object_id"] is None
            or isinstance(patch["object_id"], str)
            and patch["object_id"] in {item["object_id"] for item in draft["objects"]},
            "invalid_object_assignment",
        )
    result = copy.deepcopy(draft)
    for asset_id in asset_ids:
        photo = result["photos"][asset_id]
        if "labels" in patch:
            photo["labels"] = apply_label_patch(photo["labels"], patch["labels"])
        for key in ("role", "object_id"):
            if key in patch:
                photo[key] = patch[key]
    for obj in result["objects"]:
        obj["asset_ids"] = sorted(
            asset_id
            for asset_id, photo in result["photos"].items()
            if photo["object_id"] == obj["object_id"]
        )
    result["objects"] = [obj for obj in result["objects"] if obj["asset_ids"]]
    return result


def validate_extension(value: Any) -> dict[str, Any]:
    """Reserved validation only: candidates do not become human decisions or execute code."""
    require(_matches(value, extension_schema()), "algorithm_extension_invalid")
    regions = [value] if value["kind"] == "region" else value["regions"]
    sources = [value["source"]] if value["kind"] == "region" else value["inputs"]
    require(
        len({source["assetId"] for source in sources}) == len(sources), "algorithm_duplicate_input"
    )
    for source in [*sources, *[region["source"] for region in regions]]:
        require(
            source["assetId"] == source["frame"]["assetId"]
            and source["sourceSha256"] == source["frame"]["sourceSha256"],
            "algorithm_frame_identity_mismatch",
        )
    for region in regions:
        review = region["review"]
        require(
            review["status"] != "human_confirmed" or bool(review["decision_id"]),
            "algorithm_region_review_required",
        )
        require(
            review["status"] != "candidate" or review["decision_id"] is None,
            "algorithm_region_review_invalid",
        )
        if value["kind"] == "algorithm_result":
            require(
                review["status"] == "candidate" and region["source"] in sources,
                "algorithm_result_input_mismatch",
            )
        frame, geometry = region["source"]["frame"], region["geometry"]
        points = (
            [
                (geometry["x"], geometry["y"]),
                (geometry["x"] + geometry["width"], geometry["y"] + geometry["height"]),
            ]
            if geometry["type"] == "rectangle"
            else geometry["points"]
        )
        require(
            all(0 <= x <= frame["width"] and 0 <= y <= frame["height"] for x, y in points),
            "algorithm_region_out_of_bounds",
        )
    if value["kind"] == "algorithm_result":
        registration = value["registration"]
        require(
            (value["task"] == "registration") == (registration is not None),
            "algorithm_result_task_mismatch",
        )
        if registration:
            inputs = {source["assetId"]: source for source in sources}
            source, target = (
                inputs.get(registration[key]) for key in ("source_asset_id", "target_asset_id")
            )
            require(
                source is not None and target is not None and source != target,
                "algorithm_registration_invalid",
            )
            assert source is not None and target is not None
            for correspondence in registration["correspondences"]:
                for key, reference in (("source", source), ("target", target)):
                    x, y = correspondence[key]
                    require(
                        0 <= x <= reference["frame"]["width"]
                        and 0 <= y <= reference["frame"]["height"],
                        "algorithm_region_out_of_bounds",
                    )
    return copy.deepcopy(value)


def validate_contract(value: Any, schema: dict[str, Any]) -> None:
    """The exporter uses the same closed contracts without an optional dependency."""
    if not _matches(value, schema):
        raise VisionError("algorithm_export_schema_invalid")
