import html
import json
import os
import re
import shutil
import site
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


TIMEDTEXT_URL = "https://video.google.com/timedtext"
WATCH_URL = "https://www.youtube.com/watch"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_ASR_MODEL = "large-v3"
DEFAULT_ASR_DEVICE = "cuda"
DEFAULT_ASR_COMPUTE_TYPE = "int8_float16"
DEFAULT_ASR_FALLBACK_MODEL = "small.en"
DEFAULT_ASR_FALLBACK_DEVICE = None
DEFAULT_ASR_FALLBACK_COMPUTE_TYPE = "int8"
PROVIDERS = ("auto", "direct", "ytdlp-subtitles", "local-asr")
_CUDA_DLL_DIRECTORY_HANDLES = []


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_video_id(video: dict, json_path: Path | None = None) -> str:
    if video.get("video_id"):
        return video["video_id"]
    if video.get("url"):
        query = parse_qs(urlparse(video["url"]).query)
        if query.get("v"):
            return query["v"][0]
    if json_path is not None:
        return json_path.stem
    raise ValueError("Video JSON does not contain video_id or a YouTube watch URL")


def add_transcript_to_video_file(
    video_json_path: Path,
    languages: tuple[str, ...] = ("en",),
    overwrite: bool = True,
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
    provider: str = "auto",
    allow_local_asr: bool = False,
    asr_model: str = DEFAULT_ASR_MODEL,
    asr_device: str = DEFAULT_ASR_DEVICE,
    asr_compute_type: str = DEFAULT_ASR_COMPUTE_TYPE,
    asr_fallback_model: str = DEFAULT_ASR_FALLBACK_MODEL,
    asr_fallback_device: str | None = DEFAULT_ASR_FALLBACK_DEVICE,
    asr_fallback_compute_type: str = DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    cookies_from_browser: str | None = None,
    verbose: bool = False,
    mark_unavailable: bool = False,
) -> bool:
    video = json.loads(video_json_path.read_text(encoding="utf-8"))
    if video.get("transcript") and not overwrite:
        return False

    video_id = extract_video_id(video, video_json_path)
    try:
        transcript = fetch_transcript_payload(
            video=video,
            video_json_path=video_json_path,
            languages=languages,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            provider=provider,
            allow_local_asr=allow_local_asr,
            asr_model=asr_model,
            asr_device=asr_device,
            asr_compute_type=asr_compute_type,
            asr_fallback_model=asr_fallback_model,
            asr_fallback_device=asr_fallback_device,
            asr_fallback_compute_type=asr_fallback_compute_type,
            cookies_from_browser=cookies_from_browser,
            verbose=verbose,
        )
    except TranscriptNotFound as exc:
        if not mark_unavailable:
            raise
        transcript = build_unavailable_transcript_payload(video_id, str(exc))

    video["transcript"] = transcript
    video_json_path.write_text(json.dumps(video, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def fetch_transcript_payload(
    video: dict,
    video_json_path: Path,
    languages: tuple[str, ...] = ("en",),
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
    provider: str = "auto",
    allow_local_asr: bool = False,
    asr_model: str = DEFAULT_ASR_MODEL,
    asr_device: str = DEFAULT_ASR_DEVICE,
    asr_compute_type: str = DEFAULT_ASR_COMPUTE_TYPE,
    asr_fallback_model: str = DEFAULT_ASR_FALLBACK_MODEL,
    asr_fallback_device: str | None = DEFAULT_ASR_FALLBACK_DEVICE,
    asr_fallback_compute_type: str = DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    cookies_from_browser: str | None = None,
    verbose: bool = False,
) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported transcript provider: {provider}")

    video_id = extract_video_id(video, video_json_path)
    errors = []
    for provider_name in _providers_for(provider, allow_local_asr):
        _log_verbose(verbose, f"Trying transcript provider {provider_name} for {video_id}")
        try:
            if provider_name == "direct":
                language, segments = fetch_transcript_segments_with_retries(
                    video_id,
                    languages=languages,
                    retries=retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                    verbose=verbose,
                )
                return build_transcript_payload_with_source(video_id, language, segments, "youtube_direct")
            if provider_name == "ytdlp-subtitles":
                language, segments, details = fetch_ytdlp_subtitle_segments(
                    video,
                    languages=languages,
                    cookies_from_browser=cookies_from_browser,
                    verbose=verbose,
                )
                return build_transcript_payload_with_source(
                    video_id,
                    language,
                    segments,
                    "ytdlp_subtitles",
                    details=details,
                )
            if provider_name == "local-asr":
                language, segments, details = fetch_local_asr_segments(
                    video,
                    asr_model=asr_model,
                    asr_device=asr_device,
                    asr_compute_type=asr_compute_type,
                    asr_fallback_model=asr_fallback_model,
                    asr_fallback_device=asr_fallback_device,
                    asr_fallback_compute_type=asr_fallback_compute_type,
                    cookies_from_browser=cookies_from_browser,
                    verbose=verbose,
                )
                return build_transcript_payload_with_source(
                    video_id,
                    language,
                    segments,
                    "faster_whisper",
                    model=asr_model,
                    details=details,
                )
        except TranscriptRateLimited as exc:
            if provider == "auto":
                errors.append(f"{provider_name}: {exc}")
                continue
            raise
        except TranscriptNotFound as exc:
            errors.append(f"{provider_name}: {exc}")

    raise TranscriptNotFound("; ".join(errors) if errors else f"No transcript provider available for {video_id}")


def _providers_for(provider: str, allow_local_asr: bool) -> tuple[str, ...]:
    if provider == "auto":
        providers = ["direct", "ytdlp-subtitles"]
        if allow_local_asr:
            providers.append("local-asr")
        return tuple(providers)
    return (provider,)


def fetch_transcript_segments(video_id: str, languages: tuple[str, ...] = ("en",)) -> tuple[str, list[dict]]:
    tracks = _list_caption_tracks(video_id)
    if not tracks:
        tracks = _list_watch_page_caption_tracks(video_id)

    selected = _select_track(tracks, languages)
    if selected is None:
        raise TranscriptNotFound(f"No caption track found for {video_id}")

    if selected.get("base_url"):
        response = _get_xml_url(selected["base_url"])
    else:
        params = {
            "v": video_id,
            "lang": selected["lang_code"],
            "name": selected.get("name", ""),
        }
        if selected.get("kind"):
            params["kind"] = selected["kind"]
        response = _get_xml(params)

    segments = _parse_transcript_xml(response)
    if not segments:
        raise TranscriptNotFound(f"Caption track for {video_id} did not contain transcript text")
    return selected["lang_code"], segments


def fetch_transcript_segments_with_retries(
    video_id: str,
    languages: tuple[str, ...] = ("en",),
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    attempt = 0
    while True:
        try:
            return fetch_transcript_segments(video_id, languages)
        except TranscriptRateLimited:
            if attempt >= retries:
                raise
            attempt += 1
            sleep_seconds = retry_backoff_seconds * attempt
            _log_verbose(verbose, f"Rate limited; retrying in {sleep_seconds:g}s...")
            time.sleep(sleep_seconds)


def fetch_ytdlp_subtitle_segments(
    video: dict,
    languages: tuple[str, ...] = ("en",),
    cookies_from_browser: str | None = None,
    verbose: bool = False,
) -> tuple[str, list[dict], dict]:
    _require_executable("yt-dlp")
    video_id = extract_video_id(video)
    url = video.get("url") or f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_base = Path(tmpdir) / video_id
        command = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-subs",
            "--write-subs",
            "--sub-langs",
            _ytdlp_language_pattern(languages),
            "--sub-format",
            "json3/vtt/best",
            "--sleep-requests",
            "5",
            "--sleep-subtitles",
            "10",
            "-o",
            str(output_base) + ".%(ext)s",
            url,
        ]
        if cookies_from_browser:
            command.extend(["--cookies-from-browser", cookies_from_browser])

        _run_command(command, verbose=verbose)
        subtitle_files = _find_subtitle_files(Path(tmpdir), video_id)
        if not subtitle_files:
            raise TranscriptNotFound("yt-dlp did not write a subtitle file")

        subtitle_path = subtitle_files[0]
        language, segments = parse_subtitle_file(subtitle_path)
        if not segments:
            raise TranscriptNotFound(f"yt-dlp subtitle file was empty: {subtitle_path.name}")
        return language, segments, {"subtitle_file": subtitle_path.name}


def fetch_local_asr_segments(
    video: dict,
    asr_model: str = DEFAULT_ASR_MODEL,
    asr_device: str = DEFAULT_ASR_DEVICE,
    asr_compute_type: str = DEFAULT_ASR_COMPUTE_TYPE,
    asr_fallback_model: str = DEFAULT_ASR_FALLBACK_MODEL,
    asr_fallback_device: str | None = DEFAULT_ASR_FALLBACK_DEVICE,
    asr_fallback_compute_type: str = DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    cookies_from_browser: str | None = None,
    verbose: bool = False,
) -> tuple[str, list[dict], dict]:
    _require_executable("yt-dlp")
    _prepare_cuda_dll_paths()
    try:
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        raise TranscriptNotFound("faster-whisper is not installed") from exc

    video_id = extract_video_id(video)
    url = video.get("url") or f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_base = Path(tmpdir) / video_id
        command = [
            "yt-dlp",
            "-f",
            "ba/b",
            "-x",
            "--audio-format",
            "wav",
            "--audio-quality",
            "0",
            "-o",
            str(output_base) + ".%(ext)s",
            url,
        ]
        if cookies_from_browser:
            command.extend(["--cookies-from-browser", cookies_from_browser])

        _run_command(command, verbose=verbose)
        audio_files = list(Path(tmpdir).glob(f"{video_id}.*"))
        if not audio_files:
            raise TranscriptNotFound("yt-dlp did not write an audio file for local ASR")

        audio_path = audio_files[0]
        try:
            language, segments, runtime = _transcribe_audio(
                audio_path,
                asr_model=asr_model,
                asr_device=asr_device,
                asr_compute_type=asr_compute_type,
                verbose=verbose,
            )
        except Exception as exc:
            if not asr_fallback_device:
                raise
            _log_verbose(
                verbose,
                f"ASR failed on {asr_device}/{asr_compute_type}: {exc}. "
                f"Retrying {asr_fallback_model} on {asr_fallback_device}/{asr_fallback_compute_type}.",
            )
            language, segments, runtime = _transcribe_audio(
                audio_path,
                asr_model=asr_fallback_model,
                asr_device=asr_fallback_device,
                asr_compute_type=asr_fallback_compute_type,
                verbose=verbose,
            )
        if not segments:
            raise TranscriptNotFound("faster-whisper produced no transcript text")
        return language, segments, {"audio_file": audio_path.name, **runtime}


def _transcribe_audio(
    audio_path: Path,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    verbose: bool = False,
) -> tuple[str, list[dict], dict]:
    _prepare_cuda_dll_paths()
    from faster_whisper import WhisperModel

    _log_verbose(
        verbose,
        f"Running faster-whisper model {asr_model} on {audio_path.name} ({asr_device}, {asr_compute_type})",
    )
    model = WhisperModel(asr_model, device=asr_device, compute_type=asr_compute_type)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = []
    for index, segment in enumerate(segments_iter, start=1):
        if segment.text.strip():
            segments.append({"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()})
        if verbose and index % 25 == 0:
            print(f"Transcribed {index} ASR segments...", flush=True)
    return info.language or "en", segments, {"device": asr_device, "compute_type": asr_compute_type}


def _prepare_cuda_dll_paths() -> None:
    if os.name != "nt":
        return

    if _CUDA_DLL_DIRECTORY_HANDLES:
        return

    dll_names = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "nvrtc64_120_0.dll")
    dll_dirs = set()
    for site_root in site.getsitepackages():
        nvidia_root = Path(site_root) / "nvidia"
        for dll_name in dll_names:
            dll_dirs.update(path.parent for path in nvidia_root.glob(f"**/{dll_name}"))

    for dll_dir in sorted(dll_dirs):
        _CUDA_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))
    if dll_dirs:
        existing_path = os.environ.get("PATH", "")
        prefix = os.pathsep.join(str(path) for path in sorted(dll_dirs))
        os.environ["PATH"] = prefix + os.pathsep + existing_path


def build_transcript_payload(video_id: str, language: str, segments: list[dict]) -> dict:
    return build_transcript_payload_with_source(video_id, language, segments, "youtube_direct")


def build_transcript_payload_with_source(
    video_id: str,
    language: str,
    segments: list[dict],
    source: str,
    model: str | None = None,
    details: dict | None = None,
) -> dict:
    payload = {
        "status": "available",
        "video_id": video_id,
        "source": source,
        "language": language,
        "scraped_at": utc_now_iso(),
        "segment_count": len(segments),
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
    }
    if model:
        payload["model"] = model
    if details:
        payload["details"] = details
    return payload


def build_unavailable_transcript_payload(video_id: str, error: str) -> dict:
    return {
        "status": "unavailable",
        "video_id": video_id,
        "scraped_at": utc_now_iso(),
        "error": error,
    }


def parse_subtitle_file(path: Path) -> tuple[str, list[dict]]:
    language = _language_from_subtitle_name(path)
    suffix = path.suffix.lower()
    if suffix == ".json3":
        return language, _parse_json3_subtitles(path)
    if suffix == ".vtt":
        return language, _parse_vtt_subtitles(path)
    raise TranscriptNotFound(f"Unsupported subtitle format from yt-dlp: {path.name}")


class TranscriptNotFound(RuntimeError):
    pass


class TranscriptRateLimited(RuntimeError):
    pass


def _parse_transcript_xml(response: ET.Element) -> list[dict]:
    segments = []
    for node in response.findall(".//text"):
        start = float(node.attrib.get("start", "0"))
        duration = float(node.attrib.get("dur", "0"))
        text = "".join(node.itertext()).strip()
        if text:
            segments.append({"start": start, "end": round(start + duration, 3), "text": text})
    return segments


def _parse_json3_subtitles(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = []
    for event in data.get("events", []):
        if "segs" not in event:
            continue
        text = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
        if not text:
            continue
        start = event.get("tStartMs", 0) / 1000
        duration = event.get("dDurationMs", 0) / 1000
        segments.append({"start": round(start, 3), "end": round(start + duration, 3), "text": text})
    return segments


def _parse_vtt_subtitles(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    segments = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_line = next((line for line in lines if "-->" in line), None)
        if timing_line is None:
            continue
        timing_index = lines.index(timing_line)
        caption_text = " ".join(_clean_vtt_text(line) for line in lines[timing_index + 1 :]).strip()
        if not caption_text:
            continue
        start_text, end_text = [part.strip().split()[0] for part in timing_line.split("-->", 1)]
        segments.append({"start": _parse_timestamp(start_text), "end": _parse_timestamp(end_text), "text": caption_text})
    return segments


def _parse_timestamp(value: str) -> float:
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return round(hours * 3600 + minutes * 60 + seconds, 3)


def _clean_vtt_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value))


def _language_from_subtitle_name(path: Path) -> str:
    parts = path.name.split(".")
    return parts[-2] if len(parts) >= 3 else "unknown"


def _find_subtitle_files(directory: Path, video_id: str) -> list[Path]:
    candidates = list(directory.glob(f"{video_id}.*.json3")) + list(directory.glob(f"{video_id}.*.vtt"))
    return sorted(candidates, key=lambda path: (path.suffix != ".json3", path.name))


def _ytdlp_language_pattern(languages: tuple[str, ...]) -> str:
    return ",".join(f"{language}.*" if language == "en" else language for language in languages)


def _require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise TranscriptNotFound(f"{name} is not installed or not on PATH")


def _run_command(command: list[str], verbose: bool = False) -> None:
    _log_verbose(verbose, "Running: " + " ".join(command))
    result = subprocess.run(command, text=True, capture_output=True)
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if verbose and combined_output:
        print(combined_output, end="" if combined_output.endswith("\n") else "\n", flush=True)
    if result.returncode != 0:
        if "429" in combined_output or "Too Many Requests" in combined_output:
            raise TranscriptRateLimited(f"yt-dlp was rate limited: {combined_output.strip()}")
        raise TranscriptNotFound(f"command failed: {combined_output.strip()}")


def _log_verbose(verbose: bool, message: str) -> None:
    if verbose:
        print(message, flush=True)


def _list_caption_tracks(video_id: str) -> list[dict]:
    try:
        response = _get_xml({"type": "list", "v": video_id})
    except TranscriptRateLimited:
        raise
    except TranscriptNotFound:
        return []
    tracks = []
    for track in response.findall("track"):
        tracks.append(
            {
                "lang_code": track.attrib.get("lang_code", ""),
                "lang_original": track.attrib.get("lang_original", ""),
                "name": track.attrib.get("name", ""),
                "kind": track.attrib.get("kind", ""),
            }
        )
    return tracks


def _list_watch_page_caption_tracks(video_id: str) -> list[dict]:
    try:
        html_text = _get_text_url(f"{WATCH_URL}?{urlencode({'v': video_id, 'hl': 'en'})}")
        player_response = _extract_player_response(html_text)
    except TranscriptRateLimited:
        raise
    except (TranscriptNotFound, json.JSONDecodeError):
        return []

    tracklist = (
        player_response.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )
    tracks = []
    for track in tracklist:
        lang_code = track.get("languageCode", "")
        base_url = track.get("baseUrl")
        if not lang_code or not base_url:
            continue
        tracks.append(
            {
                "lang_code": lang_code,
                "lang_original": _caption_track_name(track),
                "name": "",
                "kind": track.get("kind", ""),
                "base_url": html.unescape(base_url),
            }
        )
    return tracks


def _caption_track_name(track: dict) -> str:
    name = track.get("name", {})
    if "simpleText" in name:
        return name["simpleText"]
    return "".join(run.get("text", "") for run in name.get("runs", []))


def _select_track(tracks: list[dict], languages: tuple[str, ...]) -> dict | None:
    for language in languages:
        for track in tracks:
            if track["lang_code"] == language:
                return track
    return tracks[0] if tracks else None


def _extract_player_response(html_text: str) -> dict:
    match = re.search(r"ytInitialPlayerResponse\s*=", html_text)
    if not match:
        raise TranscriptNotFound("YouTube watch page did not include player response")

    json_text = _extract_json_object(html_text, match.end())
    return json.loads(json_text)


def _extract_json_object(text: str, start: int) -> str:
    object_start = text.find("{", start)
    if object_start == -1:
        raise TranscriptNotFound("Could not find player response JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(object_start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[object_start : index + 1]

    raise TranscriptNotFound("Could not parse player response JSON object")


def _get_xml(params: dict) -> ET.Element:
    url = f"{TIMEDTEXT_URL}?{urlencode(params)}"
    return _get_xml_url(url)


def _get_xml_url(url: str) -> ET.Element:
    body = _get_bytes_url(url)

    if not body.strip():
        raise TranscriptNotFound("YouTube returned an empty caption response")

    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise TranscriptNotFound(f"YouTube returned malformed caption XML: {exc}") from exc


def _get_text_url(url: str) -> str:
    return _get_bytes_url(url).decode("utf-8", errors="replace")


def _get_bytes_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise TranscriptRateLimited(f"YouTube rate limited transcript requests: {exc}") from exc
        raise TranscriptNotFound(f"Caption request failed: {exc}") from exc
    except URLError as exc:
        raise TranscriptNotFound(f"Caption request failed: {exc}") from exc
