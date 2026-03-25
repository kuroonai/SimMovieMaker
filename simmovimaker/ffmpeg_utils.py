"""
FFmpeg detection, validation, and wrapper functions.

Handles locating ffmpeg/ffprobe executables on Windows systems,
caching found paths, and running ffmpeg/ffprobe subprocesses
with optional progress reporting.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path


class FFmpegNotFoundError(Exception):
    """Raised when ffmpeg or ffprobe cannot be found on the system."""
    pass


# Module-level cache for discovered paths. None means "not yet searched";
# an empty string means "searched but not found".
_ffmpeg_path_cache = None
_ffprobe_path_cache = None

# Common installation directories on Windows (without the trailing executable
# name). Each entry should point to a directory that directly contains the
# ffmpeg.exe / ffprobe.exe binaries.
_COMMON_WINDOWS_DIRS = [
    r"C:\ffmpeg\bin",
    r"C:\ffmpeg",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\Program Files\ffmpeg",
    r"C:\Program Files (x86)\ffmpeg\bin",
    r"C:\Program Files (x86)\ffmpeg",
    os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin"),
    os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg"),
    os.path.expandvars(r"%USERPROFILE%\ffmpeg\bin"),
    os.path.expandvars(r"%USERPROFILE%\ffmpeg"),
]


def _search_executable(name: str) -> str | None:
    """Search for an executable by *name* (e.g. 'ffmpeg') on PATH and in
    common Windows locations.

    Returns the absolute path to the executable, or ``None`` if it cannot be
    found.
    """
    # 1. Try the system PATH via shutil.which (fastest, most portable).
    path = shutil.which(name)
    if path is not None:
        return str(Path(path).resolve())

    # 2. Walk through well-known Windows directories.
    exe_name = f"{name}.exe"
    for directory in _COMMON_WINDOWS_DIRS:
        candidate = os.path.join(directory, exe_name)
        if os.path.isfile(candidate):
            return str(Path(candidate).resolve())

    return None


def find_ffmpeg() -> str | None:
    """Locate the ffmpeg executable.

    The result is cached after the first call so repeated invocations are
    essentially free.  Returns the absolute path or ``None``.
    """
    global _ffmpeg_path_cache
    if _ffmpeg_path_cache is None:
        result = _search_executable("ffmpeg")
        _ffmpeg_path_cache = result if result else ""
    return _ffmpeg_path_cache or None


def find_ffprobe() -> str | None:
    """Locate the ffprobe executable.

    The result is cached after the first call so repeated invocations are
    essentially free.  Returns the absolute path or ``None``.
    """
    global _ffprobe_path_cache
    if _ffprobe_path_cache is None:
        result = _search_executable("ffprobe")
        _ffprobe_path_cache = result if result else ""
    return _ffprobe_path_cache or None


def _get_version(ffmpeg_path: str) -> str:
    """Return the version string reported by ffmpeg, or an empty string on
    failure."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = result.stdout.strip().splitlines()[0]
        # Typical first line: "ffmpeg version 6.0-full_build ..."
        return first_line
    except Exception:
        return ""


def check_ffmpeg() -> dict:
    """Check ffmpeg/ffprobe availability and return a status dictionary.

    Returns a dict with keys:
        available   -- bool, True if both ffmpeg and ffprobe were found
        ffmpeg_path -- str or None
        ffprobe_path -- str or None
        version     -- str, the first line of ``ffmpeg -version`` output
    """
    ffmpeg_path = find_ffmpeg()
    ffprobe_path = find_ffprobe()
    version = ""
    if ffmpeg_path:
        version = _get_version(ffmpeg_path)

    return {
        "available": bool(ffmpeg_path and ffprobe_path),
        "ffmpeg_path": ffmpeg_path,
        "ffprobe_path": ffprobe_path,
        "version": version,
    }


# Regex to capture the time= field from ffmpeg stderr progress lines.
# Example: "frame=  120 fps= 30 ... time=00:00:04.00 ..."
_TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})")


def _parse_time_seconds(match: re.Match) -> float:
    """Convert a ``time=HH:MM:SS.cc`` regex match to total seconds."""
    hours, minutes, seconds, centiseconds = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0


def run_ffmpeg(args: list[str], progress_callback=None) -> subprocess.CompletedProcess:
    """Run ffmpeg with the given argument list.

    Parameters
    ----------
    args : list[str]
        Arguments to pass to ffmpeg (do NOT include the ffmpeg executable
        itself; it will be prepended automatically).
    progress_callback : callable, optional
        A function accepting a single float argument (0.0 -- 100.0)
        representing encoding progress.  Progress is estimated from the
        ``time=`` lines that ffmpeg writes to stderr, so a total duration
        must be determinable from the input for percentages to be meaningful.
        If the duration cannot be determined, the callback will not be
        invoked.

    Returns
    -------
    subprocess.CompletedProcess

    Raises
    ------
    FFmpegNotFoundError
        If ffmpeg cannot be located.
    """
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path is None:
        raise FFmpegNotFoundError(
            "ffmpeg was not found on this system.\n\n" + get_ffmpeg_help_text()
        )

    cmd = [ffmpeg_path] + list(args)

    # If no progress callback, just run and return.
    if progress_callback is None:
        return subprocess.run(cmd, capture_output=True, text=True)

    # With a progress callback we need to stream stderr line-by-line.
    # First, try to figure out the total duration from the args (look for
    # an input file and probe it).
    total_duration = _estimate_duration(args)
    collected_stderr: list[str] = []

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # ffmpeg writes progress to stderr.  It uses \r for in-place updates so
    # we read character-by-character and split on \r or \n.
    line_buf = []
    while True:
        ch = process.stderr.read(1)
        if not ch:
            break
        if ch in ("\r", "\n"):
            line = "".join(line_buf)
            line_buf = []
            collected_stderr.append(line)
            if total_duration and total_duration > 0:
                match = _TIME_RE.search(line)
                if match:
                    current = _parse_time_seconds(match)
                    percent = min(current / total_duration * 100.0, 100.0)
                    progress_callback(percent)
        else:
            line_buf.append(ch)

    process.wait()

    stdout_data = process.stdout.read() if process.stdout else ""

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=process.returncode,
        stdout=stdout_data,
        stderr="\n".join(collected_stderr),
    )


def _estimate_duration(args: list[str]) -> float | None:
    """Try to determine the total duration (in seconds) of the first input
    file referenced in *args*.

    Returns ``None`` if the duration cannot be determined.
    """
    ffprobe_path = find_ffprobe()
    if ffprobe_path is None:
        return None

    # Find the first -i <file> pair in the argument list.
    input_file = None
    for i, arg in enumerate(args):
        if arg == "-i" and i + 1 < len(args):
            input_file = args[i + 1]
            break

    if input_file is None:
        return None

    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_file,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def run_ffprobe(args: list[str]) -> str:
    """Run ffprobe with the given argument list and return its stdout.

    Parameters
    ----------
    args : list[str]
        Arguments to pass to ffprobe (do NOT include the ffprobe executable
        itself; it will be prepended automatically).

    Returns
    -------
    str
        The captured stdout output.

    Raises
    ------
    FFmpegNotFoundError
        If ffprobe cannot be located.
    subprocess.CalledProcessError
        If ffprobe exits with a non-zero return code.
    """
    ffprobe_path = find_ffprobe()
    if ffprobe_path is None:
        raise FFmpegNotFoundError(
            "ffprobe was not found on this system.\n\n" + get_ffmpeg_help_text()
        )

    cmd = [ffprobe_path] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    result.check_returncode()
    return result.stdout


def get_ffmpeg_help_text() -> str:
    """Return a human-readable string with installation instructions for
    Windows users."""
    return (
        "FFmpeg is required but was not found on this system.\n"
        "\n"
        "Installation options for Windows:\n"
        "\n"
        "  1. Download a pre-built release from https://www.gyan.dev/ffmpeg/builds/\n"
        "     - Grab the 'ffmpeg-release-essentials' zip.\n"
        "     - Extract it so that ffmpeg.exe and ffprobe.exe are located at\n"
        "       C:\\ffmpeg\\bin\\ffmpeg.exe (and ...\\ffprobe.exe).\n"
        "\n"
        "  2. Install via Chocolatey (if available):\n"
        "       choco install ffmpeg\n"
        "\n"
        "  3. Install via winget:\n"
        "       winget install Gyan.FFmpeg\n"
        "\n"
        "After installation, either:\n"
        "  - Add the folder containing ffmpeg.exe to your system PATH, or\n"
        "  - Place the binaries in C:\\ffmpeg\\bin\\ (this tool checks that\n"
        "    location automatically).\n"
        "\n"
        "Then restart this application."
    )
