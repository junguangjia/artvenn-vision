from __future__ import annotations

import pytest
from PIL import Image


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    for index in range(3):
        Image.new("RGB", (100 + index, 80), (30 * index, 60, 100)).save(folder / f"{index}.jpg")
    return folder


@pytest.fixture
def proposal():
    return {
        "groups": [
            {
                "key": "g1",
                "asset_ids": ["a1", "a2"],
                "fields": [
                    {"field": "title", "value": "Synthetic inscription", "evidence": ["a2"]}
                ],
            },
            {"key": "g2", "asset_ids": ["a3"], "fields": []},
        ],
        "roles": [
            {"asset_id": "a1", "role": "overview", "evidence": ["a1"]},
            {"asset_id": "a2", "role": "label", "evidence": ["a2"]},
            {"asset_id": "a3", "role": "detail", "evidence": ["a3"]},
        ],
        "relationships": [
            {"left": "g1", "right": "g2", "relation": "uncertain", "evidence": ["a1", "a3"]}
        ],
        "issues": [
            {
                "kind": "unreadable_text",
                "asset_ids": ["a3"],
                "message": "Text requires human review.",
            }
        ],
    }
