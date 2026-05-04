from unittest.mock import MagicMock
from video_fetcher import fetch_videos_since

def test_fetch_all_videos_no_filter():
    youtube = MagicMock()
    page1 = {
        "items": [
            {"snippet": {"resourceId": {"videoId": "v1"}, "title": "T1", "description": "D1", "publishedAt": "2024-01-01T00:00:00Z"}},
            {"snippet": {"resourceId": {"videoId": "v2"}, "title": "T2", "description": "D2", "publishedAt": "2024-02-01T00:00:00Z"}},
        ]
    }
    request = MagicMock()
    request.execute.return_value = page1
    youtube.playlistItems.return_value.list.return_value = request
    youtube.playlistItems.return_value.list_next.return_value = None

    results = list(fetch_videos_since(youtube, "PLuploads123", since_epoch=0))
    assert len(results) == 2
    assert results[0]["video_id"] == "v1"
    assert results[1]["video_id"] == "v2"


def test_fetch_filters_by_epoch():
    youtube = MagicMock()
    page1 = {
        "items": [
            {"snippet": {"resourceId": {"videoId": "v1"}, "title": "T1", "description": "D1", "publishedAt": "2020-01-01T00:00:00Z"}},
            {"snippet": {"resourceId": {"videoId": "v2"}, "title": "T2", "description": "D2", "publishedAt": "2024-06-01T00:00:00Z"}},
        ]
    }
    request = MagicMock()
    request.execute.return_value = page1
    youtube.playlistItems.return_value.list.return_value = request
    youtube.playlistItems.return_value.list_next.return_value = None

    # epoch for 2023-01-01
    results = list(fetch_videos_since(youtube, "PLuploads123", since_epoch=1672531200))
    assert len(results) == 1
    assert results[0]["video_id"] == "v2"
