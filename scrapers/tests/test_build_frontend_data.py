import json
import tempfile
from pathlib import Path

from build_frontend_data import build_frontend_data


def test_build_frontend_data_writes_compact_classified_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "Videos"
        channel = root / "Code Blue Cam"
        channel.mkdir(parents=True)
        (channel / "abc123.json").write_text(json.dumps({
            "video_id": "abc123",
            "title": "Bodycam title",
            "url": "https://www.youtube.com/watch?v=abc123",
            "published_at": "2026-01-02T00:00:00Z",
            "human_reviewed": False,
            "transcript": {
                "status": "available",
                "source": "faster_whisper",
                "model": "distil-large-v3",
                "scraped_at": "2026-01-03T00:00:00Z",
                "text": "large transcript should not be copied to the compact index",
                "segments": [{"start": 0, "end": 1, "text": "large transcript"}],
            },
            "classification": {
                "generated_at": "2026-01-04T00:00:00Z",
                "backend": "deepseek",
                "model": "deepseek-v4-flash",
                "result": {
                    "incident": {
                        "incident_date": "2025-12-31",
                        "location": {
                            "state": "Michigan",
                            "county": "Grand Traverse",
                            "city": "Traverse City",
                            "address_or_area": "Boardman Trail",
                        },
                        "agency": {"name": "Sheriff Office", "type": "sheriff"},
                    },
                    "legal": {
                        "alleged_crimes": [{"label": "Resisting arrest", "category": "resisting_arrest"}],
                        "charges": ["Resisting arrest"],
                    },
                    "event_summary": {
                        "short": "A short summary.",
                        "outcome": {"arrest_made": True, "foot_pursuit": True},
                    },
                    "classifications": {
                        "crime_categories": ["resisting_arrest"],
                        "incident_types": ["foot_pursuit"],
                    },
                    "confidence": "high",
                },
            },
        }), encoding="utf-8")
        (channel / "unclassified.json").write_text(json.dumps({"video_id": "unclassified"}), encoding="utf-8")
        output = Path(tmpdir) / "frontend-data"
        atlas = Path(tmpdir) / "metadata_atlas.json"

        build_frontend_data(videos_root=root, atlas_path=atlas, output_dir=output, repo_slug="owner/repo")

        index = json.loads((output / "videos.index.json").read_text(encoding="utf-8"))
        filters = json.loads((output / "filters.index.json").read_text(encoding="utf-8"))

    assert index["summary"]["included_videos"] == 1
    assert index["summary"]["skipped_unclassified"] == 1
    record = index["videos"][0]
    assert record["video_id"] == "abc123"
    assert record["state"] == "Michigan"
    assert record["crime_categories"] == ["resisting_arrest"]
    assert record["has_transcript"] is True
    assert "transcript" not in record
    assert "large transcript" not in json.dumps(record)
    assert filters["crime_categories"] == [{"value": "resisting_arrest", "count": 1}]
    assert filters["outcomes"] == [{"value": "arrest_made", "count": 1}, {"value": "foot_pursuit", "count": 1}]
    assert filters["charges"] == [{"value": "Resisting arrest", "count": 1}]
