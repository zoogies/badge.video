from urllib.error import HTTPError, URLError

import pytest

import transcript_fetcher
from transcript_fetcher import TranscriptNotFound, TranscriptRateLimited, fetch_transcript_segments


class EmptyResponse:
    def __init__(self, body=b""):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_empty_caption_list_is_transcript_not_found(monkeypatch):
    monkeypatch.setattr(transcript_fetcher, "urlopen", lambda *_args, **_kwargs: EmptyResponse())

    with pytest.raises(TranscriptNotFound, match="No caption track found"):
        fetch_transcript_segments("abc123")


def test_caption_request_error_is_transcript_not_found(monkeypatch):
    def raise_url_error(*_args, **_kwargs):
        raise URLError("network unavailable")

    monkeypatch.setattr(transcript_fetcher, "urlopen", raise_url_error)

    with pytest.raises(TranscriptNotFound, match="No caption track found"):
        fetch_transcript_segments("abc123")


def test_http_429_is_rate_limited(monkeypatch):
    def raise_429(*_args, **_kwargs):
        raise HTTPError("https://example.test", 429, "Too Many Requests", None, None)

    monkeypatch.setattr(transcript_fetcher, "urlopen", raise_429)

    with pytest.raises(TranscriptRateLimited, match="rate limited"):
        fetch_transcript_segments("abc123")


def test_watch_page_caption_tracks_are_used_when_list_is_empty(monkeypatch):
    watch_html = b"""
    <html><script>
    var ytInitialPlayerResponse = {
      "captions": {
        "playerCaptionsTracklistRenderer": {
          "captionTracks": [
            {
              "baseUrl": "https://example.test/caption?foo=1\\u0026bar=2",
              "languageCode": "en",
              "kind": "asr",
              "name": {"simpleText": "English (auto-generated)"}
            }
          ]
        }
      }
    };
    </script></html>
    """
    caption_xml = b'<transcript><text start="1.2" dur="3.4">hello world</text></transcript>'

    def fake_urlopen(request, timeout):
        url = request.full_url
        if "video.google.com/timedtext" in url:
            return EmptyResponse()
        if "youtube.com/watch" in url:
            return EmptyResponse(watch_html)
        if "example.test/caption" in url:
            return EmptyResponse(caption_xml)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(transcript_fetcher, "urlopen", fake_urlopen)

    language, segments = fetch_transcript_segments("abc123")

    assert language == "en"
    assert segments == [{"start": 1.2, "end": 4.6, "text": "hello world"}]
