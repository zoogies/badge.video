import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATABASE_ROOT = Path(__file__).parent.parent / "database"
DEFAULT_VIDEOS_ROOT = DATABASE_ROOT / "Videos"
DEFAULT_ATLAS_PATH = DATABASE_ROOT / "metadata_atlas.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iter_video_files(videos_root: Path):
    yield from videos_root.glob("*/*.json")


def rebuild_metadata_atlas(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    atlas_path: Path = DEFAULT_ATLAS_PATH,
) -> dict:
    atlas = build_metadata_atlas(videos_root)
    atlas_path.parent.mkdir(parents=True, exist_ok=True)
    atlas_path.write_text(json.dumps(atlas, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote metadata atlas to {atlas_path}")
    return atlas


def build_metadata_atlas(videos_root: Path = DEFAULT_VIDEOS_ROOT) -> dict:
    counters: dict[str, Counter] = {
        "channels": Counter(),
        "states": Counter(),
        "state_abbreviations": Counter(),
        "counties": Counter(),
        "cities": Counter(),
        "agencies": Counter(),
        "agency_types": Counter(),
        "location_names": Counter(),
        "zip_codes": Counter(),
        "county_fips": Counter(),
        "crime_categories": Counter(),
        "incident_types": Counter(),
        "tags": Counter(),
        "content_warnings": Counter(),
        "alleged_crime_labels": Counter(),
        "alleged_crime_categories": Counter(),
        "severities": Counter(),
        "transcript_sources": Counter(),
        "classifier_backends": Counter(),
        "classifier_models": Counter(),
    }
    state_locations: dict[str, Counter] = defaultdict(Counter)
    county_locations: dict[str, Counter] = defaultdict(Counter)
    city_locations: dict[str, Counter] = defaultdict(Counter)

    total_videos = 0
    classified_videos = 0
    transcribed_videos = 0
    human_reviewed_videos = 0

    for path in iter_video_files(videos_root):
        total_videos += 1
        _add(counters["channels"], path.parent.name)
        video = _load_json(path)
        if not isinstance(video, dict):
            continue

        if video.get("human_reviewed") is True:
            human_reviewed_videos += 1

        transcript = video.get("transcript")
        if isinstance(transcript, dict) and transcript.get("status") == "available":
            transcribed_videos += 1
            _add(counters["transcript_sources"], transcript.get("source"))

        classification = video.get("classification")
        if not isinstance(classification, dict):
            continue

        result = classification.get("result")
        if not isinstance(result, dict):
            continue

        classified_videos += 1
        _add(counters["classifier_backends"], classification.get("backend"))
        _add(counters["classifier_models"], classification.get("model"))

        incident = _dict(result.get("incident"))
        location = _dict(incident.get("location"))
        agency = _dict(incident.get("agency"))
        geo = _dict(result.get("geo"))
        legal = _dict(result.get("legal"))
        classifications = _dict(result.get("classifications"))

        state = _clean(location.get("state"))
        county = _clean(location.get("county"))
        city = _clean(location.get("city"))

        _add(counters["states"], state)
        _add(counters["state_abbreviations"], location.get("state_abbreviation"))
        _add(counters["counties"], county)
        _add(counters["cities"], city)
        _add(counters["agencies"], agency.get("name"))
        _add(counters["agency_types"], agency.get("type"))
        _add(counters["location_names"], location.get("location_name"))
        _add(counters["location_names"], geo.get("address_or_place"))
        _add(counters["zip_codes"], geo.get("zip_code"))
        _add(counters["county_fips"], geo.get("county_fips"))
        _add(counters["severities"], classifications.get("severity"))

        for value in _list(classifications.get("crime_categories")):
            _add(counters["crime_categories"], value)
        for value in _list(classifications.get("incident_types")):
            _add(counters["incident_types"], value)
        for value in _list(classifications.get("tags")):
            _add(counters["tags"], value)
        for value in _list(classifications.get("content_warnings")):
            _add(counters["content_warnings"], value)

        for crime in _list(legal.get("alleged_crimes")):
            if isinstance(crime, dict):
                _add(counters["alleged_crime_labels"], crime.get("label"))
                _add(counters["alleged_crime_categories"], crime.get("category"))

        if state:
            if county:
                state_locations[state][county] += 1
            if city:
                state_locations[state][city] += 1
        if county and city:
            county_locations[county][city] += 1
        if city and state:
            city_locations[city][state] += 1

    return {
        "schema_version": "1.0",
        "generated_at": utc_now_iso(),
        "videos_root": str(videos_root),
        "summary": {
            "total_videos": total_videos,
            "classified_videos": classified_videos,
            "transcribed_videos": transcribed_videos,
            "human_reviewed_videos": human_reviewed_videos,
        },
        "filters": {key: _counter_items(counter) for key, counter in counters.items()},
        "locations": {
            "states": _nested_counter_items(state_locations),
            "counties": _nested_counter_items(county_locations),
            "cities": _nested_counter_items(city_locations),
        },
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Skipping invalid JSON while building atlas: {path}")
        return None


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


def _add(counter: Counter, value: Any) -> None:
    cleaned = _clean(value)
    if cleaned:
        counter[cleaned] += 1


def _counter_items(counter: Counter) -> list[dict]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


def _nested_counter_items(counters: dict[str, Counter]) -> list[dict]:
    return [
        {"value": value, "children": _counter_items(counter)}
        for value, counter in sorted(counters.items(), key=lambda item: item[0].lower())
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a global metadata atlas for frontend filters.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--atlas-path", type=Path, default=DEFAULT_ATLAS_PATH)
    args = parser.parse_args()
    rebuild_metadata_atlas(videos_root=args.videos_root, atlas_path=args.atlas_path)


if __name__ == "__main__":
    main()
