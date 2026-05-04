import json
import tempfile
from pathlib import Path

import transcript_fetcher
from transcript_fetcher import (
    TranscriptRateLimited,
    add_transcript_to_video_file,
    build_transcript_payload,
    extract_video_id,
    fetch_transcript_payload,
    parse_subtitle_file,
)


def test_extract_video_id_from_url():
    assert extract_video_id({"url": "https://www.youtube.com/watch?v=abc123"}) == "abc123"


def test_build_transcript_payload_has_scraped_at_and_text():
    payload = build_transcript_payload(
        "abc123",
        "en",
        [{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "world"}],
    )
    assert payload["scraped_at"].endswith("Z")
    assert payload["status"] == "available"
    assert payload["source"] == "youtube_direct"
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


def test_parse_json3_subtitle_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.en.json3"
        path.write_text(json.dumps({
            "events": [
                {"tStartMs": 1000, "dDurationMs": 2500, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
                {"tStartMs": 4000, "dDurationMs": 1000},
            ]
        }))

        language, segments = parse_subtitle_file(path)

    assert language == "en"
    assert segments == [{"start": 1.0, "end": 3.5, "text": "hello world"}]


def test_parse_vtt_subtitle_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "abc123.en.vtt"
        path.write_text("""WEBVTT

00:00:01.000 --> 00:00:03.500
<c>hello</c> world
""")

        language, segments = parse_subtitle_file(path)

    assert language == "en"
    assert segments == [{"start": 1.0, "end": 3.5, "text": "hello world"}]


def test_auto_provider_falls_back_after_direct_rate_limit(monkeypatch):
    def rate_limited(*_args, **_kwargs):
        raise TranscriptRateLimited("rate limited")

    def fake_ytdlp(_video, **_kwargs):
        return "en", [{"start": 0.0, "end": 1.0, "text": "fallback"}], {"subtitle_file": "abc.en.json3"}

    monkeypatch.setattr(transcript_fetcher, "fetch_transcript_segments_with_retries", rate_limited)
    monkeypatch.setattr(transcript_fetcher, "fetch_ytdlp_subtitle_segments", fake_ytdlp)

    payload = fetch_transcript_payload(
        {"video_id": "abc123"},
        Path("abc123.json"),
        provider="auto",
    )

    assert payload["source"] == "ytdlp_subtitles"
    assert payload["text"] == "fallback"
