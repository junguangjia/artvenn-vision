"""Local, append-only human review over an unchanged prepared vision run."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .annotations import (
    SCHEMAS,
    annotation_schema,
    extension_schema,
    taxonomy,
    validate_contract,
    validate_labels,
)
from .images import validate_input
from .schema import ASSET_ID, GROUP_KEY, PROMPT_VERSION, ROLES, validate_proposal
from .storage import checkpoint, digest, fingerprint, read_json, require

REVIEW_VERSION = "artvenn-vision-review/v1"
DATASET_VERSION = "artvenn-vision-algorithm-dataset/v1"
MAX_METADATA_BYTES = 256 * 1024 * 1024
HASH = re.compile(r"^[a-f0-9]{64}$")
OBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


def _original_frame(asset: dict[str, Any]) -> dict[str, Any]:
    """Read encoded Original metadata, never transpose it or borrow preview dimensions."""
    try:
        with Image.open(asset["source_path"]) as original:
            orientation = original.getexif().get(274, 1)
            require(
                type(orientation) is int and 1 <= orientation <= 8, "original_metadata_unavailable"
            )
            frame = {
                "version": "artvenn-original-frame/v1",
                "assetId": asset["asset_id"],
                "sourceSha256": asset["source_sha256"],
                "width": original.width,
                "height": original.height,
                "exifOrientation": orientation,
                "coordinateSystem": "original_encoded_pixels_top_left",
                "orientationApplied": False,
            }
            return {"status": "verified", "frame": frame}
    except (OSError, ValueError, UnidentifiedImageError):
        return {"status": "unknown", "frame": None, "reason": "original_metadata_unavailable"}


def _text(value: Any, maximum: int, code: str, *, empty: bool = False) -> str:
    require(isinstance(value, str) and len(value) <= maximum, code)
    require(not any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value), code)
    require(empty or bool(value.strip()), code)
    return value.strip()


def _job(run: Path) -> dict[str, Any]:
    job = read_json(run / "input.json", MAX_METADATA_BYTES)
    require(
        isinstance(job, dict) and job.get("schema_version") == "artvenn-vision-input-v1",
        "invalid_input_schema",
    )
    require(
        job.get("fingerprint")
        == fingerprint({key: value for key, value in job.items() if key != "fingerprint"}),
        "input_manifest_changed",
    )
    require(
        isinstance(job.get("source_root"), str)
        and Path(job["source_root"]).is_absolute()
        and type(job.get("same_object")) is bool,
        "invalid_input_schema",
    )
    require(isinstance(job.get("assets"), list) and bool(job["assets"]), "invalid_input_assets")
    ids: set[str] = set()
    for asset in job["assets"]:
        require(
            isinstance(asset, dict)
            and isinstance(asset.get("asset_id"), str)
            and ASSET_ID.fullmatch(asset["asset_id"]) is not None
            and asset["asset_id"] not in ids,
            "invalid_input_assets",
        )
        ids.add(asset["asset_id"])
        require(
            all(
                isinstance(asset.get(key), str) and HASH.fullmatch(asset[key]) is not None
                for key in ("source_sha256", "preview_sha256")
            ),
            "invalid_input_assets",
        )
        require(
            isinstance(asset.get("source_path"), str)
            and Path(asset["source_path"]).is_absolute()
            and isinstance(asset.get("preview"), str)
            and not Path(asset["preview"]).is_absolute()
            and isinstance(asset.get("processing"), dict),
            "invalid_input_assets",
        )
    require(
        isinstance(job.get("segments"), list) and bool(job["segments"]), "invalid_input_segments"
    )
    segments: set[str] = set()
    covered: set[str] = set()
    for segment in job["segments"]:
        require(
            isinstance(segment, dict)
            and set(segment) == {"segment_id", "asset_ids"}
            and isinstance(segment["segment_id"], str)
            and GROUP_KEY.fullmatch(segment["segment_id"]) is not None
            and segment["segment_id"] not in segments,
            "invalid_input_segments",
        )
        segments.add(segment["segment_id"])
        selected = segment["asset_ids"]
        require(
            isinstance(selected, list)
            and 1 <= len(selected) <= 8
            and all(isinstance(item, str) and item in ids for item in selected)
            and len(set(selected)) == len(selected)
            and not covered.intersection(selected),
            "invalid_input_segments",
        )
        covered.update(selected)
    require(covered == ids, "invalid_input_segments")
    return job


def _proposals(run: Path, job: dict[str, Any]) -> dict[str, Any]:
    result = (
        read_json(run / "result.json", MAX_METADATA_BYTES)
        if (run / "result.json").exists()
        else None
    )
    groups: list[dict[str, Any]] = []
    roles: dict[str, str] = {}
    processed: list[str] = []
    proposals: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    if result is not None:
        require(
            isinstance(result, dict)
            and result.get("schema_version") == "artvenn-vision-result-v1"
            and isinstance(result.get("segments"), list),
            "invalid_review_result",
        )
        require(
            result.get("input_fingerprint") == job["fingerprint"], "review_result_source_unbound"
        )
        imported = result.get("imported_source")
        if imported is not None:
            expected_sources = {
                asset["asset_id"]: asset["source_sha256"] for asset in job["assets"]
            }
            require(
                isinstance(imported, dict)
                and set(imported)
                == {
                    "kind",
                    "source_proposals_sha256",
                    "asset_source_sha256",
                    "segments_sha256",
                    "synthetic",
                }
                and imported["kind"] == "hash_bound_local_proposal_import"
                and isinstance(imported["source_proposals_sha256"], str)
                and HASH.fullmatch(imported["source_proposals_sha256"]) is not None
                and imported["asset_source_sha256"] == expected_sources
                and imported["segments_sha256"] == fingerprint(result["segments"])
                and type(imported["synthetic"]) is bool,
                "review_result_source_unbound",
            )
        else:
            from .models import validate_profile

            generation = result.get("generation")
            require(
                isinstance(generation, dict)
                and set(generation) == {"max_tokens", "segment_timeout_seconds"}
                and type(generation["max_tokens"]) is int
                and 512 <= generation["max_tokens"] <= 6144
                and type(generation["segment_timeout_seconds"]) is int
                and 30 <= generation["segment_timeout_seconds"] <= 600
                and result.get("prompt_version") == PROMPT_VERSION,
                "review_result_source_unbound",
            )
            profile = validate_profile(result.get("model"))
            require(
                result.get("binding")
                == fingerprint(
                    {
                        "input": job["fingerprint"],
                        "model": profile,
                        "prompt": PROMPT_VERSION,
                        "max_tokens": generation["max_tokens"],
                        "segment_timeout": generation["segment_timeout_seconds"],
                    }
                ),
                "review_result_source_unbound",
            )
        provenance = _safe_provenance(result)
        expected = {segment["segment_id"]: segment["asset_ids"] for segment in job["segments"]}
        seen: set[str] = set()
        for segment in result["segments"]:
            require(
                isinstance(segment, dict)
                and isinstance(segment.get("segment_id"), str)
                and segment["segment_id"] in expected
                and segment["segment_id"] not in seen
                and isinstance(segment.get("status"), str)
                and segment["status"] in {"completed", "failed"},
                "invalid_review_result",
            )
            seen.add(segment["segment_id"])
            if segment["status"] != "completed":
                continue
            proposal = validate_proposal(segment.get("proposal"), expected[segment["segment_id"]])
            proposals.append({"segment_id": segment["segment_id"], "proposal": proposal})
            processed.extend(expected[segment["segment_id"]])
            for group in proposal["groups"]:
                groups.append(
                    {
                        "key": f"{segment['segment_id']}_{group['key']}",
                        "asset_ids": group["asset_ids"],
                        "fields": group["fields"],
                    }
                )
            roles.update({item["asset_id"]: item["role"] for item in proposal["roles"]})
    return {
        "groups": groups,
        "roles": roles,
        "processed_asset_ids": sorted(processed),
        "proposals": proposals,
        "result_fingerprint": fingerprint(result) if result is not None else None,
        "provenance": provenance,
    }


def _safe_provenance(result: dict[str, Any]) -> dict[str, Any]:
    """Export public model identities and hashes, never arbitrary result metadata or paths."""
    provenance = {"input_fingerprint": result["input_fingerprint"]}
    model = result.get("model")
    if model is not None:
        require(isinstance(model, dict), "review_provenance_invalid")
        if model.get("schema_version") == "artvenn-vision-model-v1":
            from .models import validate_profile

            model = validate_profile(model)
            safe_model = {
                key: model[key]
                for key in (
                    "schema_version",
                    "model_id",
                    "revision",
                    "model_type",
                    "quantization_bits",
                )
            }
            for key in ("weights", "artifacts"):
                safe_model[key] = [
                    {field: item[field] for field in ("name", "size_bytes", "sha256")}
                    for item in model[key]
                ]
        else:
            require(
                isinstance(model, dict)
                and set(model).issubset({"revision", "origin", "model_id"})
                and isinstance(model.get("revision"), str)
                and re.fullmatch(r"[a-f0-9]{40}", model["revision"]) is not None
                and model.get("origin") == "existing_local_artvenn_proposals",
                "review_provenance_invalid",
            )
            if "model_id" in model:
                require(
                    isinstance(model["model_id"], str)
                    and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", model["model_id"])
                    is not None,
                    "review_provenance_invalid",
                )
            safe_model = copy.deepcopy(model)
        provenance["model"] = safe_model
    if "prompt_version" in result:
        require(
            isinstance(result["prompt_version"], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", result["prompt_version"])
            is not None,
            "review_provenance_invalid",
        )
        provenance["prompt_version"] = result["prompt_version"]
    if "binding" in result:
        require(
            isinstance(result["binding"], str) and HASH.fullmatch(result["binding"]) is not None,
            "review_provenance_invalid",
        )
        provenance["binding"] = result["binding"]
    if "generation" in result:
        generation = result["generation"]
        require(
            isinstance(generation, dict)
            and set(generation) == {"max_tokens", "segment_timeout_seconds"}
            and type(generation["max_tokens"]) is int
            and 512 <= generation["max_tokens"] <= 6144
            and type(generation["segment_timeout_seconds"]) is int
            and 30 <= generation["segment_timeout_seconds"] <= 600,
            "review_provenance_invalid",
        )
    for key in ("generation", "imported_source"):
        if key in result:
            provenance[key] = copy.deepcopy(result[key])
    return provenance


def _initial(job: dict[str, Any], proposals: dict[str, Any]) -> dict[str, Any]:
    draft: dict[str, Any] = {"objects": [], "photos": {}}
    membership: dict[str, str] = {}
    for group in proposals["groups"]:
        title = next((field["value"] for field in group["fields"] if field["field"] == "title"), "")
        draft["objects"].append(
            {"object_id": group["key"], "title": title, "asset_ids": sorted(group["asset_ids"])}
        )
        membership.update({asset_id: group["key"] for asset_id in group["asset_ids"]})
    if job["same_object"]:
        draft["objects"] = [
            {
                "object_id": "declared_object",
                "title": "",
                "asset_ids": sorted(asset["asset_id"] for asset in job["assets"]),
            }
        ]
        membership = {asset["asset_id"]: "declared_object" for asset in job["assets"]}
    for asset in job["assets"]:
        asset_id = asset["asset_id"]
        draft["photos"][asset_id] = {
            "object_id": membership.get(asset_id),
            "role": proposals["roles"].get(asset_id, "unspecified"),
            "labels": {},
        }
    return draft


def _validate_draft(value: Any, available: set[str]) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"objects", "photos"}, "invalid_review_draft")
    require(
        isinstance(value["objects"], list)
        and isinstance(value["photos"], dict)
        and set(value["photos"]) == available,
        "review_asset_coverage_invalid",
    )
    objects: dict[str, dict[str, Any]] = {}
    result = copy.deepcopy(value)
    for obj in result["objects"]:
        require(
            isinstance(obj, dict)
            and {"object_id", "title", "asset_ids"}.issubset(obj)
            and set(obj).issubset({"object_id", "title", "asset_ids", "coverage"})
            and isinstance(obj["object_id"], str)
            and OBJECT_ID.fullmatch(obj["object_id"]) is not None
            and obj["object_id"] not in objects,
            "invalid_review_object",
        )
        obj["title"] = _text(obj["title"], 1200, "invalid_object_title", empty=True)
        require(
            isinstance(obj["asset_ids"], list)
            and all(isinstance(item, str) and item in available for item in obj["asset_ids"])
            and len(set(obj["asset_ids"])) == len(obj["asset_ids"]),
            "invalid_object_assets",
        )
        obj["asset_ids"] = sorted(obj["asset_ids"])
        if "coverage" in obj:
            obj["coverage"] = validate_labels(obj["coverage"], "object_coverage")
        objects[obj["object_id"]] = obj
    for photo in result["photos"].values():
        require(
            isinstance(photo, dict) and set(photo) == {"object_id", "role", "labels"},
            "invalid_review_photo",
        )
        require(
            photo["object_id"] is None
            or isinstance(photo["object_id"], str)
            and photo["object_id"] in objects,
            "invalid_object_assignment",
        )
        require(isinstance(photo["role"], str) and photo["role"] in ROLES, "invalid_photo_role")
        photo["labels"] = validate_labels(photo["labels"])
    for object_id, obj in objects.items():
        require(
            obj["asset_ids"]
            == sorted(
                asset_id
                for asset_id, photo in result["photos"].items()
                if photo["object_id"] == object_id
            ),
            "review_membership_mismatch",
        )
    result["objects"].sort(key=lambda obj: obj["object_id"])
    return result


class ReviewStore:
    """One prepared run, durable drafts, and separate explicit human confirmations."""

    def __init__(self, run: Path):
        self.run = run.absolute()
        require(self.run.is_dir() and not self.run.is_symlink(), "invalid_run_directory")
        self.job = _job(self.run)
        validate_input(self.run)
        self.proposals = _proposals(self.run, self.job)
        self.assets = {asset["asset_id"]: asset for asset in self.job["assets"]}
        self.frames = {asset_id: _original_frame(asset) for asset_id, asset in self.assets.items()}
        self.binding = {
            "schema_version": REVIEW_VERSION,
            "input_fingerprint": self.job["fingerprint"],
            "source_binding": fingerprint(
                [
                    {key: asset[key] for key in ("asset_id", "source_sha256", "preview_sha256")}
                    for asset in self.job["assets"]
                ]
            ),
            "ai_result_fingerprint": self.proposals["result_fingerprint"],
            "original_frames_fingerprint": fingerprint(self.frames),
        }
        self.path = self.run / "review.sqlite"
        new = not self.path.exists()
        if new:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        self._identity = self._guard_file()
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            if new:
                self._initialize()
            else:
                self._validate_binding()
        except BaseException:
            self.db.close()
            raise

    def __enter__(self) -> ReviewStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _guard_file(self) -> tuple[int, int]:
        info = self.path.lstat()
        require(
            self.path.is_file()
            and not self.path.is_symlink()
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
            and info.st_mode & 0o777 == 0o600,
            "review_database_unsafe",
        )
        identity = (info.st_dev, info.st_ino)
        require(
            not hasattr(self, "_identity") or identity == self._identity, "review_database_changed"
        )
        return identity

    def _initialize(self) -> None:
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE bindings(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL,
                                  payload_sha256 TEXT NOT NULL);
            CREATE TABLE revisions(revision INTEGER PRIMARY KEY CHECK(revision>=0),
                                   parent_revision INTEGER REFERENCES revisions(revision),
                                   payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                                   source_binding TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE confirmations(decision_id TEXT PRIMARY KEY,
                                       revision INTEGER UNIQUE NOT NULL REFERENCES revisions(revision),
                                       reviewer TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                                       source_binding TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TRIGGER bindings_immutable_update BEFORE UPDATE ON bindings
              BEGIN SELECT RAISE(ABORT,'immutable_review_binding'); END;
            CREATE TRIGGER bindings_immutable_delete BEFORE DELETE ON bindings
              BEGIN SELECT RAISE(ABORT,'immutable_review_binding'); END;
            CREATE TRIGGER revisions_immutable_update BEFORE UPDATE ON revisions
              BEGIN SELECT RAISE(ABORT,'immutable_review_revision'); END;
            CREATE TRIGGER revisions_immutable_delete BEFORE DELETE ON revisions
              BEGIN SELECT RAISE(ABORT,'immutable_review_revision'); END;
            CREATE TRIGGER confirmations_immutable_update BEFORE UPDATE ON confirmations
              BEGIN SELECT RAISE(ABORT,'immutable_review_confirmation'); END;
            CREATE TRIGGER confirmations_immutable_delete BEFORE DELETE ON confirmations
              BEGIN SELECT RAISE(ABORT,'immutable_review_confirmation'); END;
        """)
        try:
            payload = {"binding": self.binding, "ai": self.proposals}
            self.db.execute(
                "INSERT INTO bindings VALUES(1,?,?)", (_json(payload), fingerprint(payload))
            )
            draft = _validate_draft(_initial(self.job, self.proposals), set(self.assets))
            self.db.execute(
                "INSERT INTO revisions VALUES(0,NULL,?,?,?,?)",
                (_json(draft), fingerprint(draft), self.binding["source_binding"], time.time()),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _validate_binding(self) -> None:
        self._guard_file()
        require(_job(self.run)["fingerprint"] == self.job["fingerprint"], "review_input_changed")
        row = self.db.execute("SELECT * FROM bindings WHERE id=1").fetchone()
        require(row is not None, "review_database_invalid")
        payload = json.loads(row["payload"])
        require(
            fingerprint(payload) == row["payload_sha256"]
            and payload["binding"] == self.binding
            and payload["ai"] == self.proposals,
            "review_source_binding_changed",
        )
        current_ai = _proposals(self.run, self.job)
        require(
            current_ai["result_fingerprint"] == self.proposals["result_fingerprint"],
            "review_ai_proposals_changed",
        )

    def validates_current_run(self) -> None:
        """Explicit confirmation/export verifies Original and preview bytes afresh."""
        self._validate_binding()
        validate_input(self.run)

        require(
            {asset_id: _original_frame(asset) for asset_id, asset in self.assets.items()}
            == self.frames,
            "review_original_frame_changed",
        )

    def _head(self) -> tuple[int, dict[str, Any], str]:
        row = self.db.execute("SELECT * FROM revisions ORDER BY revision DESC LIMIT 1").fetchone()
        require(row is not None, "review_database_invalid")
        draft = _validate_draft(json.loads(row["payload"]), set(self.assets))
        require(
            fingerprint(draft) == row["payload_sha256"]
            and row["source_binding"] == self.binding["source_binding"],
            "review_revision_invalid",
        )
        return row["revision"], draft, row["payload_sha256"]

    def _expected(self, expected_revision: int) -> tuple[int, dict[str, Any], str]:
        require(
            type(expected_revision) is int and expected_revision >= 0, "review_revision_invalid"
        )
        head = self._head()
        require(head[0] == expected_revision, "review_revision_conflict")
        return head

    def snapshot(self) -> dict[str, Any]:
        self._guard_file()
        revision, draft, payload_hash = self._head()
        confirmation = self.db.execute(
            "SELECT * FROM confirmations WHERE revision=?", (revision,)
        ).fetchone()
        latest = self.db.execute("SELECT MAX(revision) FROM confirmations").fetchone()[0]
        if confirmation:
            require(
                confirmation["payload_sha256"] == payload_hash
                and confirmation["source_binding"] == self.binding["source_binding"],
                "review_confirmation_invalid",
            )
        return {
            **self.binding,
            "revision": revision,
            "assets": [
                {
                    key: asset[key]
                    for key in (
                        "asset_id",
                        "source_sha256",
                        "preview",
                        "preview_sha256",
                        "processing",
                    )
                }
                for asset in self.job["assets"]
            ],
            "groups": copy.deepcopy(self.proposals["groups"]),
            "processed_asset_ids": list(self.proposals["processed_asset_ids"]),
            "unprocessed_asset_ids": sorted(
                set(self.assets) - set(self.proposals["processed_asset_ids"])
            ),
            "initial_grouping_authority": "user_declaration"
            if self.job["same_object"]
            else "ai_proposal",
            "draft": draft,
            "taxonomy": taxonomy(),
            "confirmed_revision": latest,
            "human_confirmed": confirmation is not None,
            "confirmation": dict(confirmation) if confirmation else None,
        }

    def save(self, expected_revision: int, draft: dict[str, Any]) -> dict[str, Any]:
        self._validate_binding()
        normalized = _validate_draft(draft, set(self.assets))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            revision, previous, _ = self._expected(expected_revision)
            if revision == 0 or normalized != previous:
                self.db.execute(
                    "INSERT INTO revisions VALUES(?,?,?,?,?,?)",
                    (
                        revision + 1,
                        revision,
                        _json(normalized),
                        fingerprint(normalized),
                        self.binding["source_binding"],
                        time.time(),
                    ),
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.snapshot()

    def confirm(self, expected_revision: int, reviewer: str) -> dict[str, Any]:
        reviewer = _text(reviewer, 120, "reviewer_required")
        self.validates_current_run()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            revision, draft, payload_hash = self._expected(expected_revision)
            require(revision > 0, "review_must_be_saved")
            require(
                all(photo["object_id"] is not None for photo in draft["photos"].values()),
                "review_unassigned_photos",
            )
            require(
                all(obj["title"] and obj["asset_ids"] for obj in draft["objects"]),
                "review_object_name_required",
            )
            previous = self.db.execute(
                "SELECT * FROM confirmations WHERE revision=?", (revision,)
            ).fetchone()
            if previous:
                require(previous["reviewer"] == reviewer, "review_already_confirmed")
            else:
                decision_id = "decision-" + fingerprint(
                    {
                        "revision": revision,
                        "payload": payload_hash,
                        "source": self.binding,
                        "reviewer": reviewer,
                    }
                )
                self.db.execute(
                    "INSERT INTO confirmations VALUES(?,?,?,?,?,?)",
                    (
                        decision_id,
                        revision,
                        reviewer,
                        payload_hash,
                        self.binding["source_binding"],
                        time.time(),
                    ),
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.snapshot()

    def export(self, output: Path, include_unconfirmed: bool = False) -> dict[str, Any]:
        require(type(include_unconfirmed) is bool, "review_export_invalid")
        self.validates_current_run()
        self.db.execute("BEGIN")
        try:
            snapshot = self.snapshot()
            require(snapshot["revision"] > 0, "review_must_be_saved")
            require(snapshot["human_confirmed"] or include_unconfirmed, "review_not_confirmed")
            revisions: list[dict[str, Any]] = []
            for row in self.db.execute("SELECT * FROM revisions ORDER BY revision"):
                record = dict(row)
                record["payload"] = _validate_draft(json.loads(record["payload"]), set(self.assets))
                require(
                    fingerprint(record["payload"]) == record["payload_sha256"]
                    and record["source_binding"] == self.binding["source_binding"],
                    "review_revision_invalid",
                )
                require(
                    record["revision"] == len(revisions)
                    and record["parent_revision"] == (len(revisions) - 1 if revisions else None),
                    "review_revision_chain_invalid",
                )
                revisions.append(record)
            confirmations = [
                dict(row)
                for row in self.db.execute("SELECT * FROM confirmations ORDER BY revision")
            ]
            for decision in confirmations:
                require(
                    decision["revision"] > 0
                    and decision["revision"] < len(revisions)
                    and decision["payload_sha256"]
                    == revisions[decision["revision"]]["payload_sha256"]
                    and decision["source_binding"] == self.binding["source_binding"],
                    "review_confirmation_invalid",
                )
                require(
                    decision["decision_id"]
                    == "decision-"
                    + fingerprint(
                        {
                            "revision": decision["revision"],
                            "payload": decision["payload_sha256"],
                            "source": self.binding,
                            "reviewer": decision["reviewer"],
                        }
                    ),
                    "review_confirmation_invalid",
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        annotations = [
            {
                "asset_id": asset_id,
                "source_sha256": self.assets[asset_id]["source_sha256"],
                **photo,
                "revision": snapshot["revision"],
                "status": "human_confirmed" if snapshot["human_confirmed"] else "saved_unconfirmed",
                "decision_id": snapshot["confirmation"]["decision_id"]
                if snapshot["confirmation"]
                else None,
            }
            for asset_id, photo in sorted(snapshot["draft"]["photos"].items())
        ]
        dataset = {
            "schema_version": DATASET_VERSION,
            "input_fingerprint": self.binding["input_fingerprint"],
            "source_binding": self.binding["source_binding"],
            "ai_result_fingerprint": self.binding["ai_result_fingerprint"],
            "original_frames_fingerprint": self.binding["original_frames_fingerprint"],
            "revision": snapshot["revision"],
            "media_included": False,
            "source_hash_policy": "original_and_preview_bytes_reverified_at_export",
            "assets": [
                {
                    "asset_id": asset_id,
                    "source_sha256": asset["source_sha256"],
                    "preview_sha256": asset["preview_sha256"],
                    "source_dimensions": asset["processing"].get("source_dimensions"),
                    "original_frame": copy.deepcopy(self.frames[asset_id]),
                }
                for asset_id, asset in sorted(self.assets.items())
            ],
            "ai_proposals": copy.deepcopy(self.proposals["proposals"]),
            "ai_groups": copy.deepcopy(self.proposals["groups"]),
            "ai_provenance": copy.deepcopy(self.proposals["provenance"]),
            "processed_asset_ids": snapshot["processed_asset_ids"],
            "unprocessed_asset_ids": snapshot["unprocessed_asset_ids"],
            "draft": snapshot["draft"],
            "revisions": revisions,
            "confirmations": confirmations,
            "current_annotations": annotations if snapshot["human_confirmed"] else [],
            "unconfirmed_annotations": annotations if not snapshot["human_confirmed"] else [],
            "extension_interfaces": {
                "schema_version": "artvenn-algorithm-extension/v1",
                "region_editing": "reserved",
                "result_execution": "reserved",
            },
        }
        dataset_id = "dataset-" + fingerprint(dataset)
        dataset["dataset_id"] = dataset_id
        dataset_schema = read_json(SCHEMAS / "algorithm-dataset-v1.schema.json")
        validate_contract(dataset, dataset_schema)
        status = "human_confirmed" if snapshot["human_confirmed"] else "saved_unconfirmed"
        counts = {
            "assets": len(self.assets),
            "ai_groups": len(self.proposals["groups"]),
            "objects": len(snapshot["draft"]["objects"]),
            "revisions": len(revisions),
            "confirmations": len(confirmations),
            "current_annotations": len(dataset["current_annotations"]),
            "unconfirmed_annotations": len(dataset["unconfirmed_annotations"]),
        }
        output = output.absolute()
        require(not output.exists() and not output.is_symlink(), "export_output_already_exists")
        require(output.parent.is_dir() and not output.parent.is_symlink(), "export_parent_invalid")
        output.mkdir(mode=0o700)
        try:
            checkpoint(output / "dataset.json", dataset)
            checkpoint(output / "photo-annotation-v1.schema.json", annotation_schema())
            checkpoint(output / "algorithm-extension-v1.schema.json", extension_schema())
            checkpoint(output / "algorithm-dataset-v1.schema.json", dataset_schema)
            files = [
                {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
                for path in sorted(output.iterdir())
            ]
            manifest = {
                "schema_version": DATASET_VERSION,
                "dataset_id": dataset_id,
                "status": status,
                "counts": counts,
                "files": files,
                "media_included": False,
            }
            checkpoint(output / "manifest.json", manifest)
            checksums = "".join(
                f"{digest(path)}  {path.name}\n" for path in sorted(output.iterdir())
            )
            fd = os.open(output / "checksums.sha256", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(checksums)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            shutil.rmtree(output)
            raise
        return {
            "dataset_id": dataset_id,
            "status": status,
            "counts": counts,
            "path": str(output),
            "dataset_file": str(output / "dataset.json"),
            "manifest_file": str(output / "manifest.json"),
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
