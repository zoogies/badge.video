import json
from pathlib import Path
from datetime import datetime, timezone


YOUTUBE_METADATA_KEYS = ("video_id", "title", "url", "published_at", "description")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_video(videos_root: Path, channel_name: str, video: dict) -> None:
    channel_dir = videos_root / channel_name
    channel_dir.mkdir(parents=True, exist_ok=True)
    out = channel_dir / f"{video['video_id']}.json"
    existing = {}
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8"))

    scraped_metadata = {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": f"https://www.youtube.com/watch?v={video['video_id']}",
        "published_at": video["published_at"],
        "description": video["description"],
    }

    metadata_changed = any(
        existing.get(key) != scraped_metadata[key]
        for key in YOUTUBE_METADATA_KEYS
    )

    payload = dict(existing)
    payload.update(scraped_metadata)
    payload["video_scraped_at"] = utc_now_iso()
    if "human_reviewed" not in payload or metadata_changed:
        payload["human_reviewed"] = False

    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
