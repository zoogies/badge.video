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

def test_includes_video_scraped_at():
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
        assert data["video_scraped_at"].endswith("Z")

def test_preserves_existing_enrichments_on_video_refresh():
    video = {
        "video_id": "abc123",
        "title": "Test Video",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        out = videos_root / "MidwestSafety" / "abc123.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({
            "video_id": "abc123",
            "transcript": {"text": "existing"},
            "classification": {"result": {"tags": ["existing"]}},
        }))
        write_video(videos_root, "MidwestSafety", video)
        data = json.loads(out.read_text())
        assert data["transcript"]["text"] == "existing"
        assert data["classification"]["result"]["tags"] == ["existing"]

def test_preserves_manual_fields_on_video_refresh():
    video = {
        "video_id": "abc123",
        "title": "Test Video",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        out = videos_root / "MidwestSafety" / "abc123.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({
            "video_id": "abc123",
            "title": "Test Video",
            "description": "A test",
            "published_at": "2024-01-01T00:00:00Z",
            "url": "https://www.youtube.com/watch?v=abc123",
            "human_reviewed": True,
            "manual_note": "keep me",
        }))
        write_video(videos_root, "MidwestSafety", video)
        data = json.loads(out.read_text())
        assert data["manual_note"] == "keep me"
        assert data["human_reviewed"] is True

def test_new_video_starts_unreviewed():
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
        assert data["human_reviewed"] is False

def test_metadata_change_clears_human_reviewed():
    original = {
        "video_id": "abc123",
        "title": "Original",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    updated = {
        "video_id": "abc123",
        "title": "Updated",
        "description": "A test",
        "published_at": "2024-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        videos_root = Path(tmpdir)
        write_video(videos_root, "MidwestSafety", original)
        out = videos_root / "MidwestSafety" / "abc123.json"
        data = json.loads(out.read_text())
        data["human_reviewed"] = True
        out.write_text(json.dumps(data))
        write_video(videos_root, "MidwestSafety", updated)
        assert json.loads(out.read_text())["human_reviewed"] is False
