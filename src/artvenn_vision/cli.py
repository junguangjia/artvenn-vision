"""English command-line interface for standalone local photo recognition."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from . import __version__
from .images import prepare
from .models import default_profile, download_model, register_model
from .pipeline import analyze
from .schema import ProposalError
from .storage import VisionError, require


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Create private previews from a selected folder")
    prep.add_argument("folder", type=Path)
    prep.add_argument("--output", type=Path, required=True, help="New run directory")
    prep.add_argument("--recursive", action="store_true", help="Include selected subfolders")
    prep.add_argument(
        "--same-object", action="store_true", help="Declare all photos depict one object"
    )
    prep.add_argument("--batch-size", type=int, default=8, help="Images per inference window (1-8)")
    inference = commands.add_parser(
        "analyze", help="Run offline inference; resume valid completed windows"
    )
    inference.add_argument("--run", type=Path, required=True)
    inference.add_argument("--model-dir", type=Path, required=True)
    inference.add_argument("--profile", type=Path, default=default_profile())
    inference.add_argument(
        "--timeout", type=int, default=900, help="Overall child timeout in seconds"
    )
    inference.add_argument("--segment-timeout", type=int, default=180)
    inference.add_argument("--max-tokens", type=int, default=4096)
    download = commands.add_parser(
        "download-model", help="Explicitly download a pinned public model"
    )
    download.add_argument("--model-dir", type=Path, required=True)
    download.add_argument("--profile", type=Path, default=default_profile())
    register = commands.add_parser(
        "register-model", help="Record hashes for an existing Qwen3-VL 4-bit model"
    )
    register.add_argument("--model-dir", type=Path, required=True)
    register.add_argument("--model-id", required=True)
    register.add_argument("--revision", required=True, help="Exact 40-character upstream commit")
    register.add_argument("--output", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            job = prepare(
                args.folder,
                args.output,
                recursive=args.recursive,
                same_object=args.same_object,
                batch_size=args.batch_size,
            )
            result = {
                "status": "prepared",
                "images": len(job["assets"]),
                "windows": len(job["segments"]),
                "same_object": job["same_object"],
            }
        elif args.command == "analyze":
            require(
                platform.system() == "Darwin" and platform.machine() == "arm64",
                "mlx_requires_apple_silicon_macos",
            )
            value = analyze(
                args.run,
                args.model_dir,
                args.profile,
                timeout=args.timeout,
                segment_timeout=args.segment_timeout,
                max_tokens=args.max_tokens,
            )
            result = {
                "status": value["status"],
                "windows": len(value["segments"]),
                "completed": sum(s["status"] == "completed" for s in value["segments"]),
                "reused_windows": value.get("reused_segments", 0),
            }
        elif args.command == "download-model":
            value = download_model(args.model_dir, args.profile)
            result = {"status": "downloaded_and_verified", "model_id": value["model_id"]}
        else:
            value = register_model(args.model_dir, args.model_id, args.revision, args.output)
            result = {"status": "registered", "model_id": value["model_id"]}
        print(json.dumps(result))
        return 0 if result["status"] not in {"partial", "failed"} else 2
    except (VisionError, ProposalError) as error:
        print(json.dumps({"status": "failed", "error_category": str(error)}), file=sys.stderr)
        return 2
    except FileExistsError:
        print('{"status":"failed","error_category":"run_locked_or_output_exists"}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"status":"failed","error_category":"cancelled"}', file=sys.stderr)
        return 130
    except Exception:
        print('{"status":"failed","error_category":"local_operation_failed"}', file=sys.stderr)
        return 3
