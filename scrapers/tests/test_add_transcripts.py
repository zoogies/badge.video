import json
import tempfile
from pathlib import Path

import add_transcripts as add_transcripts_module
from add_transcripts import add_transcripts
from transcript_fetcher import TranscriptRateLimited


def test_add_transcripts_stops_on_rate_limit(monkeypatch, capsys):
    calls = []

    def fake_add(path, **_kwargs):
        calls.append(path)
        raise TranscriptRateLimited("YouTube rate limited transcript requests")

    monkeypatch.setattr(add_transcripts_module, "add_transcript_to_video_file", fake_add)
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        channel = videos_root / "Channel"
        channel.mkdir()
        (channel / "one.json").write_text(json.dumps({"video_id": "one"}))
        (channel / "two.json").write_text(json.dumps({"video_id": "two"}))

        count = add_transcripts(videos_root=videos_root, delay_seconds=0)

    output = capsys.readouterr().out
    assert count == 0
    assert len(calls) == 1
    assert "Stopping transcript batch early" in output


def test_add_transcripts_passes_retry_options(monkeypatch):
    observed = {}

    def fake_add(_path, **kwargs):
        observed.update(kwargs)
        return True

    monkeypatch.setattr(add_transcripts_module, "add_transcript_to_video_file", fake_add)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "one.json"
        path.write_text(json.dumps({"video_id": "one"}))

        count = add_transcripts(
            video_json=path,
            delay_seconds=0,
            overwrite=True,
            retries=2,
            retry_backoff_seconds=5,
            provider="local-asr",
            allow_local_asr=True,
            asr_model="distil-large-v3",
            asr_device="cuda",
            asr_compute_type="int8_float16",
            asr_fallback_model="small.en",
            asr_fallback_device=None,
            asr_fallback_compute_type="int8",
            cookies_from_browser="chrome",
            verbose=True,
            mark_unavailable=True,
        )

    assert count == 1
    assert observed["retries"] == 2
    assert observed["retry_backoff_seconds"] == 5
    assert observed["provider"] == "local-asr"
    assert observed["allow_local_asr"] is True
    assert observed["asr_model"] == "distil-large-v3"
    assert observed["asr_device"] == "cuda"
    assert observed["asr_compute_type"] == "int8_float16"
    assert observed["asr_fallback_model"] == "small.en"
    assert observed["asr_fallback_device"] is None
    assert observed["asr_fallback_compute_type"] == "int8"
    assert observed["cookies_from_browser"] == "chrome"
    assert observed["verbose"] is True
    assert observed["mark_unavailable"] is True


def test_add_transcripts_defaults_to_no_overwrite(monkeypatch):
    observed = {}

    def fake_add(_path, **kwargs):
        observed.update(kwargs)
        return False

    monkeypatch.setattr(add_transcripts_module, "add_transcript_to_video_file", fake_add)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "one.json"
        path.write_text(json.dumps({"video_id": "one", "transcript": {"text": "existing"}}))

        add_transcripts(video_json=path, delay_seconds=0)

    assert observed["overwrite"] is False
