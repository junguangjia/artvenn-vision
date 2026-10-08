from __future__ import annotations

import pytest

from artvenn_vision.models import default_profile, register_model, validate_profile, verify_model
from artvenn_vision.storage import VisionError, checkpoint, read_json


def test_baseline_profile_is_exact_revision():
    profile = validate_profile(read_json(default_profile()))
    assert profile["revision"] == "2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b"
    profile["revision"] = "main"
    with pytest.raises(VisionError, match="model_revision_must_be_exact_commit"):
        validate_profile(profile)


def test_local_registration_and_changed_weights(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    checkpoint(model / "config.json", {"model_type": "qwen3_vl", "quantization": {"bits": 4}})
    for name in ["tokenizer.json", "tokenizer_config.json", "preprocessor_config.json"]:
        checkpoint(model / name, {})
    # Explicit synthetic bytes: no model execution or recognition claim.
    (model / "model.safetensors").write_bytes(b"synthetic-test-weights")
    profile = register_model(model, "synthetic/model", "a" * 40, tmp_path / "profile.json")
    verify_model(model, profile)
    (model / "model.safetensors").write_bytes(b"changed-test-weights!!")
    with pytest.raises(VisionError, match="model_weight_(size|hash)_mismatch"):
        verify_model(model, profile)


def test_weight_path_traversal_refused():
    profile = read_json(default_profile())
    profile["weights"][0]["name"] = "../outside.safetensors"
    with pytest.raises(VisionError, match="invalid_weight_name"):
        validate_profile(profile)


def synthetic_model(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    checkpoint(model / "config.json", {"model_type": "qwen3_vl", "quantization": {"bits": 4}})
    for name in ["tokenizer.json", "tokenizer_config.json", "preprocessor_config.json"]:
        checkpoint(model / name, {})
    (model / "model.safetensors").write_bytes(b"explicit-synthetic-weights")
    profile = register_model(model, "synthetic/model", "a" * 40, tmp_path / "profile.json")
    return model, profile


def test_tokenizer_metadata_is_bound(tmp_path):
    model, profile = synthetic_model(tmp_path)
    checkpoint(model / "tokenizer_config.json", {"chat_template": "Changed synthetic prompt"})
    with pytest.raises(VisionError, match="model_artifact_hash_mismatch"):
        verify_model(model, profile)


def test_custom_model_code_refused_even_with_registered_weights(tmp_path):
    model, profile = synthetic_model(tmp_path)
    config = read_json(model / "config.json")
    config["model_file"] = "explicit-synthetic-model.py"
    checkpoint(model / "config.json", config)
    with pytest.raises(VisionError, match="custom_model_code_refused"):
        verify_model(model, profile)


def test_added_chat_template_refused(tmp_path):
    model, profile = synthetic_model(tmp_path)
    (model / "chat_template.jinja").write_text("Synthetic added template")
    with pytest.raises(VisionError, match="model_artifact_hash_mismatch"):
        verify_model(model, profile)
