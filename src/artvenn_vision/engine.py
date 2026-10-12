"""Bounded MLX inference worker, extracted from ArtVenn's local model runner."""

from __future__ import annotations

import contextlib
import os
import resource
import signal
import time
from pathlib import Path
from typing import Any, cast

from PIL import Image

from .models import verify_model
from .schema import ASSET_ID, PROMPT_VERSION, ProposalError, build_prompt, parse_proposal
from .storage import VisionError, checkpoint, private_new, require


def offline_environment() -> None:
    for name, value in {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "HF_TOKEN": "",
        "TOKENIZERS_PARALLELISM": "false",
    }.items():
        os.environ[name] = value


@contextlib.contextmanager
def segment_deadline(seconds: int):
    def expired(_number, _frame):
        raise TimeoutError("segment_deadline_exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def validate_request(request: Any) -> None:
    require(
        isinstance(request, dict)
        and set(request)
        == {"model_path", "profile", "segments", "max_tokens", "segment_timeout_seconds"},
        "invalid_inference_request",
    )
    require(
        type(request["max_tokens"]) is int and 512 <= request["max_tokens"] <= 6144,
        "invalid_token_limit",
    )
    require(
        type(request["segment_timeout_seconds"]) is int
        and 30 <= request["segment_timeout_seconds"] <= 600,
        "invalid_segment_timeout",
    )
    require(
        isinstance(request["model_path"], str) and Path(request["model_path"]).is_absolute(),
        "invalid_model_path",
    )
    segments = request["segments"]
    require(isinstance(segments, list) and len(segments) > 0, "invalid_segments")
    seen_ids: set[str] = set()
    seen_segments: set[str] = set()
    for segment in segments:
        require(
            isinstance(segment, dict) and set(segment) == {"segment_id", "batch"}, "invalid_segment"
        )
        identifier = segment["segment_id"]
        require(
            isinstance(identifier, str)
            and ASSET_ID.fullmatch(identifier) is not None
            and identifier not in seen_segments,
            "invalid_segment_id",
        )
        seen_segments.add(identifier)
        batch = segment["batch"]
        require(isinstance(batch, list) and 0 < len(batch) <= 8, "invalid_batch_size")
        for item in batch:
            require(
                isinstance(item, dict) and set(item) == {"asset_id", "preview_path"},
                "invalid_batch_item",
            )
            asset_id = item["asset_id"]
            require(
                isinstance(asset_id, str)
                and ASSET_ID.fullmatch(asset_id) is not None
                and asset_id not in seen_ids,
                "invalid_asset_id",
            )
            seen_ids.add(asset_id)
            require(isinstance(item["preview_path"], str), "invalid_preview_path")
            preview = Path(item["preview_path"])
            require(
                preview.is_absolute() and preview.is_file() and not preview.is_symlink(),
                "missing_local_preview",
            )
            require(
                preview.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                and 0 < preview.stat().st_size <= 20 * 1024 * 1024,
                "invalid_preview_size",
            )
            with Image.open(preview) as image:
                require(image.width <= 1536 and image.height <= 1536, "preview_dimensions_exceeded")
                require(image.mode == "RGB", "preview_must_be_rgb")
                image.verify()


def run_inference(request: Any, output: Path) -> dict[str, Any]:
    offline_environment()
    validate_request(request)
    profile = request["profile"]
    verify_model(Path(request["model_path"]), profile)
    from mlx_vlm import load, stream_generate
    from mlx_vlm.prompt_utils import apply_chat_template

    start = time.monotonic()
    model, processor = load(
        request["model_path"],
        revision=profile["revision"],
        trust_remote_code=False,
        local_files_only=True,
    )
    result: dict[str, Any] = {
        "status": "running",
        "segments": [],
        "load_seconds": round(time.monotonic() - start, 3),
        "engine": "mlx-vlm",
        "cloud": False,
        "mock": False,
        "human_review_required": True,
        "prompt_version": PROMPT_VERSION,
    }
    checkpoint(output, result)
    for segment in request["segments"]:
        ids = [item["asset_id"] for item in segment["batch"]]
        images = [item["preview_path"] for item in segment["batch"]]
        segment_start = time.monotonic()
        record: dict[str, Any] = {
            "segment_id": segment["segment_id"],
            "status": "failed",
            "proposal": None,
            "error_category": None,
            "input_images": len(ids),
        }
        parts: list[str] = []
        length = 0
        try:
            with segment_deadline(request["segment_timeout_seconds"]):
                prompt = apply_chat_template(
                    processor,
                    model.config,
                    build_prompt(ids),
                    num_images=len(ids),
                    enable_thinking=False,
                )
                if not isinstance(prompt, str):
                    raise VisionError("invalid_rendered_prompt")
                last = None
                for chunk in stream_generate(
                    model,
                    cast(Any, processor),  # MLX adds a detokenizer to this processor at runtime.
                    prompt,
                    images,
                    max_tokens=request["max_tokens"],
                    temperature=0.0,
                    repetition_penalty=1.05,
                ):
                    require(isinstance(chunk.text, str), "invalid_runtime_response")
                    parts.append(chunk.text)
                    length += len(chunk.text)
                    require(length <= 65536, "invalid_output_length")
                    last = chunk
                require(last is not None, "empty_runtime_response")
                record["proposal"] = parse_proposal("".join(parts), ids)
                record["status"] = "completed"
                record["prompt_tokens"] = int(getattr(last, "prompt_tokens", 0))
                record["generation_tokens"] = int(getattr(last, "generation_tokens", 0))
        except (ProposalError, VisionError) as error:
            record["error_category"] = str(error)
        except TimeoutError:
            record["error_category"] = "segment_timeout"
        except Exception:
            record["error_category"] = "local_runtime_failure"
        with private_new(
            output.with_name(f"{output.name}.{segment['segment_id']}.raw.txt")
        ) as handle:
            handle.write("".join(parts))
        record["elapsed_seconds"] = round(time.monotonic() - segment_start, 3)
        result["segments"].append(record)
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        checkpoint(output, result)
    import mlx.core as mx

    result["peak_gpu_memory_gb"] = round(mx.get_peak_memory() / 1024**3, 3)
    result["peak_process_rss_gb"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**3, 3
    )
    completed = sum(segment["status"] == "completed" for segment in result["segments"])
    result["status"] = (
        "completed"
        if completed == len(request["segments"])
        else "partial"
        if completed
        else "failed"
    )
    checkpoint(output, result)
    return result
