import json
import tempfile
from pathlib import Path

import pytest

from review_corrections import (
    CorrectionError,
    apply_correction,
    build_validation_report,
    load_correction,
)


def write_video(root: Path) -> Path:
    path = root / "database" / "Videos" / "Channel" / "abc123.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "video_id": "abc123",
        "human_reviewed": False,
        "classification": {
            "result": {
                "incident": {
                    "location": {
                        "city": "Old City",
                        "county": "Old County",
                        "state": "Ohio",
                    },
                    "agency": {"name": "Old Agency"},
                    "incident_date": "2026-01-01",
                },
                "legal": {
                    "charges": ["Old charge"],
                    "alleged_crimes": [{"label": "Old charge", "confidence": "high"}],
                },
                "event_summary": {
                    "short": "Old summary.",
                    "outcome": {"arrest_made": False},
                },
                "classifications": {"crime_categories": ["traffic_stop"]},
            }
        },
    }), encoding="utf-8")
    return path


def write_issue(root: Path, payload: dict) -> Path:
    path = root / "issue.md"
    path.write_text("\n".join([
        "### Video metadata review",
        "",
        "```json",
        json.dumps(payload, indent=2),
        "```",
    ]), encoding="utf-8")
    return path


def test_apply_correction_updates_canonical_video_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        video_path = write_video(root)
        issue_path = write_issue(root, {
            "schema_version": 1,
            "kind": "metadata_review",
            "intent": "correction",
            "video_id": "abc123",
            "data_path": "database/Videos/Channel/abc123.json",
            "changes": {
                "classification.result.incident.location.city": "New City",
                "classification.result.event_summary.short": "New summary.",
                "classification.result.event_summary.outcome.arrest_made": True,
                "classification.result.legal.charges": ["New charge"],
                "classification.result.legal.alleged_crimes": [
                    {"label": "New charge", "category": None, "statute": None, "confidence": "human"}
                ],
                "human_reviewed": True,
            },
        })

        correction = load_correction(issue_path, root)
        apply_correction(correction)

        data = json.loads(video_path.read_text(encoding="utf-8"))
    result = data["classification"]["result"]
    assert data["human_reviewed"] is True
    assert result["incident"]["location"]["city"] == "New City"
    assert result["event_summary"]["short"] == "New summary."
    assert result["event_summary"]["outcome"]["arrest_made"] is True
    assert result["legal"]["charges"] == ["New charge"]
    assert result["legal"]["alleged_crimes"][0]["confidence"] == "human"


def test_rejects_path_traversal():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_video(root)
        issue_path = write_issue(root, {
            "video_id": "abc123",
            "data_path": "database/Videos/../secrets.json",
            "changes": {"human_reviewed": True},
        })

        with pytest.raises(CorrectionError, match="parent traversal"):
            load_correction(issue_path, root)


def test_validation_report_marks_duplicate_and_conflict():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_video(root)
        duplicate_payload = {
            "video_id": "abc123",
            "data_path": "database/Videos/Channel/abc123.json",
            "changes": {"classification.result.event_summary.short": "New summary."},
        }
        issue_path = write_issue(root, duplicate_payload)
        correction = load_correction(issue_path, root)
        duplicate = {
            "number": 10,
            "body": "```json\n" + json.dumps(duplicate_payload) + "\n```",
        }
        conflict = {
            "number": 11,
            "body": "```json\n" + json.dumps({
                "video_id": "abc123",
                "data_path": "database/Videos/Channel/abc123.json",
                "changes": {"classification.result.event_summary.short": "Different summary."},
            }) + "\n```",
        }

        report = build_validation_report(correction, [duplicate, conflict])

    assert "Duplicate of: #10" in report
    assert "Conflicts with: #11" in report
