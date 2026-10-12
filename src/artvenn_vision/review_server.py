"""Private loopback editor for immutable local review records; no cloud operations."""

from __future__ import annotations

import hmac
import json
import secrets
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .review_store import ReviewStore
from .storage import VisionError, require

UI = Path(__file__).with_name("ui")
MAX_BODY = 8 * 1024 * 1024


class ReviewServer(HTTPServer):
    """Single request writer with a private, ephemeral session and exact Host checks."""

    def __init__(self, run: Path, port: int = 0):
        require(type(port) is int and 0 <= port <= 65535, "invalid_review_port")
        self.store = ReviewStore(run)
        self.run = run.resolve()
        self.csrf_token = secrets.token_urlsafe(32)
        self.downloads: dict[str, Path] = {}
        try:
            super().__init__(("127.0.0.1", port), ReviewHandler)
        except Exception:
            self.store.close()
            raise
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def server_close(self) -> None:
        super().server_close()
        self.store.close()


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: Any) -> None:
        # Requests, local filenames and review text never enter terminal logs.
        return

    def _reply(self, code: int, body: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: Any) -> None:
        self._reply(code, json.dumps(value, ensure_ascii=False).encode(), "application/json")

    def _host(self) -> None:
        require(self.headers.get("Host") == urlsplit(self.server.origin).netloc, "host_refused")
        origin = self.headers.get("Origin")
        require(origin is None or origin == self.server.origin, "origin_refused")

    def do_GET(self) -> None:
        try:
            self._host()
            route = urlsplit(self.path).path
            if route == "/":
                page = (UI / "index.html").read_text(encoding="utf-8")
                config = json.dumps({"csrfToken": self.server.csrf_token}).replace("<", "\\u003c")
                page = page.replace(
                    "<!--SESSION_CONFIG-->",
                    f'<script type="application/json" id="session-config">{config}</script>',
                )
                self._reply(200, page.encode(), "text/html; charset=utf-8")
            elif route == "/api/review":
                self._json(200, self.server.store.snapshot())
            elif route in {"/review.js", "/review.css"}:
                mime = "text/javascript" if route.endswith(".js") else "text/css"
                self._reply(200, (UI / route[1:]).read_bytes(), mime)
            elif route.startswith("/previews/"):
                asset_id = route.removeprefix("/previews/").removesuffix(".jpg")
                asset = next(
                    (
                        a
                        for a in self.server.store.snapshot()["assets"]
                        if a["asset_id"] == asset_id
                    ),
                    None,
                )
                require(asset is not None and route.endswith(".jpg"), "preview_not_found")
                assert asset is not None
                image = self.server.run / asset["preview"]
                require(
                    not image.is_symlink()
                    and image.resolve().is_relative_to(self.server.run / "previews"),
                    "preview_not_found",
                )
                self._reply(200, image.read_bytes(), "image/jpeg")
            elif route in self.server.downloads:
                self._reply(200, self.server.downloads[route].read_bytes(), "application/json")
            else:
                self._json(404, {"error_category": "route_not_found"})
        except VisionError as error:
            self._json(403, {"error_category": str(error)})
        except (OSError, ValueError, TypeError):
            self._json(400, {"error_category": "local_read_failed"})

    def do_POST(self) -> None:
        try:
            self._host()
            require(self.headers.get("Origin") == self.server.origin, "origin_refused")
            require(
                hmac.compare_digest(
                    self.headers.get("X-ArtVenn-Session", ""), self.server.csrf_token
                ),
                "session_refused",
            )
            require(self.headers.get_content_type() == "application/json", "json_required")
            length = int(self.headers.get("Content-Length", "0"))
            require(0 < length <= MAX_BODY, "request_size_exceeded")
            data = json.loads(self.rfile.read(length))
            require(isinstance(data, dict), "invalid_request")
            expected = data.get("expected_revision")
            require(type(expected) is int and expected >= 0, "invalid_expected_revision")
            route = urlsplit(self.path).path
            if route == "/api/save":
                require(set(data) == {"expected_revision", "draft"}, "invalid_request")
                result = self.server.store.save(expected, data["draft"])
            elif route == "/api/confirm":
                require(set(data) == {"expected_revision", "reviewer"}, "invalid_request")
                result = self.server.store.confirm(expected, data["reviewer"])
            elif route == "/api/export":
                require(set(data) == {"expected_revision"}, "invalid_request")
                require(self.server.store.snapshot()["revision"] == expected, "review_conflict")
                export_root = self.server.run / "exports"
                require(not export_root.is_symlink(), "export_parent_invalid")
                export_root.mkdir(mode=0o700, exist_ok=True)
                output = export_root / uuid.uuid4().hex
                result = self.server.store.export(output)
                file = output / "dataset.json"
                require(file.is_file() and not file.is_symlink(), "export_file_missing")
                download = f"/exports/{output.name}.json"
                self.server.downloads[download] = file
                result = {key: result.get(key) for key in {"dataset_id", "status", "counts"}}
                result["download_url"] = download
            else:
                self._json(404, {"error_category": "route_not_found"})
                return
            self._json(200, result)
        except VisionError as error:
            self._json(409 if "conflict" in str(error) else 400, {"error_category": str(error)})
        except (OSError, ValueError, TypeError):
            self._json(400, {"error_category": "invalid_request"})


def serve(run: Path, port: int = 0) -> None:
    with ReviewServer(run, port) as server:
        print(json.dumps({"status": "review_server_ready", "url": server.origin}), flush=True)
        server.serve_forever(poll_interval=0.25)
