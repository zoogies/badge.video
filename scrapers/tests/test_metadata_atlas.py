import json
import tempfile
from pathlib import Path

from metadata_atlas import build_metadata_atlas, rebuild_metadata_atlas


def test_metadata_atlas_collects_frontend_filter_values():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "Videos"
        channel = root / "Code Blue Cam"
        channel.mkdir(parents=True)
        (channel / "abc123.json").write_text(json.dumps({
            "video_id": "abc123",
            "human_reviewed": False,
            "transcript": {"status": "available", "source": "faster_whisper"},
            "classification": {
                "backend": "deepseek",
                "model": "deepseek-chat",
                "result": {
                    "incident": {
                        "location": {
                            "state": "Wisconsin",
                            "state_abbreviation": "WI",
                            "county": "Dane County",
                            "city": "Madison",
                            "location_name": "East Towne Mall",
                        },
                        "agency": {"name": "Madison Police Department", "type": "police"},
                    },
                    "geo": {
                        "zip_code": "53704",
                        "county_fips": "55025",
                    },
                    "legal": {
                        "alleged_crimes": [
                            {"label": "Resisting arrest", "category": "resisting_arrest"}
                        ]
                    },
                    "classifications": {
                        "crime_categories": ["resisting_arrest", "traffic_stop"],
                        "incident_types": ["traffic_stop"],
                        "tags": ["bodycam"],
                        "content_warnings": ["use_of_force"],
                        "severity": "medium",
                    },
                },
            },
        }), encoding="utf-8")

        atlas = build_metadata_atlas(root)

    assert atlas["summary"]["total_videos"] == 1
    assert atlas["summary"]["classified_videos"] == 1
    assert atlas["summary"]["transcribed_videos"] == 1
    assert atlas["filters"]["channels"] == [{"value": "Code Blue Cam", "count": 1}]
    assert atlas["filters"]["crime_categories"][0] == {"value": "resisting_arrest", "count": 1}
    assert {"value": "traffic_stop", "count": 1} in atlas["filters"]["crime_categories"]
    assert atlas["filters"]["states"] == [{"value": "Wisconsin", "count": 1}]
    assert atlas["filters"]["cities"] == [{"value": "Madison", "count": 1}]
    assert atlas["filters"]["agencies"] == [{"value": "Madison Police Department", "count": 1}]
    assert atlas["filters"]["location_names"] == [{"value": "East Towne Mall", "count": 1}]
    assert atlas["filters"]["zip_codes"] == [{"value": "53704", "count": 1}]
    assert atlas["filters"]["county_fips"] == [{"value": "55025", "count": 1}]


def test_rebuild_metadata_atlas_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "Videos"
        (root / "Channel").mkdir(parents=True)
        (root / "Channel" / "abc123.json").write_text(json.dumps({"video_id": "abc123"}), encoding="utf-8")
        atlas_path = Path(tmpdir) / "metadata_atlas.json"

        rebuild_metadata_atlas(videos_root=root, atlas_path=atlas_path)

        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    assert atlas["summary"]["total_videos"] == 1
