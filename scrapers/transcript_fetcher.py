import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET


TIMEDTEXT_URL = "https://video.google.com/timedtext"


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
    selected = _select_track(tracks, languages)
    if selected is None:
        raise TranscriptNotFound(f"No caption track found for {video_id}")

    response = _get_xml(
        {
            "v": video_id,
            "lang": selected["lang_code"],
            "name": selected.get("name", ""),
        }
    )
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
    return selected["lang_code"], segments


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
) -> bool:
    video = json.loads(video_json_path.read_text(encoding="utf-8"))
    if video.get("transcript") and not overwrite:
        return False

    video_id = extract_video_id(video, video_json_path)
    language, segments = fetch_transcript_segments(video_id, languages)
    video["transcript"] = build_transcript_payload(video_id, language, segments)
    video_json_path.write_text(json.dumps(video, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


class TranscriptNotFound(RuntimeError):
    pass


def _list_caption_tracks(video_id: str) -> list[dict]:
    response = _get_xml({"type": "list", "v": video_id})
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


def _select_track(tracks: list[dict], languages: tuple[str, ...]) -> dict | None:
    for language in languages:
        for track in tracks:
            if track["lang_code"] == language:
                return track
    return tracks[0] if tracks else None


def _get_xml(params: dict) -> ET.Element:
    url = f"{TIMEDTEXT_URL}?{urlencode(params)}"
    with urlopen(url, timeout=20) as response:
        body = response.read()
    return ET.fromstring(body)
