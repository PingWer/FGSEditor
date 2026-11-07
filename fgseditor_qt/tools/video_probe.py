from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction

from fgseditor_qt.core.app_paths import find_executable, NO_WINDOW_FLAG


def find_ffprobe() -> str | None:
    return find_executable("ffprobe", "ffprobe_path")


def find_ffmpeg() -> str | None:
    return find_executable("ffmpeg", "ffmpeg_path")


def get_ffmpeg_version() -> str | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    try:
        run_kwargs: dict = {"capture_output": True}
        if sys.platform == "win32" and NO_WINDOW_FLAG:
            run_kwargs["creationflags"] = NO_WINDOW_FLAG
        result = subprocess.run([ffmpeg, "-version"], **run_kwargs)
        if result.returncode != 0:
            return None

        stdout_str = result.stdout.decode("utf-8", errors="replace")
        first_line = stdout_str.splitlines()[0]
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


def check_ffmpeg_version(min_version: str = "5.0.0") -> bool:
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
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise FileNotFoundError(
            "ffprobe not found.\n\n"
            "Please install FFmpeg (which includes ffprobe) and ensure it is "
            "in your system PATH, or place the ffprobe binary next to the "
            "FGSEditor executable."
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
        run_kwargs: dict = {"capture_output": True, "timeout": 30}
        if sys.platform == "win32" and NO_WINDOW_FLAG:
            run_kwargs["creationflags"] = NO_WINDOW_FLAG
        result = subprocess.run(cmd, **run_kwargs)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Could not execute ffprobe at: {ffprobe}\n"
            "The binary may be missing or not executable."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe timed out while probing the video file.")

    if result.returncode != 0:
        stderr_str = result.stderr.decode("utf-8", errors="replace").strip() if result.stderr else "(no output)"
        raise RuntimeError(f"ffprobe failed (exit code {result.returncode}):\n{stderr_str}")

    try:
        stdout_str = result.stdout.decode("utf-8", errors="replace")
        data = json.loads(stdout_str)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON:\n{exc}")

    video_stream = _find_video_stream(data)
    if video_stream is None:
        raise ValueError("No video stream found in the file.")

    codec = (video_stream.get("codec_name") or "").lower()
    pix_fmt = (video_stream.get("pix_fmt") or "").lower()
    is_444 = "444" in pix_fmt

    width = _safe_int(video_stream.get("width"), 0)
    height = _safe_int(video_stream.get("height"), 0)

    fps_num, fps_den, fps = _parse_frame_rate(video_stream)

    duration_s = _parse_duration(video_stream, data)

    num_frames = _parse_frame_count(video_stream, duration_s, fps)

    return {
        "codec": codec,
        "pix_fmt": pix_fmt,
        "is_444": is_444,
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


def detect_crop_parameters(video_path: str, duration_s: float = 0.0) -> str | None:
    import re
    from collections import Counter

    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe or not os.path.isfile(video_path):
        return None

    all_crops: list[str] = []

    sample_points: list[str] = []
    if duration_s > 120:
        sample_points = ["60", "120", "30"]
    elif duration_s > 30:
        sample_points = [str(int(duration_s * 0.3)), str(int(duration_s * 0.6))]
    elif duration_s > 5:
        sample_points = ["2"]
    else:
        sample_points = ["0"]

    for ss in sample_points:
        cmd = [
            ffmpeg_exe,
            "-hide_banner",
            "-nostdin",
            "-ss",
            ss,
            "-i",
            video_path,
            "-vframes",
            "15",
            "-vf",
            "cropdetect=round=2:reset=1",
            "-f",
            "null",
            "-",
        ]
        try:
            run_kwargs: dict = {"capture_output": True, "text": True, "timeout": 10}
            if sys.platform == "win32" and NO_WINDOW_FLAG:
                run_kwargs["creationflags"] = NO_WINDOW_FLAG
            res = subprocess.run(cmd, **run_kwargs)
            matches = re.findall(r"crop=([0-9]+:[0-9]+:[0-9]+:[0-9]+)", res.stderr)
            if matches:
                all_crops.extend(matches)
                break
        except Exception:
            pass

    if not all_crops:
        return None

    return Counter(all_crops).most_common(1)[0][0]
