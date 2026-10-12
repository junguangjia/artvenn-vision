from __future__ import annotations

import os

import pytest
from PIL import Image

from artvenn_vision.engine import offline_environment, validate_request
from artvenn_vision.storage import VisionError


def test_inference_offline_and_implicit_auth_disabled(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "explicit-synthetic-placeholder")
    offline_environment()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    assert os.environ["HF_TOKEN"] == ""


def test_invalid_batch_refused_before_model_load(tmp_path):
    request = {
        "model_path": str(tmp_path),
        "profile": {},
        "segments": [{"segment_id": "s1", "batch": []}],
        "max_tokens": 4096,
        "segment_timeout_seconds": 180,
    }
    with pytest.raises(VisionError, match="invalid_batch_size"):
        validate_request(request)


def test_boolean_token_limit_refused(tmp_path):
    request = {
        "model_path": str(tmp_path),
        "profile": {},
        "segments": [],
        "max_tokens": True,
        "segment_timeout_seconds": 180,
    }
    with pytest.raises(VisionError, match="invalid_token_limit"):
        validate_request(request)


def test_total_window_count_is_not_a_photo_limit(tmp_path):
    preview = tmp_path / "preview.jpg"
    Image.new("RGB", (2, 2)).save(preview)
    request = {
        "model_path": str(tmp_path),
        "profile": {},
        "segments": [
            {
                "segment_id": f"s{index}",
                "batch": [{"asset_id": f"a{index}", "preview_path": str(preview)}],
            }
            for index in range(513)
        ],
        "max_tokens": 4096,
        "segment_timeout_seconds": 180,
    }
    validate_request(request)


def test_per_window_safety_bound_remains(tmp_path):
    preview = tmp_path / "preview.jpg"
    Image.new("RGB", (2, 2)).save(preview)
    request = {
        "model_path": str(tmp_path),
        "profile": {},
        "segments": [
            {
                "segment_id": "s1",
                "batch": [
                    {"asset_id": f"a{index}", "preview_path": str(preview)} for index in range(9)
                ],
            }
        ],
        "max_tokens": 4096,
        "segment_timeout_seconds": 180,
    }
    with pytest.raises(VisionError, match="invalid_batch_size"):
        validate_request(request)
