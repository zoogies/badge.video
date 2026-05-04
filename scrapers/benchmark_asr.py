import argparse
import difflib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from transcript_fetcher import (
    DEFAULT_ASR_COMPUTE_TYPE,
    DEFAULT_ASR_DEVICE,
    build_transcript_payload_with_source,
    extract_video_id,
    _prepare_cuda_dll_paths,
    _transcribe_audio,
)


DEFAULT_OUTPUT_ROOT = Path(__file__).parent.parent / "database" / "TranscriptBenchmarks"
DEFAULT_MODELS = ("large-v3", "distil-large-v3", "large-v3-turbo")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ASR models without modifying video JSON.")
    parser.add_argument("--video-json", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--device", default=DEFAULT_ASR_DEVICE)
    parser.add_argument("--compute-type", default=DEFAULT_ASR_COMPUTE_TYPE)
    parser.add_argument("--cookies-from-browser")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    args = parser.parse_args()

    models = tuple(args.models) if args.models else DEFAULT_MODELS
    video = json.loads(args.video_json.read_text(encoding="utf-8"))
    video_id = extract_video_id(video, args.video_json)
    output_dir = args.output_root / video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.compare_only:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = download_audio(video, Path(tmpdir), args.cookies_from_browser, args.verbose)
            for model in models:
                try:
                    benchmark_model(
                        video_id=video_id,
                        audio_path=audio_path,
                        output_dir=output_dir,
                        model=model,
                        device=args.device,
                        compute_type=args.compute_type,
                        verbose=args.verbose,
                    )
                except Exception as exc:
                    write_model_error(output_dir, model, exc)
                    print(f"  {model}: ERROR {exc}", flush=True)

    write_comparison_report(output_dir, models)
    print(f"Wrote benchmark transcripts to {output_dir}")


def download_audio(video: dict, tmpdir: Path, cookies_from_browser: str | None, verbose: bool) -> Path:
    video_id = extract_video_id(video)
    url = video.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    output_base = tmpdir / video_id
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

    if verbose:
        print("Running: " + " ".join(command), flush=True)
    result = subprocess.run(command, text=True, capture_output=not verbose)
    if result.returncode != 0:
        raise RuntimeError(result.stderr if result.stderr else "yt-dlp audio download failed")

    audio_files = list(tmpdir.glob(f"{video_id}.*"))
    if not audio_files:
        raise RuntimeError("yt-dlp did not write an audio file")
    return audio_files[0]


def benchmark_model(
    video_id: str,
    audio_path: Path,
    output_dir: Path,
    model: str,
    device: str,
    compute_type: str,
    verbose: bool,
) -> None:
    print(f"Benchmarking {model}...", flush=True)
    _prepare_cuda_dll_paths()
    started = time.perf_counter()
    language, segments, runtime = _transcribe_audio(
        audio_path,
        asr_model=model,
        asr_device=device,
        asr_compute_type=compute_type,
        verbose=verbose,
    )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    payload = build_transcript_payload_with_source(
        video_id=video_id,
        language=language,
        segments=segments,
        source="faster_whisper_benchmark",
        model=model,
        details={
            **runtime,
            "elapsed_seconds": elapsed_seconds,
            "audio_file": audio_path.name,
        },
    )
    output_path = output_dir / f"{safe_model_filename(model)}.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {model}: {len(segments)} segments in {elapsed_seconds}s -> {output_path}", flush=True)


def write_model_error(output_dir: Path, model: str, exc: Exception) -> None:
    output_path = output_dir / f"{safe_model_filename(model)}.error.json"
    output_path.write_text(
        json.dumps(
            {
                "model": model,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def write_comparison_report(output_dir: Path, models: tuple[str, ...]) -> None:
    payloads = []
    for model in models:
        path = output_dir / f"{safe_model_filename(model)}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            payloads.append(payload)

    if not payloads:
        return

    baseline = payloads[0]
    lines = [
        "# ASR Benchmark Comparison",
        "",
        f"Baseline: `{baseline['model']}`",
        "",
        "| Model | Seconds | Segments | Words | Similarity vs Baseline |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]

    baseline_words = word_count(baseline["text"])
    for payload in payloads:
        similarity = difflib.SequenceMatcher(None, normalize_text(baseline["text"]), normalize_text(payload["text"])).ratio()
        lines.append(
            f"| {payload['model']} | {payload['details']['elapsed_seconds']} | "
            f"{payload['segment_count']} | {word_count(payload['text'])} | {similarity:.3f} |"
        )

    lines.extend(["", f"Baseline words: {baseline_words}", ""])
    for payload in payloads[1:]:
        lines.extend(model_diff_section(baseline, payload))

    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_pairwise_html(output_dir, payloads)


def model_diff_section(baseline: dict, candidate: dict) -> list[str]:
    baseline_sentences = split_sentences(baseline["text"])
    candidate_sentences = split_sentences(candidate["text"])
    matcher = difflib.SequenceMatcher(None, baseline_sentences, candidate_sentences)
    rows = [
        f"## `{candidate['model']}` vs `{baseline['model']}`",
        "",
        "| Type | Baseline | Candidate |",
        "| --- | --- | --- |",
    ]
    emitted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        baseline_text = " ".join(baseline_sentences[i1:i2])
        candidate_text = " ".join(candidate_sentences[j1:j2])
        rows.append(f"| {tag} | {escape_table(baseline_text)} | {escape_table(candidate_text)} |")
        emitted += 1
        if emitted >= 12:
            rows.append("| ... | Additional differences omitted. | Additional differences omitted. |")
            break
    if emitted == 0:
        rows.append("| none | No sentence-level differences detected. | No sentence-level differences detected. |")
    rows.append("")
    return rows


def write_pairwise_html(output_dir: Path, payloads: list[dict]) -> None:
    baseline = payloads[0]
    html_parts = [
        "<!doctype html><meta charset='utf-8'><title>ASR Benchmark Diff</title>",
        "<style>body{font-family:system-ui;margin:24px;line-height:1.35} table{border-collapse:collapse;width:100%} td,th{border:1px solid #ddd;padding:6px;vertical-align:top} ins{background:#d9fdd3;text-decoration:none} del{background:#ffd7d5;text-decoration:none}</style>",
        f"<h1>ASR Benchmark Diff</h1><p>Baseline: <code>{baseline['model']}</code></p>",
    ]
    for payload in payloads[1:]:
        diff = difflib.HtmlDiff(wrapcolumn=100).make_table(
            split_sentences(baseline["text"]),
            split_sentences(payload["text"]),
            fromdesc=baseline["model"],
            todesc=payload["model"],
            context=True,
            numlines=3,
        )
        html_parts.append(f"<h2>{payload['model']} vs {baseline['model']}</h2>")
        html_parts.append(diff)
    (output_dir / "comparison.html").write_text("\n".join(html_parts), encoding="utf-8")


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def escape_table(text: str) -> str:
    text = text.replace("|", "\\|").replace("\n", " ")
    return text[:700] + "..." if len(text) > 700 else text


def safe_model_filename(model: str) -> str:
    return model.replace("/", "__").replace("\\", "__")


if __name__ == "__main__":
    main()
