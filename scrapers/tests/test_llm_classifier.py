import json
import tempfile
from pathlib import Path

from llm_classifier import classify_video_file


def test_dry_run_classifier_writes_generated_at(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "title": "Test"}))
        assert classify_video_file(path) is True
        data = json.loads(path.read_text())
        assert data["classification"]["generated_at"].endswith("Z")
        assert data["classification"]["backend"] == "dry_run"
        assert data["classification"]["result"]["needs_human_review"] is True
        assert data["human_reviewed"] is False


def test_classifier_respects_no_overwrite(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "classification": {"result": "old"}}))
        assert classify_video_file(path, overwrite=False) is False
        assert json.loads(path.read_text())["classification"]["result"] == "old"
