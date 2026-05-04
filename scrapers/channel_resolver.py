import re
from googleapiclient.discovery import build


def extract_handle_from_url(url: str) -> tuple[str, str]:
    if match := re.search(r"/@([^/?]+)", url):
        return ("handle", match.group(1))
    if match := re.search(r"/channel/([^/?]+)", url):
        return ("id", match.group(1))
    if match := re.search(r"/user/([^/?]+)", url):
        return ("user", match.group(1))
    raise ValueError(f"Cannot parse YouTube URL: {url}")


def resolve_channel(youtube, url: str) -> tuple[str, str]:
    """Returns (channel_id, uploads_playlist_id)."""
    kind, value = extract_handle_from_url(url)

    if kind == "id":
        request = youtube.channels().list(part="contentDetails", id=value)
    elif kind == "handle":
        request = youtube.channels().list(part="contentDetails", forHandle=value)
    else:
        request = youtube.channels().list(part="contentDetails", forUsername=value)

    response = request.execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"No channel found for URL: {url}")

    channel_id = items[0]["id"]
    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return channel_id, uploads_playlist_id
