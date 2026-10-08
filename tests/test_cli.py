from __future__ import annotations

import json

from artvenn_vision.cli import main


def test_folder_cli_creates_run(photos, tmp_path, capsys):
    assert main(["prepare", str(photos), "--output", str(tmp_path / "run"), "--same-object"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"status": "prepared", "images": 3, "windows": 1, "same_object": True}


def test_error_summary_contains_no_source_contents(photos, tmp_path, capsys):
    (tmp_path / "run").mkdir()
    assert main(["prepare", str(photos), "--output", str(tmp_path / "run")]) == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "error_category": "output_already_exists",
    }
