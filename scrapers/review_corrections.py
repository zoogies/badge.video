from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEOS_ROOT = DEFAULT_REPO_ROOT / "database" / "Videos"
PAYLOAD_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
FINGERPRINT_RE = re.compile(r"<!--\s*correction-fingerprint:\s*([a-f0-9]{64})\s*-->", re.IGNORECASE)
VIDEO_RE = re.compile(r"<!--\s*correction-video:\s*([^ >]+)\s*-->", re.IGNORECASE)
FIELDS_RE = re.compile(r"<!--\s*correction-fields:\s*([^>]+?)\s*-->", re.IGNORECASE)

OUTCOME_KEYS = {
    "arrest_made",
    "injuries_reported",
    "shots_fired",
    "fatality",
    "use_of_force",
    "vehicle_pursuit",
    "foot_pursuit",
}

ALLOWED_PATHS = {
    "human_reviewed",
    "classification.result.incident.location.city",
    "classification.result.incident.location.county",
    "classification.result.incident.location.state",
    "classification.result.incident.agency.name",
    "classification.result.incident.incident_date",
    "classification.result.legal.charges",
    "classification.result.legal.alleged_crimes",
    "classification.result.event_summary.short",
    "classification.result.classifications.crime_categories",
    *{f"classification.result.event_summary.outcome.{key}" for key in OUTCOME_KEYS},
}


class CorrectionError(Exception):
    pass


@dataclass(frozen=True)
class Correction:
    payload: dict[str, Any]
    path: Path
    relative_path: str
    video: dict[str, Any]
    changes: dict[str, Any]
    old_values: dict[str, Any]
    fingerprint: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and apply metadata review issues.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate an issue body and print a markdown report")
    validate.add_argument("--issue-body", type=Path, required=True)
    validate.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    validate.add_argument("--open-issues", type=Path)
    validate.add_argument("--output-json", type=Path)

    apply = subparsers.add_parser("apply", help="apply a validated issue body to the canonical video JSON")
    apply.add_argument("--issue-body", type=Path, required=True)
    apply.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    apply.add_argument("--output-json", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "validate":
            correction = load_correction(args.issue_body, args.repo_root)
            report = build_validation_report(correction, load_open_issues(args.open_issues))
            if args.output_json:
                write_json(args.output_json, summary_json(correction))
            print(report)
            return 0
        if args.command == "apply":
            correction = load_correction(args.issue_body, args.repo_root)
            apply_correction(correction)
            if args.output_json:
                write_json(args.output_json, summary_json(correction))
            print(f"Applied {len(correction.changes)} changed field(s) to {correction.relative_path}")
            return 0
    except CorrectionError as exc:
        print(build_invalid_report(str(exc)))
        return 1
    return 2


def load_correction(issue_body_path: Path, repo_root: Path = DEFAULT_REPO_ROOT) -> Correction:
    body = issue_body_path.read_text(encoding="utf-8")
    payload = extract_payload(body)
    changes = normalize_changes(payload)
    if not changes:
        raise CorrectionError("No changed fields were provided.")

    data_path = normalize_data_path(payload.get("data_path"))
    path = safe_video_path(repo_root, data_path)
    video = read_json(path)

    expected_video_id = str(payload.get("video_id") or "").strip()
    actual_video_id = str(video.get("video_id") or path.stem)
    if not expected_video_id:
        raise CorrectionError("Payload is missing video_id.")
    if expected_video_id != actual_video_id:
        raise CorrectionError(f"Payload video_id `{expected_video_id}` does not match file video_id `{actual_video_id}`.")

    old_values = {field: get_path(video, field) for field in changes}
    fingerprint = correction_fingerprint(expected_video_id, changes)
    return Correction(
        payload=payload,
        path=path,
        relative_path=data_path,
        video=video,
        changes=changes,
        old_values=old_values,
        fingerprint=fingerprint,
    )


def extract_payload(body: str) -> dict[str, Any]:
    matches = PAYLOAD_RE.findall(body)
    if not matches:
        raise CorrectionError("No fenced JSON payload was found in the issue body.")
    last_error: Exception | None = None
    for raw in reversed(matches):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(payload, dict) and ("changes" in payload or "classification_updates" in payload):
            return payload
    raise CorrectionError(f"No usable correction payload was found. {last_error or ''}".strip())


def normalize_changes(payload: dict[str, Any]) -> dict[str, Any]:
    raw_changes = payload.get("changes")
    if isinstance(raw_changes, dict):
        changes = dict(raw_changes)
    else:
        changes = changes_from_legacy_payload(payload)

    normalized: dict[str, Any] = {}
    for field, value in changes.items():
        field = str(field).strip()
        if field not in ALLOWED_PATHS:
            raise CorrectionError(f"Field `{field}` is not allowed.")
        validate_value(field, value)
        normalized[field] = value
    return normalized


def changes_from_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    updates = payload.get("classification_updates")
    if not isinstance(updates, dict):
        return {}

    changes: dict[str, Any] = {}
    if "human_reviewed" in payload:
        changes["human_reviewed"] = payload["human_reviewed"]

    incident = as_dict(updates.get("incident"))
    location = as_dict(incident.get("location"))
    agency = as_dict(incident.get("agency"))
    legal = as_dict(updates.get("legal"))
    summary = as_dict(updates.get("event_summary"))
    outcome = as_dict(summary.get("outcome"))
    classes = as_dict(updates.get("classifications"))

    copy_if_present(changes, location, "city", "classification.result.incident.location.city")
    copy_if_present(changes, location, "county", "classification.result.incident.location.county")
    copy_if_present(changes, location, "state", "classification.result.incident.location.state")
    copy_if_present(changes, agency, "name", "classification.result.incident.agency.name")
    copy_if_present(changes, incident, "incident_date", "classification.result.incident.incident_date")
    copy_if_present(changes, legal, "charges", "classification.result.legal.charges")
    copy_if_present(changes, legal, "alleged_crimes", "classification.result.legal.alleged_crimes")
    copy_if_present(changes, summary, "short", "classification.result.event_summary.short")
    copy_if_present(changes, classes, "crime_categories", "classification.result.classifications.crime_categories")
    for key in OUTCOME_KEYS:
        copy_if_present(changes, outcome, key, f"classification.result.event_summary.outcome.{key}")
    return changes


def copy_if_present(target: dict[str, Any], source: dict[str, Any], source_key: str, target_key: str) -> None:
    if source_key in source:
        target[target_key] = source[source_key]


def validate_value(field: str, value: Any) -> None:
    if field == "human_reviewed":
        if not isinstance(value, bool):
            raise CorrectionError("human_reviewed must be a boolean.")
        return
    if field.endswith(".outcome." + field.rsplit(".", 1)[-1]):
        if value is not None and not isinstance(value, bool):
            raise CorrectionError(f"{field} must be true, false, or null.")
        return
    if field in {
        "classification.result.legal.charges",
        "classification.result.classifications.crime_categories",
    }:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CorrectionError(f"{field} must be a list of strings.")
        return
    if field == "classification.result.legal.alleged_crimes":
        if not isinstance(value, list) or not all(isinstance(item, dict) and isinstance(item.get("label"), str) for item in value):
            raise CorrectionError("classification.result.legal.alleged_crimes must be a list of objects with string labels.")
        return
    if value is not None and not isinstance(value, str):
        raise CorrectionError(f"{field} must be a string or null.")


def normalize_data_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        raise CorrectionError("Payload is missing data_path.")
    if not text.startswith("database/"):
        text = f"database/{text.lstrip('/')}"
    return text


def safe_video_path(repo_root: Path, data_path: str) -> Path:
    pure = PurePosixPath(data_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise CorrectionError("data_path must be a relative path without parent traversal.")
    if pure.parts[:2] != ("database", "Videos") or pure.suffix.lower() != ".json":
        raise CorrectionError("data_path must point to a JSON file under database/Videos/.")
    path = (repo_root / Path(*pure.parts)).resolve()
    videos_root = (repo_root / "database" / "Videos").resolve()
    if videos_root not in path.parents:
        raise CorrectionError("Resolved data_path escapes database/Videos/.")
    if not path.exists():
        raise CorrectionError(f"Data file does not exist: {data_path}")
    return path


def apply_correction(correction: Correction) -> None:
    video = deepcopy(correction.video)
    for field, value in correction.changes.items():
        set_path(video, field, value)
    write_json(correction.path, video)


def get_path(data: dict[str, Any], field: str) -> Any:
    current: Any = data
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def set_path(data: dict[str, Any], field: str, value: Any) -> None:
    current: Any = data
    parts = field.split(".")
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def correction_fingerprint(video_id: str, changes: dict[str, Any]) -> str:
    canonical = json.dumps({"video_id": video_id, "changes": changes}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summary_json(correction: Correction) -> dict[str, Any]:
    return {
        "video_id": correction.payload.get("video_id"),
        "data_path": correction.relative_path,
        "fingerprint": correction.fingerprint,
        "fields": sorted(correction.changes),
        "branch": f"metadata-correction/{correction.payload.get('video_id')}-{correction.fingerprint[:10]}",
        "title": f"Apply metadata correction for {correction.payload.get('video_id')}",
    }


def build_validation_report(correction: Correction, open_issues: list[dict[str, Any]]) -> str:
    duplicate, conflicts = find_related_issues(correction, open_issues)
    lines = [
        "### Correction validation",
        "",
        "Status: valid",
        "",
        f"<!-- correction-fingerprint: {correction.fingerprint} -->",
        f"<!-- correction-video: {correction.payload.get('video_id')} -->",
        f"<!-- correction-fields: {','.join(sorted(correction.changes))} -->",
        "",
        f"- Video ID: `{correction.payload.get('video_id')}`",
        f"- Data file: `{correction.relative_path}`",
        f"- Changed fields: {len(correction.changes)}",
    ]
    if duplicate:
        lines.append(f"- Duplicate of: #{duplicate.get('number')}")
    if conflicts:
        lines.append("- Conflicts with: " + ", ".join(f"#{issue.get('number')}" for issue in conflicts))
    lines.extend(["", "### Proposed changes", "", "| Field | Current | Proposed |", "|---|---|---|"])
    for field in sorted(correction.changes):
        lines.append(f"| `{field}` | {markdown_value(correction.old_values.get(field))} | {markdown_value(correction.changes[field])} |")
    if correction.payload.get("review_comment"):
        lines.extend(["", "### Reviewer note", "", str(correction.payload["review_comment"])])
    return "\n".join(lines)


def build_invalid_report(reason: str) -> str:
    return "\n".join(["### Correction validation", "", "Status: invalid", "", reason])


def find_related_issues(correction: Correction, issues: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    duplicate = None
    conflicts: list[dict[str, Any]] = []
    fields = set(correction.changes)
    for issue in issues:
        body = str(issue.get("body") or "")
        marker = FINGERPRINT_RE.search(body)
        if marker and marker.group(1) == correction.fingerprint:
            duplicate = issue
            continue
        try:
            payload = extract_payload(body)
            changes = normalize_changes(payload)
        except CorrectionError:
            changes = {}
        if payload_video_id(body, changes) == str(correction.payload.get("video_id")):
            other_fingerprint = correction_fingerprint(str(correction.payload.get("video_id")), changes) if changes else None
            if other_fingerprint == correction.fingerprint:
                duplicate = issue
                continue
            overlapping = fields & set(changes)
            if any(changes[field] != correction.changes[field] for field in overlapping):
                conflicts.append(issue)
                continue
        video_match = VIDEO_RE.search(body)
        fields_match = FIELDS_RE.search(body)
        if not video_match or not fields_match:
            continue
        if video_match.group(1).strip() != str(correction.payload.get("video_id")):
            continue
        other_fields = {field.strip() for field in fields_match.group(1).split(",") if field.strip()}
        if fields & other_fields:
            conflicts.append(issue)
    return duplicate, conflicts


def payload_video_id(body: str, changes: dict[str, Any]) -> str | None:
    if not changes:
        return None
    try:
        payload = extract_payload(body)
    except CorrectionError:
        return None
    value = payload.get("video_id")
    return str(value).strip() if value else None


def load_open_issues(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    data = read_json(path)
    return data if isinstance(data, list) else []


def markdown_value(value: Any) -> str:
    if value is None:
        return "`null`"
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value)
    text = text.replace("\n", "<br>").replace("|", "\\|")
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
