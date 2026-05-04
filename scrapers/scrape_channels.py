import json
import time
from pathlib import Path
import os
import argparse

from dotenv import load_dotenv
from googleapiclient.discovery import build
from tqdm.auto import tqdm

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

    channels = channels_data["channels"]
    channel_progress = tqdm(channels, desc="Channels", unit="channel")
    for channel in channel_progress:
        name = channel["name"]
        url = channel["url"]
        since_epoch = channel.get("last_scraped_epoch", 0)

        channel_progress.set_postfix(channel=name, new_videos=total)
        tqdm.write(f"Scraping {name} (since epoch {since_epoch})...")

        try:
            _channel_id, uploads_playlist_id = resolve_channel(youtube, url)
        except Exception as e:
            tqdm.write(f"  ERROR resolving channel: {e}")
            continue

        count = 0
        videos = fetch_videos_since(youtube, uploads_playlist_id, since_epoch)
        for video in tqdm(videos, desc=f"{name} videos", unit="video", leave=False):
            try:
                write_video(videos_root, name, video)
                count += 1
            except Exception as e:
                tqdm.write(f"  WARNING: skipping {video.get('video_id')}: {e}")

        tqdm.write(f"  Wrote {count} new videos.")
        total += count
        channel_progress.set_postfix(channel=name, new_videos=total)
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
