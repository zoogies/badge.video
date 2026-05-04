from datetime import datetime
from typing import Generator


def fetch_videos_since(youtube, uploads_playlist_id: str, since_epoch: int) -> Generator[dict, None, None]:
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId=uploads_playlist_id,
        maxResults=50,
    )

    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            published_at = snippet["publishedAt"]
            published_epoch = int(
                datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                .timestamp()
            )
            if published_epoch <= since_epoch:
                continue
            yield {
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "description": snippet["description"],
                "published_at": published_at,
            }
        request = youtube.playlistItems().list_next(request, response)
