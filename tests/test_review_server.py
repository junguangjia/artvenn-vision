from __future__ import annotations

import json
import queue
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from artvenn_vision.images import prepare
from artvenn_vision.review_server import ReviewServer


@pytest.fixture
def server(photos, tmp_path):
    run = tmp_path / "run"
    prepare(photos, run)
    ready = queue.Queue()

    def worker():
        with ReviewServer(run) as instance:
            ready.put(instance)
            instance.serve_forever(poll_interval=0.05)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    instance = ready.get(timeout=10)
    yield instance
    instance.shutdown()
    thread.join(timeout=10)
    assert not thread.is_alive()


def call(server, route, data=None, *, session=True, origin=True, headers=None):
    request_headers = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        request_headers["Content-Type"] = "application/json"
        if session:
            request_headers["X-ArtVenn-Session"] = server.csrf_token
        if origin:
            request_headers["Origin"] = server.origin
    request = Request(server.origin + route, data=body, headers=request_headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def test_loopback_snapshot_hides_source_paths_and_frames(server):
    status, body, headers = call(server, "/api/review")
    assert status == 200
    data = json.loads(body)
    assert len(data["assets"]) == 3
    assert "source_path" not in body.decode()
    assert str(server.run) not in body.decode()
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    status, page, _ = call(server, "/")
    assert status == 200
    assert b'id="session-config"' in page
    assert b"<!--SESSION_CONFIG-->" not in page


def test_cross_origin_and_missing_session_cannot_save(server):
    draft = json.loads(call(server, "/api/review")[1])["draft"]
    data = {"expected_revision": 0, "draft": draft}
    assert call(server, "/api/save", data, session=False)[0] == 400
    assert call(server, "/api/save", data, origin=False)[0] == 400
    assert call(server, "/api/save", data, headers={"Host": "attacker.invalid"})[0] == 400
    assert call(server, "/api/review", headers={"Origin": "https://attacker.invalid"})[0] == 403
    assert json.loads(call(server, "/api/review")[1])["revision"] == 0


def test_save_confirm_export_are_distinct_and_revision_bound(server):
    state = json.loads(call(server, "/api/review")[1])
    ids = [asset["asset_id"] for asset in state["assets"]]
    draft = state["draft"]
    draft["objects"] = [{"object_id": "stele1", "title": "Test stele", "asset_ids": ids}]
    for asset_id in ids:
        draft["photos"][asset_id]["object_id"] = "stele1"
        draft["photos"][asset_id]["labels"] = {
            "object_kind": "inscription",
            "surfaces": ["front"],
            "parts": ["body"],
        }
    code, value, _ = call(server, "/api/save", {"expected_revision": 0, "draft": draft})
    assert code == 200
    saved = json.loads(value)
    assert saved["revision"] > 0
    assert saved["confirmed_revision"] != saved["revision"]
    assert call(server, "/api/save", {"expected_revision": 0, "draft": draft})[0] == 409
    assert call(server, "/api/export", {"expected_revision": saved["revision"]})[0] == 400
    assert (
        call(server, "/api/confirm", {"expected_revision": saved["revision"], "reviewer": ""})[0]
        == 400
    )
    code, value, _ = call(
        server,
        "/api/confirm",
        {"expected_revision": saved["revision"], "reviewer": "Synthetic test reviewer"},
    )
    assert code == 200
    assert json.loads(value)["confirmed_revision"] == saved["revision"]
    code, value, _ = call(server, "/api/export", {"expected_revision": saved["revision"]})
    assert code == 200
    exported = json.loads(value)
    assert "path" not in exported
    assert str(server.run) not in value.decode()
    code, dataset, _ = call(server, exported["download_url"])
    assert code == 200
    assert str(server.run) not in dataset.decode()
    assert "source_path" not in dataset.decode()


def test_preview_routes_reject_arbitrary_files(server):
    assert call(server, "/previews/a0001.jpg")[0] == 200
    assert call(server, "/previews/../../input.json")[0] == 403
    assert call(server, "/input.json")[0] == 404
    assert call(server, "/review.sqlite")[0] == 404
