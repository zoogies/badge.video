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
            retries=2,
            retry_backoff_seconds=5,
        )

    assert count == 1
    assert observed["retries"] == 2
    assert observed["retry_backoff_seconds"] == 5
