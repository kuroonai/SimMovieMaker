"""
video_ops.py - Video operations using ffmpeg.

Provides functions for inspecting, merging, splitting, trimming,
converting, and otherwise manipulating video files.  All heavy lifting
is delegated to the ffmpeg / ffprobe binaries via the ffmpeg_utils
module in this package.
"""

import json
import math
import os
import tempfile

from .ffmpeg_utils import run_ffmpeg, run_ffprobe, check_ffmpeg, FFmpegNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_ffmpeg():
    """Raise FFmpegNotFoundError if ffmpeg is not available."""
    if not check_ffmpeg()["available"]:
        raise FFmpegNotFoundError("ffmpeg was not found on this system.")


def _safe_float(value, default=0.0):
    """Convert *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    """Convert *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

def get_video_info(filepath):
    """Return a dict describing the video at *filepath*.

    Keys: duration, width, height, fps, codec, audio_codec, bitrate,
    file_size, format_name.
    """
    _ensure_ffmpeg()

    args = [
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]
    output = run_ffprobe(args)
    data = json.loads(output)

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = None
    audio_stream = None
    for s in streams:
        if s.get("codec_type") == "video" and video_stream is None:
            video_stream = s
        elif s.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = s

    # Parse frame rate from the video stream (r_frame_rate is like "30/1").
    fps = 0.0
    if video_stream:
        rfr = video_stream.get("r_frame_rate", "0/1")
        parts = rfr.split("/")
        if len(parts) == 2 and _safe_float(parts[1]) != 0:
            fps = _safe_float(parts[0]) / _safe_float(parts[1])
        else:
            fps = _safe_float(parts[0])

    info = {
        "duration": _safe_float(fmt.get("duration")),
        "width": _safe_int(video_stream.get("width")) if video_stream else 0,
        "height": _safe_int(video_stream.get("height")) if video_stream else 0,
        "fps": fps,
        "codec": video_stream.get("codec_name", "") if video_stream else "",
        "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
        "bitrate": _safe_int(fmt.get("bit_rate")),
        "file_size": _safe_int(fmt.get("size")),
        "format_name": fmt.get("format_name", ""),
    }
    return info


def get_metadata(filepath):
    """Return all metadata tags from *filepath* as a dict."""
    _ensure_ffmpeg()

    args = [
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        filepath,
    ]
    output = run_ffprobe(args)
    data = json.loads(output)
    return data.get("format", {}).get("tags", {})


# ---------------------------------------------------------------------------
# Merge / Split / Trim
# ---------------------------------------------------------------------------

def merge_videos(input_files, output_file, progress_callback=None):
    """Concatenate *input_files* (list of paths) into *output_file*.

    Uses the ffmpeg concat demuxer with ``-c copy`` for speed.
    Returns the *output_file* path.
    """
    _ensure_ffmpeg()

    fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="smm_concat_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for path in input_files:
                safe = path.replace("'", "'\\''")
                fh.write(f"file '{safe}'\n")

        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_file,
        ]
        run_ffmpeg(args, progress_callback=progress_callback)
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)

    return output_file


def split_video(input_file, output_dir, split_points, progress_callback=None):
    """Split *input_file* at each time in *split_points* (seconds).

    Segments are written to *output_dir* with names like
    ``basename_001.ext``, ``basename_002.ext``, etc.

    Returns a list of output file paths.
    """
    _ensure_ffmpeg()

    os.makedirs(output_dir, exist_ok=True)

    base, ext = os.path.splitext(os.path.basename(input_file))
    sorted_points = sorted(split_points)

    # Build segment boundaries: [0, p1, p2, ..., end]
    boundaries = [0.0] + [float(p) for p in sorted_points]
    # We do not know the duration yet -- use None to mean "until end".
    segments = []
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else None
        segments.append((start, end))

    output_paths = []
    for idx, (start, end) in enumerate(segments, start=1):
        out_name = f"{base}_{idx:03d}{ext}"
        out_path = os.path.join(output_dir, out_name)

        args = ["-i", input_file, "-ss", str(start)]
        if end is not None:
            args += ["-to", str(end)]
        args += ["-c", "copy", out_path]

        run_ffmpeg(args, progress_callback=progress_callback)
        output_paths.append(out_path)

    return output_paths


def trim_video(input_file, output_file, start_time, end_time,
               progress_callback=None):
    """Trim *input_file* between *start_time* and *end_time* (seconds).

    Uses ``-c copy`` for speed.  Returns *output_file*.
    """
    _ensure_ffmpeg()

    args = [
        "-i", input_file,
        "-ss", str(start_time),
        "-to", str(end_time),
        "-c", "copy",
        output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


# ---------------------------------------------------------------------------
# Audio operations
# ---------------------------------------------------------------------------

def mute_audio(input_file, output_file, progress_callback=None):
    """Strip the audio track from *input_file*.  Returns *output_file*."""
    _ensure_ffmpeg()

    args = [
        "-i", input_file,
        "-c", "copy",
        "-an",
        output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


def extract_audio(input_file, output_file, progress_callback=None):
    """Extract the audio track to a separate file.  Returns *output_file*."""
    _ensure_ffmpeg()

    args = [
        "-i", input_file,
        "-vn",
        "-acodec", "copy",
        output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


def add_audio(video_file, audio_file, output_file, replace=True,
              progress_callback=None):
    """Add (or replace) the audio track of *video_file*.

    If *replace* is True the original audio is discarded; otherwise the
    new audio is mixed as an additional stream.  Returns *output_file*.
    """
    _ensure_ffmpeg()

    args = [
        "-i", video_file,
        "-i", audio_file,
    ]
    if replace:
        args += [
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
        ]
    else:
        args += [
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-map", "1:a:0",
            "-shortest",
        ]
    args.append(output_file)

    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


# ---------------------------------------------------------------------------
# Speed / format / codec
# ---------------------------------------------------------------------------

def change_speed(input_file, output_file, speed_factor,
                 progress_callback=None):
    """Change playback speed of *input_file* by *speed_factor*.

    A factor of 2.0 doubles the speed; 0.5 halves it.
    Returns *output_file*.
    """
    _ensure_ffmpeg()

    pts_factor = 1.0 / speed_factor
    video_filter = f"setpts={pts_factor}*PTS"

    # atempo only accepts values in [0.5, 100.0].  Chain multiple atempo
    # filters when the factor falls outside the single-filter range.
    atempo_filters = []
    remaining = speed_factor
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining}")
    audio_filter = ",".join(atempo_filters)

    args = [
        "-i", input_file,
        "-filter:v", video_filter,
        "-filter:a", audio_filter,
        output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


def convert_format(input_file, output_file, codec=None, bitrate=None,
                   progress_callback=None):
    """Convert *input_file* to a different format / codec.

    The target format is inferred from the *output_file* extension.
    Returns *output_file*.
    """
    _ensure_ffmpeg()

    args = ["-i", input_file]
    if codec:
        args += ["-c:v", codec]
    if bitrate:
        args += ["-b:v", str(bitrate)]
    args.append(output_file)

    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------

def extract_frames(input_file, output_dir, fps=None, format="png",
                   progress_callback=None):
    """Extract frames from *input_file* into *output_dir*.

    If *fps* is ``None`` every frame is extracted; otherwise frames are
    sampled at the given rate.  Returns a sorted list of extracted file
    paths.
    """
    _ensure_ffmpeg()

    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(input_file))[0]
    pattern = os.path.join(output_dir, f"{base}_%06d.{format}")

    args = ["-i", input_file]
    if fps is not None:
        args += ["-vf", f"fps={fps}"]
    args += [pattern]

    run_ffmpeg(args, progress_callback=progress_callback)

    # Collect the files that were written.
    extracted = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith(base + "_") and f.endswith(f".{format}")
    )
    return extracted


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def strip_metadata(input_file, output_file, progress_callback=None):
    """Remove ALL metadata from file including owner, computer info, GPS, EXIF, XMP."""
    _ensure_ffmpeg()

    args = [
        "-i", input_file,
        "-map_metadata", "-1",      # Strip global metadata
        "-map_metadata:s:v", "-1",  # Strip video stream metadata
        "-map_metadata:s:a", "-1",  # Strip audio stream metadata
        "-fflags", "+bitexact",     # Don't write encoder info
        "-flags:v", "+bitexact",    # Bitexact video flags
        "-flags:a", "+bitexact",    # Bitexact audio flags
        "-c", "copy",               # Stream copy (fast)
        "-y", output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


def strip_metadata_deep(input_file, output_file, progress_callback=None):
    """Deep metadata strip - re-encodes to guarantee complete removal of all
    metadata including owner info, computer name, GPS, EXIF, XMP, and any
    container-specific tags. Slower than strip_metadata but more thorough."""
    _ensure_ffmpeg()

    args = [
        "-i", input_file,
        "-map_metadata", "-1",
        "-map_metadata:s:v", "-1",
        "-map_metadata:s:a", "-1",
        "-map_chapters", "-1",       # Remove chapter metadata
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        "-movflags", "+faststart",   # For MP4: optimize for streaming
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k",
        "-y", output_file,
    ]
    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


def set_metadata(input_file, output_file, metadata_dict,
                 progress_callback=None):
    """Write metadata tags from *metadata_dict* into *output_file*.

    Returns *output_file*.
    """
    _ensure_ffmpeg()

    args = ["-i", input_file]
    for key, value in metadata_dict.items():
        args += ["-metadata", f"{key}={value}"]
    args += ["-c", "copy", output_file]

    run_ffmpeg(args, progress_callback=progress_callback)
    return output_file


# ---------------------------------------------------------------------------
# GIF creation
# ---------------------------------------------------------------------------

def create_gif(input_file, output_file, fps=10, width=480,
               progress_callback=None):
    """Convert *input_file* to an optimised GIF.

    A two-pass approach is used: first a palette is generated, then the
    GIF is rendered using that palette for better colour quality.
    Returns *output_file*.
    """
    _ensure_ffmpeg()

    fd, palette_path = tempfile.mkstemp(suffix=".png", prefix="smm_palette_")
    os.close(fd)

    filters = f"fps={fps},scale={width}:-1:flags=lanczos"

    try:
        # Pass 1 -- generate palette.
        args_palette = [
            "-i", input_file,
            "-vf", f"{filters},palettegen",
            "-y",
            palette_path,
        ]
        run_ffmpeg(args_palette, progress_callback=progress_callback)

        # Pass 2 -- render GIF with palette.
        args_gif = [
            "-i", input_file,
            "-i", palette_path,
            "-lavfi", f"{filters} [x]; [x][1:v] paletteuse",
            output_file,
        ]
        run_ffmpeg(args_gif, progress_callback=progress_callback)
    finally:
        if os.path.exists(palette_path):
            os.remove(palette_path)

    return output_file
