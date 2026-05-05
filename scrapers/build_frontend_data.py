import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metadata_atlas import DEFAULT_ATLAS_PATH, DEFAULT_VIDEOS_ROOT, rebuild_metadata_atlas


REPO_ROOT = Path(__file__).parent.parent
DEFAULT_FRONTEND_DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"
DEFAULT_REPO_SLUG = "zoogies/badge.video"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_frontend_data(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    atlas_path: Path = DEFAULT_ATLAS_PATH,
    output_dir: Path = DEFAULT_FRONTEND_DATA_DIR,
    repo_slug: str = DEFAULT_REPO_SLUG,
    rebuild_atlas: bool = True,
    include_unclassified: bool = False,
) -> dict:
    if rebuild_atlas:
        atlas = rebuild_metadata_atlas(videos_root=videos_root, atlas_path=atlas_path)
    else:
        atlas = _load_json(atlas_path) if atlas_path.exists() else {}

    videos: list[dict] = []
    state_counts: Counter = Counter()
    county_counts: Counter = Counter()
    city_counts: Counter = Counter()
    channel_counts: Counter = Counter()
    crime_counts: Counter = Counter()
    outcome_counts: Counter = Counter()
    charge_counts: Counter = Counter()
    reviewed_counts: Counter = Counter()
    state_counties: dict[str, Counter] = defaultdict(Counter)

    total_files = 0
    skipped_unclassified = 0

    for path in sorted(videos_root.glob("*/*.json")):
        total_files += 1
        video = _load_json(path)
        if not isinstance(video, dict):
            continue

        classification = _dict(video.get("classification"))
        result = _dict(classification.get("result"))
        if not result and not include_unclassified:
            skipped_unclassified += 1
            continue

        record = build_video_record(video, path, videos_root, repo_slug)
        videos.append(record)

        state = record.get("state") or "Unknown"
        county = record.get("county") or "Unknown"
        city = record.get("city") or "Unknown"
        channel = record.get("channel") or "Unknown"
        state_counts[state] += 1
        county_counts[county] += 1
        city_counts[city] += 1
        channel_counts[channel] += 1
        reviewed_counts["reviewed" if record.get("human_reviewed") else "needs_review"] += 1
        if county != "Unknown":
            state_counties[state][county] += 1
        for category in record.get("crime_categories", []):
            crime_counts[category] += 1
        for outcome_name, outcome_value in record.get("outcome", {}).items():
            if outcome_value is True:
                outcome_counts[outcome_name] += 1
        record_charges: set[str] = set()
        for charge in record.get("charges", []):
            if charge:
                record_charges.add(charge)
        for crime in record.get("alleged_crimes", []):
            if isinstance(crime, dict) and crime.get("label"):
                record_charges.add(crime["label"])
        for charge in record_charges:
            charge_counts[charge] += 1

    videos.sort(key=lambda item: item.get("published_at") or "", reverse=True)

    payload = {
        "schema_version": "1.0",
        "generated_at": utc_now_iso(),
        "source": {
            "videos_root": str(videos_root),
            "atlas_path": str(atlas_path),
            "repo": repo_slug,
        },
        "summary": {
            "total_video_files": total_files,
            "included_videos": len(videos),
            "skipped_unclassified": skipped_unclassified,
            "human_reviewed": reviewed_counts["reviewed"],
            "needs_review": reviewed_counts["needs_review"],
        },
        "videos": videos,
    }

    location_payload = {
        "schema_version": "1.0",
        "generated_at": payload["generated_at"],
        "states": _counter_items(state_counts),
        "counties": _counter_items(county_counts),
        "cities": _counter_items(city_counts),
        "state_counties": [
            {"state": state, "counties": _counter_items(counter)}
            for state, counter in sorted(state_counties.items())
        ],
    }

    filters_payload = {
        "schema_version": "1.0",
        "generated_at": payload["generated_at"],
        "crime_categories": _counter_items(crime_counts),
        "outcomes": _counter_items(outcome_counts),
        "charges": _counter_items(charge_counts),
        "channels": _counter_items(channel_counts),
        "states": _counter_items(state_counts),
        "counties": _counter_items(county_counts),
        "cities": _counter_items(city_counts),
        "atlas_filters": atlas.get("filters", {}) if isinstance(atlas, dict) else {},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "videos.index.json", payload)
    _write_json(output_dir / "locations.index.json", location_payload)
    _write_json(output_dir / "filters.index.json", filters_payload)
    if isinstance(atlas, dict):
        _write_json(output_dir / "metadata_atlas.json", atlas)

    print(f"Wrote {len(videos)} frontend video records to {output_dir / 'videos.index.json'}")
    return payload


def build_video_record(video: dict, path: Path, videos_root: Path, repo_slug: str) -> dict:
    classification = _dict(video.get("classification"))
    result = _dict(classification.get("result"))
    incident = _dict(result.get("incident"))
    location = _dict(incident.get("location"))
    agency = _dict(incident.get("agency"))
    legal = _dict(result.get("legal"))
    event_summary = _dict(result.get("event_summary"))
    outcome = _dict(event_summary.get("outcome"))
    classes = _dict(result.get("classifications"))
    transcript = _dict(video.get("transcript"))
    relative_path = path.relative_to(videos_root.parent).as_posix()
    video_id = _clean(video.get("video_id")) or path.stem

    return {
        "video_id": video_id,
        "title": _clean(video.get("title")) or video_id,
        "url": _clean(video.get("url")) or f"https://www.youtube.com/watch?v={video_id}",
        "channel": path.parent.name,
        "published_at": _clean(video.get("published_at")),
        "video_scraped_at": _clean(video.get("scraped_at")),
        "transcript_scraped_at": _clean(transcript.get("scraped_at")),
        "classification_generated_at": _clean(classification.get("generated_at")),
        "state": _clean(location.get("state")),
        "state_abbreviation": _clean(location.get("state_abbreviation")),
        "county": _clean(location.get("county")),
        "city": _clean(location.get("city")),
        "address_or_area": _clean(location.get("address_or_area") or location.get("location_name")),
        "agency": _clean(agency.get("name")),
        "agency_type": _clean(agency.get("type")),
        "incident_date": _clean(incident.get("incident_date")),
        "crime_categories": _clean_list(classes.get("crime_categories")),
        "incident_types": _clean_list(classes.get("incident_types")),
        "tags": _clean_list(classes.get("tags")),
        "content_warnings": _clean_list(classes.get("content_warnings")),
        "alleged_crimes": [
            {
                "label": _clean(crime.get("label")),
                "category": _clean(crime.get("category")),
                "confidence": _clean(crime.get("confidence")),
            }
            for crime in _list(legal.get("alleged_crimes"))
            if isinstance(crime, dict)
        ],
        "charges": _clean_list(legal.get("charges")),
        "disposition": _clean(legal.get("disposition")),
        "summary": _clean(event_summary.get("short")),
        "outcome": {
            "arrest_made": _bool_or_none(outcome.get("arrest_made")),
            "injuries_reported": _bool_or_none(outcome.get("injuries_reported")),
            "shots_fired": _bool_or_none(outcome.get("shots_fired")),
            "fatality": _bool_or_none(outcome.get("fatality")),
            "use_of_force": _bool_or_none(outcome.get("use_of_force")),
            "vehicle_pursuit": _bool_or_none(outcome.get("vehicle_pursuit")),
            "foot_pursuit": _bool_or_none(outcome.get("foot_pursuit")),
        },
        "confidence": _clean(result.get("confidence")),
        "needs_human_review": _bool_or_none(result.get("needs_human_review")),
        "human_reviewed": video.get("human_reviewed") is True,
        "has_transcript": transcript.get("status") == "available",
        "transcript_source": _clean(transcript.get("source")),
        "transcript_model": _clean(transcript.get("model")),
        "classifier_backend": _clean(classification.get("backend")),
        "classifier_model": _clean(classification.get("model")),
        "data_path": relative_path,
        "github_issue_url": build_issue_url(repo_slug, video, relative_path, result),
    }


def build_issue_url(repo_slug: str, video: dict, relative_path: str, result: dict) -> str:
    title = f"Review requested: {video.get('title') or video.get('video_id')}"
    body = "\n".join([
        "### Video review request",
        "",
        f"- Video ID: `{video.get('video_id')}`",
        f"- Data file: `{relative_path}`",
        f"- URL: {video.get('url')}",
        "",
        "### Current classification",
        "",
        f"```json\n{json.dumps(result, indent=2, ensure_ascii=False)[:6000]}\n```",
        "",
        "### Requested correction",
        "",
        "Describe the field that should change and include a source or timestamp when possible.",
    ])
    query = {
        "title": title,
        "labels": "human-review,correction-requested",
        "body": body,
    }
    return f"https://github.com/{repo_slug}/issues/new?{_urlencode(query)}"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"Skipping unreadable JSON while building frontend data: {path}")
        return None


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "null", "none"}:
        return None
    return text


def _clean_list(value: Any) -> list[str]:
    return [cleaned for item in _list(value) if (cleaned := _clean(item))]


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _counter_items(counter: Counter) -> list[dict]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


def _urlencode(query: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(query)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact static JSON for the badge.video frontend.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--atlas-path", type=Path, default=DEFAULT_ATLAS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_FRONTEND_DATA_DIR)
    parser.add_argument("--repo", default=DEFAULT_REPO_SLUG)
    parser.add_argument("--no-atlas", action="store_true", help="Use the existing atlas instead of rebuilding it first.")
    parser.add_argument("--include-unclassified", action="store_true", help="Include videos without classification results.")
    args = parser.parse_args()
    build_frontend_data(
        videos_root=args.videos_root,
        atlas_path=args.atlas_path,
        output_dir=args.output_dir,
        repo_slug=args.repo,
        rebuild_atlas=not args.no_atlas,
        include_unclassified=args.include_unclassified,
    )


if __name__ == "__main__":
    main()
