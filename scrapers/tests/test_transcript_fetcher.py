import json
import tempfile
from pathlib import Path

import transcript_fetcher
from transcript_fetcher import add_transcript_to_video_file, build_transcript_payload, extract_video_id


def test_extract_video_id_from_url():
    assert extract_video_id({"url": "https://www.youtube.com/watch?v=abc123"}) == "abc123"


def test_build_transcript_payload_has_scraped_at_and_text():
    payload = build_transcript_payload(
        "abc123",
        "en",
        [{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "world"}],
    )
    assert payload["scraped_at"].endswith("Z")
    assert payload["segment_count"] == 2
    assert payload["text"] == "hello world"


def test_add_transcript_overwrites_existing_transcript(monkeypatch):
    def fake_fetch(video_id, languages):
        assert video_id == "abc123"
        assert languages == ("en",)
        return "en", [{"start": 0.0, "end": 1.0, "text": "new transcript"}]

    monkeypatch.setattr(transcript_fetcher, "fetch_transcript_segments", fake_fetch)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "transcript": {"text": "old"}}))
        assert add_transcript_to_video_file(path) is True
        data = json.loads(path.read_text())
        assert data["transcript"]["text"] == "new transcript"
        assert data["transcript"]["scraped_at"].endswith("Z")


def test_add_transcript_respects_no_overwrite(monkeypatch):
    def fake_fetch(_video_id, _languages):
        raise AssertionError("fetch should not be called")

    monkeypatch.setattr(transcript_fetcher, "fetch_transcript_segments", fake_fetch)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.json"
        path.write_text(json.dumps({"video_id": "abc123", "transcript": {"text": "old"}}))
        assert add_transcript_to_video_file(path, overwrite=False) is False
        assert json.loads(path.read_text())["transcript"]["text"] == "old"
