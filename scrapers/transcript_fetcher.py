import json
import html
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET


TIMEDTEXT_URL = "https://video.google.com/timedtext"
WATCH_URL = "https://www.youtube.com/watch"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_video_id(video: dict, json_path: Path | None = None) -> str:
    if video.get("video_id"):
        return video["video_id"]
    if video.get("url"):
        query = parse_qs(urlparse(video["url"]).query)
        if query.get("v"):
            return query["v"][0]
    if json_path is not None:
        return json_path.stem
    raise ValueError("Video JSON does not contain video_id or a YouTube watch URL")


def fetch_transcript_segments(video_id: str, languages: tuple[str, ...] = ("en",)) -> tuple[str, list[dict]]:
    tracks = _list_caption_tracks(video_id)
    if not tracks:
        tracks = _list_watch_page_caption_tracks(video_id)

    selected = _select_track(tracks, languages)
    if selected is None:
        raise TranscriptNotFound(f"No caption track found for {video_id}")

    if selected.get("base_url"):
        response = _get_xml_url(selected["base_url"])
    else:
        params = {
            "v": video_id,
            "lang": selected["lang_code"],
            "name": selected.get("name", ""),
        }
        if selected.get("kind"):
            params["kind"] = selected["kind"]
        response = _get_xml(params)

    segments = _parse_transcript_xml(response)
    if not segments:
        raise TranscriptNotFound(f"Caption track for {video_id} did not contain transcript text")
    return selected["lang_code"], segments


def _parse_transcript_xml(response: ET.Element) -> list[dict]:
    segments = []
    for node in response.findall(".//text"):
        start = float(node.attrib.get("start", "0"))
        duration = float(node.attrib.get("dur", "0"))
        text = "".join(node.itertext()).strip()
        if text:
            segments.append(
                {
                    "start": start,
                    "end": round(start + duration, 3),
                    "text": text,
                }
            )
    return segments


def build_transcript_payload(video_id: str, language: str, segments: list[dict]) -> dict:
    return {
        "video_id": video_id,
        "source": "youtube_timedtext",
        "language": language,
        "scraped_at": utc_now_iso(),
        "segment_count": len(segments),
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
    }


def add_transcript_to_video_file(
    video_json_path: Path,
    languages: tuple[str, ...] = ("en",),
    overwrite: bool = True,
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
) -> bool:
    video = json.loads(video_json_path.read_text(encoding="utf-8"))
    if video.get("transcript") and not overwrite:
        return False

    video_id = extract_video_id(video, video_json_path)
    language, segments = fetch_transcript_segments_with_retries(
        video_id,
        languages=languages,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    video["transcript"] = build_transcript_payload(video_id, language, segments)
    video_json_path.write_text(json.dumps(video, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def fetch_transcript_segments_with_retries(
    video_id: str,
    languages: tuple[str, ...] = ("en",),
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
) -> tuple[str, list[dict]]:
    attempt = 0
    while True:
        try:
            return fetch_transcript_segments(video_id, languages)
        except TranscriptRateLimited:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(retry_backoff_seconds * attempt)


class TranscriptNotFound(RuntimeError):
    pass


class TranscriptRateLimited(RuntimeError):
    pass


def _list_caption_tracks(video_id: str) -> list[dict]:
    try:
        response = _get_xml({"type": "list", "v": video_id})
    except TranscriptRateLimited:
        raise
    except TranscriptNotFound:
        return []
    tracks = []
    for track in response.findall("track"):
        tracks.append(
            {
                "lang_code": track.attrib.get("lang_code", ""),
                "lang_original": track.attrib.get("lang_original", ""),
                "name": track.attrib.get("name", ""),
                "kind": track.attrib.get("kind", ""),
            }
        )
    return tracks


def _list_watch_page_caption_tracks(video_id: str) -> list[dict]:
    try:
        html_text = _get_text_url(f"{WATCH_URL}?{urlencode({'v': video_id, 'hl': 'en'})}")
        player_response = _extract_player_response(html_text)
    except TranscriptRateLimited:
        raise
    except (TranscriptNotFound, json.JSONDecodeError):
        return []

    tracklist = (
        player_response.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )
    tracks = []
    for track in tracklist:
        lang_code = track.get("languageCode", "")
        base_url = track.get("baseUrl")
        if not lang_code or not base_url:
            continue
        tracks.append(
            {
                "lang_code": lang_code,
                "lang_original": _caption_track_name(track),
                "name": "",
                "kind": track.get("kind", ""),
                "base_url": html.unescape(base_url),
            }
        )
    return tracks


def _caption_track_name(track: dict) -> str:
    name = track.get("name", {})
    if "simpleText" in name:
        return name["simpleText"]
    return "".join(run.get("text", "") for run in name.get("runs", []))


def _select_track(tracks: list[dict], languages: tuple[str, ...]) -> dict | None:
    for language in languages:
        for track in tracks:
            if track["lang_code"] == language:
                return track
    return tracks[0] if tracks else None


def _extract_player_response(html_text: str) -> dict:
    match = re.search(r"ytInitialPlayerResponse\s*=", html_text)
    if not match:
        raise TranscriptNotFound("YouTube watch page did not include player response")

    json_text = _extract_json_object(html_text, match.end())
    return json.loads(json_text)


def _extract_json_object(text: str, start: int) -> str:
    object_start = text.find("{", start)
    if object_start == -1:
        raise TranscriptNotFound("Could not find player response JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(object_start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[object_start : index + 1]

    raise TranscriptNotFound("Could not parse player response JSON object")


def _get_xml(params: dict) -> ET.Element:
    url = f"{TIMEDTEXT_URL}?{urlencode(params)}"
    return _get_xml_url(url)


def _get_xml_url(url: str) -> ET.Element:
    body = _get_bytes_url(url)

    if not body.strip():
        raise TranscriptNotFound("YouTube returned an empty caption response")

    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise TranscriptNotFound(f"YouTube returned malformed caption XML: {exc}") from exc


def _get_text_url(url: str) -> str:
    return _get_bytes_url(url).decode("utf-8", errors="replace")


def _get_bytes_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise TranscriptRateLimited(f"YouTube rate limited transcript requests: {exc}") from exc
        raise TranscriptNotFound(f"Caption request failed: {exc}") from exc
    except URLError as exc:
        raise TranscriptNotFound(f"Caption request failed: {exc}") from exc
