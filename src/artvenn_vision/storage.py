"""Small private-file helpers shared by preparation and inference."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


class VisionError(ValueError):
    """A bounded English error code without original media or generated text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise VisionError(code)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def private_new(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def checkpoint(path: Path, value: Any) -> None:
    """Replace a task-owned file atomically, without following a destination symlink."""
    require(not path.is_symlink(), "output_symlink_refused")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with private_new(temporary) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, maximum: int = 4 * 1024 * 1024) -> Any:
    require(path.is_file() and not path.is_symlink(), "invalid_json_file")
    require(0 < path.stat().st_size <= maximum, "json_file_size_exceeded")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise VisionError("invalid_json_file") from None
