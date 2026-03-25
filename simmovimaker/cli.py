"""Command-line interface for SimMovieMaker.

Provides subcommands for creating videos from image sequences and for
common video editing operations (merge, split, trim, mute, speed change,
GIF creation, frame extraction, metadata manipulation, etc.).

All heavy lifting is delegated to :mod:`simmovimaker.video_ops` and
:mod:`simmovimaker.ffmpeg_utils`.
"""

import argparse
import glob
import os
import sys

from . import __version__
from .ffmpeg_utils import check_ffmpeg, FFmpegNotFoundError, run_ffmpeg
from .video_ops import (
    get_video_info,
    get_metadata,
    merge_videos,
    split_video,
    trim_video,
    mute_audio,
    change_speed,
    extract_frames,
    create_gif,
    strip_metadata,
    set_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_printer(percent):
    """Simple progress callback that prints a percentage bar to stderr."""
    bar_len = 40
    filled = int(bar_len * percent / 100.0)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {percent:5.1f}%")
    sys.stderr.flush()
    if percent >= 100.0:
        sys.stderr.write("\n")


def _error(message):
    """Print an error message to stderr and return exit code 1."""
    print(f"Error: {message}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_create(args):
    """Create a video from an image sequence (default subcommand)."""
    input_path = args.input
    output_file = args.output
    fps = args.fps
    codec = args.codec
    fmt = args.format
    pattern = args.pattern

    # Determine output filename
    if output_file is None:
        output_file = f"output.{fmt}"

    # Collect image files
    if os.path.isdir(input_path):
        if pattern:
            image_files = sorted(glob.glob(os.path.join(input_path, pattern)))
        else:
            extensions = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff")
            image_files = []
            for ext in extensions:
                image_files.extend(glob.glob(os.path.join(input_path, ext)))
            image_files.sort()
    elif os.path.isfile(input_path):
        # Treat as a text file containing one image path per line
        with open(input_path, "r", encoding="utf-8") as fh:
            image_files = [
                line.strip() for line in fh if line.strip() and not line.startswith("#")
            ]
    else:
        return _error(f"Input path does not exist: {input_path}")

    if not image_files:
        return _error("No image files found.")

    print(f"Found {len(image_files)} image(s).")
    print(f"Creating video: {output_file}  (fps={fps}, codec={codec}, format={fmt})")

    # Build ffmpeg command for image sequence
    # Write a temporary concat file listing each image with its duration
    import tempfile

    fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="smm_cli_")
    frame_duration = 1.0 / fps
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for img in image_files:
                safe = os.path.abspath(img).replace("'", "'\\''")
                fh.write(f"file '{safe}'\n")
                fh.write(f"duration {frame_duration}\n")
            # Repeat last file so the last frame is shown for its full duration
            if image_files:
                safe = os.path.abspath(image_files[-1]).replace("'", "'\\''")
                fh.write(f"file '{safe}'\n")

        ffmpeg_args = [
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
        ]
        if codec:
            ffmpeg_args += ["-c:v", codec]
        ffmpeg_args += ["-pix_fmt", "yuv420p", "-y", output_file]

        run_ffmpeg(ffmpeg_args, progress_callback=_progress_printer)
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)

    if os.path.isfile(output_file):
        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"Done. Output: {output_file} ({size_mb:.1f} MB)")
    else:
        return _error("Video creation failed -- output file was not produced.")

    return 0


def _cmd_merge(args):
    """Merge multiple video files."""
    input_files = args.inputs
    output_file = args.output

    for f in input_files:
        if not os.path.isfile(f):
            return _error(f"Input file not found: {f}")

    print(f"Merging {len(input_files)} video(s) into {output_file} ...")
    try:
        merge_videos(input_files, output_file, progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Output: {output_file}")
    return 0


def _cmd_split(args):
    """Split a video at given time points."""
    input_file = args.input
    output_dir = args.output_dir
    points_str = args.points

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    try:
        split_points = [float(p.strip()) for p in points_str.split(",")]
    except ValueError:
        return _error("Split points must be comma-separated numbers (seconds).")

    print(f"Splitting {input_file} at points {split_points} ...")
    try:
        outputs = split_video(input_file, output_dir, split_points,
                              progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Created {len(outputs)} segment(s):")
    for p in outputs:
        print(f"  {p}")
    return 0


def _cmd_mute(args):
    """Remove audio from a video."""
    input_file = args.input
    output_file = args.output

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    print(f"Muting audio: {input_file} -> {output_file} ...")
    try:
        mute_audio(input_file, output_file, progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Output: {output_file}")
    return 0


def _cmd_trim(args):
    """Trim a video between start and end times."""
    input_file = args.input
    output_file = args.output
    start = args.start
    end = args.end

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    print(f"Trimming {input_file} [{start}s - {end}s] -> {output_file} ...")
    try:
        trim_video(input_file, output_file, start, end,
                   progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Output: {output_file}")
    return 0


def _cmd_info(args):
    """Display information about a video file."""
    input_file = args.input

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    try:
        info = get_video_info(input_file)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"File:        {input_file}")
    print(f"Format:      {info['format_name']}")
    print(f"Duration:    {info['duration']:.2f} s")
    print(f"Resolution:  {info['width']}x{info['height']}")
    print(f"FPS:         {info['fps']:.2f}")
    print(f"Video codec: {info['codec']}")
    print(f"Audio codec: {info['audio_codec'] or '(none)'}")
    bitrate_kbps = info["bitrate"] / 1000 if info["bitrate"] else 0
    print(f"Bitrate:     {bitrate_kbps:.0f} kbps")
    size_mb = info["file_size"] / (1024 * 1024) if info["file_size"] else 0
    print(f"File size:   {size_mb:.2f} MB")
    return 0


def _cmd_metadata(args):
    """View, strip, or set metadata on a video file."""
    input_file = args.input

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    try:
        if args.strip:
            output_file = args.output
            if not output_file:
                return _error("--output is required when stripping metadata.")
            print(f"Stripping metadata: {input_file} -> {output_file} ...")
            strip_metadata(input_file, output_file, progress_callback=_progress_printer)
            print(f"Done. Output: {output_file}")

        elif args.set:
            output_file = args.output
            if not output_file:
                return _error("--output is required when setting metadata.")
            meta = {}
            for item in args.set:
                if "=" not in item:
                    return _error(f"Invalid metadata format (expected key=value): {item}")
                key, value = item.split("=", 1)
                meta[key] = value
            print(f"Setting metadata on {input_file} -> {output_file} ...")
            set_metadata(input_file, output_file, meta,
                         progress_callback=_progress_printer)
            print(f"Done. Output: {output_file}")

        else:
            # View metadata
            tags = get_metadata(input_file)
            if not tags:
                print("No metadata tags found.")
            else:
                print(f"Metadata for {input_file}:")
                for key, value in sorted(tags.items()):
                    print(f"  {key}: {value}")

    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    return 0


def _cmd_extract_frames(args):
    """Extract frames from a video."""
    input_file = args.input
    output_dir = args.output_dir
    fps = args.fps
    fmt = args.format

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    print(f"Extracting frames from {input_file} -> {output_dir}/ ...")
    try:
        extracted = extract_frames(input_file, output_dir, fps=fps, format=fmt,
                                   progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Extracted {len(extracted)} frame(s).")
    return 0


def _cmd_gif(args):
    """Create a GIF from a video."""
    input_file = args.input
    output_file = args.output
    fps = args.fps
    width = args.width

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    print(f"Creating GIF: {input_file} -> {output_file} (fps={fps}, width={width}) ...")
    try:
        create_gif(input_file, output_file, fps=fps, width=width,
                   progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    if os.path.isfile(output_file):
        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"Done. Output: {output_file} ({size_mb:.1f} MB)")
    else:
        return _error("GIF creation failed.")
    return 0


def _cmd_speed(args):
    """Change the playback speed of a video."""
    input_file = args.input
    output_file = args.output
    factor = args.factor

    if not os.path.isfile(input_file):
        return _error(f"Input file not found: {input_file}")

    if factor <= 0:
        return _error("Speed factor must be a positive number.")

    print(f"Changing speed: {input_file} -> {output_file} (factor={factor}x) ...")
    try:
        change_speed(input_file, output_file, factor,
                     progress_callback=_progress_printer)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))

    print(f"Done. Output: {output_file}")
    return 0


def _cmd_check_ffmpeg(args):
    """Check whether ffmpeg is installed and reachable."""
    status = check_ffmpeg()

    if status["available"]:
        print("ffmpeg is available.")
        print(f"  ffmpeg:  {status['ffmpeg_path']}")
        print(f"  ffprobe: {status['ffprobe_path']}")
        if status["version"]:
            print(f"  Version: {status['version']}")
    else:
        print("ffmpeg is NOT available.", file=sys.stderr)
        if status["ffmpeg_path"]:
            print(f"  ffmpeg found at:  {status['ffmpeg_path']}")
        else:
            print("  ffmpeg:  not found")
        if status["ffprobe_path"]:
            print(f"  ffprobe found at: {status['ffprobe_path']}")
        else:
            print("  ffprobe: not found")
        print()
        from .ffmpeg_utils import get_ffmpeg_help_text
        print(get_ffmpeg_help_text())
        return 1

    return 0


# ---------------------------------------------------------------------------
# Argument parser construction
# ---------------------------------------------------------------------------

def _build_parser():
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="simmovimaker",
        description="SimMovieMaker -- create movies from simulation snapshots "
                    "and perform common video editing tasks.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- create (default when no subcommand) ---------------------------------
    p_create = subparsers.add_parser(
        "create", help="Create a video from an image sequence",
    )
    p_create.add_argument(
        "-i", "--input", required=True,
        help="Input directory containing images, or a text file listing image paths",
    )
    p_create.add_argument("-o", "--output", default=None, help="Output video filename")
    p_create.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30)")
    p_create.add_argument("--format", default="mp4", help="Output format (default: mp4)")
    p_create.add_argument("--codec", default="libx264", help="Video codec (default: libx264)")
    p_create.add_argument("--pattern", default=None, help="Filename glob pattern for image sequence (e.g. 'frame_*.png')")

    # -- merge ---------------------------------------------------------------
    p_merge = subparsers.add_parser("merge", help="Merge multiple videos into one")
    p_merge.add_argument("inputs", nargs="+", help="Input video files to merge")
    p_merge.add_argument("-o", "--output", required=True, help="Output file")

    # -- split ---------------------------------------------------------------
    p_split = subparsers.add_parser("split", help="Split a video at given time points")
    p_split.add_argument("-i", "--input", required=True, help="Input video file")
    p_split.add_argument("-d", "--output-dir", required=True, help="Output directory for segments")
    p_split.add_argument("-p", "--points", required=True, help="Split points in seconds (comma-separated, e.g. '10,25,60')")

    # -- mute ----------------------------------------------------------------
    p_mute = subparsers.add_parser("mute", help="Remove audio from a video")
    p_mute.add_argument("-i", "--input", required=True, help="Input video file")
    p_mute.add_argument("-o", "--output", required=True, help="Output file")

    # -- trim ----------------------------------------------------------------
    p_trim = subparsers.add_parser("trim", help="Trim a video between start and end times")
    p_trim.add_argument("-i", "--input", required=True, help="Input video file")
    p_trim.add_argument("-o", "--output", required=True, help="Output file")
    p_trim.add_argument("-s", "--start", type=float, required=True, help="Start time in seconds")
    p_trim.add_argument("-e", "--end", type=float, required=True, help="End time in seconds")

    # -- info ----------------------------------------------------------------
    p_info = subparsers.add_parser("info", help="Display information about a video file")
    p_info.add_argument("-i", "--input", required=True, help="Input video file")

    # -- metadata ------------------------------------------------------------
    p_meta = subparsers.add_parser("metadata", help="View, strip, or set video metadata")
    p_meta.add_argument("-i", "--input", required=True, help="Input video file")
    p_meta.add_argument("-o", "--output", default=None, help="Output file (required for --strip / --set)")
    p_meta.add_argument("--strip", action="store_true", help="Strip all metadata")
    p_meta.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="Set metadata key=value pairs")

    # -- extract-frames ------------------------------------------------------
    p_frames = subparsers.add_parser("extract-frames", help="Extract frames from a video")
    p_frames.add_argument("-i", "--input", required=True, help="Input video file")
    p_frames.add_argument("-d", "--output-dir", required=True, help="Output directory for frames")
    p_frames.add_argument("--fps", type=float, default=None, help="Extraction FPS (default: all frames)")
    p_frames.add_argument("--format", default="png", help="Output image format (default: png)")

    # -- gif -----------------------------------------------------------------
    p_gif = subparsers.add_parser("gif", help="Create an animated GIF from a video")
    p_gif.add_argument("-i", "--input", required=True, help="Input video file")
    p_gif.add_argument("-o", "--output", required=True, help="Output GIF file")
    p_gif.add_argument("--fps", type=int, default=10, help="GIF frame rate (default: 10)")
    p_gif.add_argument("--width", type=int, default=480, help="GIF width in pixels (default: 480)")

    # -- speed ---------------------------------------------------------------
    p_speed = subparsers.add_parser("speed", help="Change video playback speed")
    p_speed.add_argument("-i", "--input", required=True, help="Input video file")
    p_speed.add_argument("-o", "--output", required=True, help="Output file")
    p_speed.add_argument("-f", "--factor", type=float, required=True, help="Speed factor (e.g. 2.0 = double speed)")

    # -- check-ffmpeg --------------------------------------------------------
    subparsers.add_parser("check-ffmpeg", help="Check ffmpeg installation status")

    return parser


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def cli_mode():
    """Parse command-line arguments and dispatch to the appropriate handler.

    Returns an integer exit code.
    """
    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "create": _cmd_create,
        "merge": _cmd_merge,
        "split": _cmd_split,
        "mute": _cmd_mute,
        "trim": _cmd_trim,
        "info": _cmd_info,
        "metadata": _cmd_metadata,
        "extract-frames": _cmd_extract_frames,
        "gif": _cmd_gif,
        "speed": _cmd_speed,
        "check-ffmpeg": _cmd_check_ffmpeg,
    }

    if args.command is None:
        parser.print_help()
        return 0

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except FFmpegNotFoundError as exc:
        return _error(str(exc))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        return _error(f"Unexpected error: {exc}")
