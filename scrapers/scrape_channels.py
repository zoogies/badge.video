import json
import time
from pathlib import Path
import os

from dotenv import load_dotenv
from googleapiclient.discovery import build

from channel_resolver import resolve_channel
from video_fetcher import fetch_videos_since
from video_writer import write_video

load_dotenv(Path(__file__).parent.parent / ".env")

CHANNELS_FILE = Path(__file__).parent.parent / "database" / "channels.json"
VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def main():
    api_key = os.environ["YOUTUBE_API_KEY"]
    youtube = build("youtube", "v3", developerKey=api_key)

    channels_data = json.loads(CHANNELS_FILE.read_text())

    for channel in channels_data["channels"]:
        name = channel["name"]
        url = channel["url"]
        since_epoch = channel.get("last_scraped_epoch", 0)

        print(f"Scraping {name} (since epoch {since_epoch})...")

        try:
            _channel_id, uploads_playlist_id = resolve_channel(youtube, url)
        except Exception as e:
            print(f"  ERROR resolving channel: {e}")
            continue

        count = 0
        for video in fetch_videos_since(youtube, uploads_playlist_id, since_epoch):
            try:
                write_video(VIDEOS_ROOT, name, video)
                count += 1
            except Exception as e:
                print(f"  WARNING: skipping {video.get('video_id')}: {e}")

        print(f"  Wrote {count} new videos.")
        channel["last_scraped_epoch"] = int(time.time())

    CHANNELS_FILE.write_text(json.dumps(channels_data, indent=4), encoding="utf-8")
    print("Done. Updated last_scraped_epoch in channels.json.")


if __name__ == "__main__":
    main()
