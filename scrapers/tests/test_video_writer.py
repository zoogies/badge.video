import json
import tempfile
from pathlib import Path
from video_writer import write_video

def test_writes_json_file():
    video = {
        "video_id": "abc123",
        "title": "Test Video",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        write_video(videos_root, "MidwestSafety", video)
        out = videos_root / "MidwestSafety" / "abc123.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["video_id"] == "abc123"
        assert data["title"] == "Test Video"

def test_write_is_idempotent():
    video = {
        "video_id": "abc123",
        "title": "Test Video",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        write_video(videos_root, "MidwestSafety", video)
        write_video(videos_root, "MidwestSafety", video)
        files = list((videos_root / "MidwestSafety").iterdir())
        assert len(files) == 1

def test_includes_url():
    video = {
        "video_id": "abc123",
        "title": "Test Video",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        write_video(videos_root, "MidwestSafety", video)
        data = json.loads((videos_root / "MidwestSafety" / "abc123.json").read_text())
        assert data["url"] == "https://www.youtube.com/watch?v=abc123"
