import json
from pathlib import Path


def write_video(videos_root: Path, channel_name: str, video: dict) -> None:
    channel_dir = videos_root / channel_name
    channel_dir.mkdir(parents=True, exist_ok=True)
    out = channel_dir / f"{video['video_id']}.json"
    payload = {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": f"https://www.youtube.com/watch?v={video['video_id']}",
        "published_at": video["published_at"],
        "description": video["description"],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
