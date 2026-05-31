from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction

from .app_paths import get_base_dir


def find_ffprobe() -> str | None:
    from .settings_manager import get_setting
    user_path = get_setting("ffprobe_path", "").strip()
    if user_path and os.path.isfile(user_path) and os.access(user_path, os.X_OK):
        return user_path

    base = get_base_dir()
    if sys.platform == "win32":
        candidates = ["ffprobe.exe"]
    else:
        candidates = ["ffprobe"]

    for name in candidates:
        path = os.path.join(base, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which("ffprobe")
    if found:
        return found

    return None


def find_ffmpeg() -> str | None:
    from .settings_manager import get_setting
    user_path = get_setting("ffmpeg_path", "").strip()
    if user_path and os.path.isfile(user_path) and os.access(user_path, os.X_OK):
        return user_path

    base = get_base_dir()
    if sys.platform == "win32":
        candidates = ["ffmpeg.exe"]
    else:
        candidates = ["ffmpeg"]

    for name in candidates:
        path = os.path.join(base, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which("ffmpeg")
    if found:
        return found

    return None


def get_ffmpeg_version() -> str | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode != 0:
            return None

        first_line = result.stdout.splitlines()[0]
        parts = first_line.split()
        if (
            len(parts) < 3
            or parts[0].lower() != "ffmpeg"
            or parts[1].lower() != "version"
        ):
            return None

        return parts[2]
    except Exception:
        return None


def check_ffmpeg_version(min_version: str = "8.0.0") -> bool:
    version_str = get_ffmpeg_version()
    if not version_str:
        return False
    if version_str.startswith("N-"):
        return True

    def parse_v(v):
        v = v.split("-")[0]
        parts = []
        for x in v.split("."):
            try:
                parts.append(int(x))
            except ValueError:
                break
        return parts

    v_actual = parse_v(version_str)
    v_min = parse_v(min_version)

    max_len = max(len(v_actual), len(v_min))
    v_actual += [0] * (max_len - len(v_actual))
    v_min += [0] * (max_len - len(v_min))

    return v_actual >= v_min


def probe_video(filepath: str) -> dict:
    if not check_ffmpeg_version():
        raise RuntimeError(
            "ffmpeg version is too old.\n\n"
            "Please install at least FFmpeg 8.0 (which includes ffprobe) "
            "and ensure it is in your system PATH, or place the ffprobe binary "
            "next to the FGSEditor executable."
        )
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise FileNotFoundError(
            "ffprobe not found.\n\n"
            "Please install FFmpeg (which includes ffprobe) and ensure it is "
            "in your system PATH, or place the ffprobe binary next to the "
            "FGSEditor executable."
        )

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in (".mkv", ".ivf", ".mp4", ".hevc"):
        raise ValueError(
            f"Unsupported file format: '{ext}'\nOnly .mkv, .ivf, .mp4, and .hevc files are accepted."
        )

    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        filepath,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Could not execute ffprobe at: {ffprobe}\n"
            "The binary may be missing or not executable."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe timed out while probing the video file.")

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no output)"
        raise RuntimeError(f"ffprobe failed (exit code {result.returncode}):\n{stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON:\n{exc}")

    video_stream = _find_video_stream(data)
    if video_stream is None:
        raise ValueError("No video stream found in the file.")

    codec = (video_stream.get("codec_name") or "").lower()

    if ext == ".mkv" and codec not in ("av1", "hevc"):
        raise ValueError(
            f"The MKV file contains '{codec}' video.\n"
            "Only AV1 or HEVC video is supported."
        )

    width = _safe_int(video_stream.get("width"), 0)
    height = _safe_int(video_stream.get("height"), 0)

    fps_num, fps_den, fps = _parse_frame_rate(video_stream)

    duration_s = _parse_duration(video_stream, data)

    num_frames = _parse_frame_count(video_stream, duration_s, fps)

    return {
        "codec": codec,
        "width": width,
        "height": height,
        "fps": fps,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "duration_s": duration_s,
        "num_frames": num_frames,
    }


def _find_video_stream(data: dict) -> dict | None:
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_fraction(text: str) -> tuple[int, int]:
    if not text or text == "0/0":
        return 0, 1
    try:
        frac = Fraction(text)
        return frac.numerator, frac.denominator
    except (ValueError, ZeroDivisionError):
        return 0, 1


def _parse_frame_rate(stream: dict) -> tuple[int, int, float]:
    for key in ("r_frame_rate", "avg_frame_rate"):
        raw = stream.get(key, "")
        if raw and raw != "0/0":
            num, den = _parse_fraction(raw)
            if num > 0 and den > 0:
                return num, den, num / den

    return 0, 1, 0.0


def _parse_duration(stream: dict, data: dict) -> float:
    dur = _safe_float(stream.get("duration"))
    if dur > 0:
        return dur

    fmt = data.get("format", {})
    dur = _safe_float(fmt.get("duration"))
    if dur > 0:
        return dur

    tags = stream.get("tags", {})
    dur_str = tags.get("DURATION") or tags.get("duration") or ""
    if dur_str:
        parsed = _parse_duration_tag(dur_str)
        if parsed > 0:
            return parsed

    fmt_tags = fmt.get("tags", {})
    dur_str = fmt_tags.get("DURATION") or fmt_tags.get("duration") or ""
    if dur_str:
        parsed = _parse_duration_tag(dur_str)
        if parsed > 0:
            return parsed

    return 0.0


def _parse_duration_tag(text: str) -> float:
    text = text.strip()
    if not text:
        return 0.0

    try:
        parts = text.split(":")
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60 + s
    except (ValueError, IndexError):
        pass

    return 0.0


def _parse_frame_count(stream: dict, duration_s: float, fps: float) -> int:
    nb = _safe_int(stream.get("nb_frames"))
    if nb > 0:
        return nb

    nb = _safe_int(stream.get("nb_read_frames"))
    if nb > 0:
        return nb

    if duration_s > 0 and fps > 0:
        return round(duration_s * fps)

    return 0
