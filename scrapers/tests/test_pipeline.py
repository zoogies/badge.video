from pathlib import Path

from pipeline import build_parser


def test_default_pipeline_command_is_usage_only(capsys):
    parser = build_parser()
    parser.print_help()
    output = capsys.readouterr().out
    assert "uv run pipeline.py videos" in output
    assert "uv run pipeline.py pipeline --skip-videos" in output


def test_pipeline_parser_supports_partial_pipeline():
    args = build_parser().parse_args(["pipeline", "--skip-videos", "--skip-classify", "--no-overwrite"])
    assert args.command == "pipeline"
    assert args.skip_videos is True
    assert args.skip_classify is True
    assert args.no_overwrite is True


def test_pipeline_parser_supports_single_video_file():
    args = build_parser().parse_args(["pipeline", "--video-json", "one.json"])
    assert args.video_json == Path("one.json")
