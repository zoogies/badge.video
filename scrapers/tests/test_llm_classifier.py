import json
import threading
import time
import tempfile
from pathlib import Path

import llm_classifier
from llm_classifier import build_user_payload, classify_video_file, classify_videos


def test_dry_run_classifier_writes_generated_at(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    monkeypatch.delenv("LLM_TRANSCRIPT_CONTEXT", raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({
            "video_id": "abc123",
            "title": "Test",
            "transcript": {"status": "available", "text": "hello", "segments": []},
        }))
        assert classify_video_file(path) is True
        data = json.loads(path.read_text())
        assert data["classification"]["generated_at"].endswith("Z")
        assert data["classification"]["backend"] == "dry_run"
        assert data["classification"]["transcript_context"] == "timestamped_text"
        assert data["classification"]["result"]["needs_human_review"] is True
        assert data["human_reviewed"] is False


def test_classifier_respects_no_overwrite(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "classification": {"result": "old"}}))
        assert classify_video_file(path, overwrite=False) is False
        assert json.loads(path.read_text())["classification"]["result"] == "old"


def test_classifier_skips_missing_transcript_by_default(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "title": "Test"}))
        assert classify_video_file(path) is False
        assert "classification" not in json.loads(path.read_text())


def test_classifier_can_include_untranscribed(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "title": "Test"}))
        assert classify_video_file(path, require_transcript=False) is True
        assert json.loads(path.read_text())["classification"]["result"]["needs_human_review"] is True


def test_classify_videos_continues_after_bad_json(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        channel = root / "Channel"
        channel.mkdir()
        (channel / "bad.json").write_text("{")
        good = channel / "good.json"
        good.write_text(json.dumps({
            "video_id": "good",
            "transcript": {"status": "available", "text": "hello"},
        }))

        assert classify_videos(root, update_atlas=False) == 1
        assert "classification" in json.loads(good.read_text())


def test_classify_videos_can_run_with_workers(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_classify_video_file(path, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(llm_classifier, "classify_video_file", fake_classify_video_file)
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        channel = root / "Channel"
        channel.mkdir()
        for index in range(4):
            (channel / f"{index}.json").write_text("{}")

        assert llm_classifier.classify_videos(root, update_atlas=False, workers=2) == 4
        assert max_active == 2


def test_classifier_uses_env_transcript_context(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "dry_run")
    monkeypatch.setenv("LLM_TRANSCRIPT_CONTEXT", "text")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({
            "video_id": "abc123",
            "transcript": {"status": "available", "text": "hello"},
        }))
        assert classify_video_file(path) is True
        data = json.loads(path.read_text())
        assert data["classification"]["transcript_context"] == "text"


def test_user_payload_defaults_to_compact_timestamped_text():
    payload = json.loads(build_user_payload({
        "video_id": "abc123",
        "title": "Test",
        "description": "Video description",
        "transcript": {
            "status": "available",
            "source": "faster_whisper",
            "text": "duplicated full transcript text",
            "segments": [
                {"start": 1.0, "end": 2.0, "text": "first line"},
                {"start": 2.0, "end": 3.0, "text": "second line", "extra": "ignored"},
            ],
        },
    }))

    assert payload["video"]["title"] == "Test"
    assert "text" not in payload["transcript"]
    assert "segments" not in payload["transcript"]
    assert payload["transcript"]["timestamped_text"] == "[0:01-0:02] first line\n[0:02-0:03] second line"


def test_user_payload_can_send_json_segments():
    payload = json.loads(build_user_payload({
        "transcript": {
            "status": "available",
            "text": "duplicated full transcript text",
            "segments": [
                {"start": 1.0, "end": 2.0, "text": "first line"},
                {"start": 2.0, "end": 3.0, "text": "second line", "extra": "ignored"},
            ],
        },
    }, transcript_context="segments"))

    assert "text" not in payload["transcript"]
    assert payload["transcript"]["segments"] == [
        {"start": 1.0, "end": 2.0, "text": "first line"},
        {"start": 2.0, "end": 3.0, "text": "second line"},
    ]


def test_user_payload_can_send_plain_transcript_text():
    payload = json.loads(build_user_payload({
        "transcript": {
            "status": "available",
            "text": "plain transcript",
            "segments": [{"start": 1.0, "end": 2.0, "text": "line"}],
        },
    }, transcript_context="text"))

    assert payload["transcript"]["text"] == "plain transcript"
    assert "segments" not in payload["transcript"]
