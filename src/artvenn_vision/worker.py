"""Private child-process entry; the parent redirects Python and native output."""

from __future__ import annotations

import argparse
from pathlib import Path

from .engine import run_inference
from .storage import VisionError, checkpoint, read_json

MAX_RESULT_BYTES = 256 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_inference(read_json(args.request), args.output)
        return 0 if result["status"] == "completed" else 2
    except Exception as error:
        category = str(error) if isinstance(error, VisionError) else "local_runtime_failure"
        result = (
            read_json(args.output, MAX_RESULT_BYTES) if args.output.exists() else {"segments": []}
        )
        result["status"] = (
            "partial" if any(s["status"] == "completed" for s in result["segments"]) else "failed"
        )
        result["error_category"] = category
        checkpoint(args.output, result)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
