import json
import time
from pathlib import Path
import os
import argparse

from dotenv import load_dotenv
from googleapiclient.discovery import build

from channel_resolver import resolve_channel
from video_fetcher import fetch_videos_since
from video_writer import write_video

load_dotenv(Path(__file__).parent.parent / ".env")

CHANNELS_FILE = Path(__file__).parent.parent / "database" / "channels.json"
VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def scrape_youtube_videos(channels_file: Path = CHANNELS_FILE, videos_root: Path = VIDEOS_ROOT) -> int:
    api_key = os.environ["YOUTUBE_API_KEY"]
    youtube = build("youtube", "v3", developerKey=api_key)

    channels_data = json.loads(channels_file.read_text(encoding="utf-8"))
    total = 0

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
                write_video(videos_root, name, video)
                count += 1
            except Exception as e:
                print(f"  WARNING: skipping {video.get('video_id')}: {e}")

        print(f"  Wrote {count} new videos.")
        total += count
        channel["last_scraped_epoch"] = int(time.time())

    channels_file.write_text(json.dumps(channels_data, indent=4), encoding="utf-8")
    print("Done. Updated last_scraped_epoch in channels.json.")
    return total


def main():
    parser = argparse.ArgumentParser(description="Search configured YouTube channels for new videos.")
    parser.add_argument("--channels-file", type=Path, default=CHANNELS_FILE)
    parser.add_argument("--videos-root", type=Path, default=VIDEOS_ROOT)
    args = parser.parse_args()
    scrape_youtube_videos(channels_file=args.channels_file, videos_root=args.videos_root)


if __name__ == "__main__":
    main()
