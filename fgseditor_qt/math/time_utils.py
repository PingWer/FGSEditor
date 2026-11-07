COMMON_FPS: list[tuple[str, float]] = [
    ("23.976", 24000 / 1001),
    ("24", 24.0),
    ("25", 25.0),
    ("29.97", 30000 / 1001),
    ("30", 30.0),
    ("50", 50.0),
    ("59.94", 60000 / 1001),
    ("60", 60.0),
]

DEFAULT_FPS_LABEL = "23.976"
TICKS_PER_SECOND = 10_000_000  # 10^7 ticks = 1 second
MAX_QT_INT = 2_147_483_647  # Max for 32-bit signed int


def fps_from_label(label: str) -> float:
    for lbl, val in COMMON_FPS:
        if lbl == label:
            return val
    return float(label)


def ticks_to_frames(ticks: int, fps: float) -> int:
    return int((ticks * fps + TICKS_PER_SECOND / 2) // TICKS_PER_SECOND)


def frames_to_ticks(frames: int, fps: float) -> int:
    seconds = frames / fps
    return round(seconds * TICKS_PER_SECOND)


def ticks_to_seconds(ticks: int) -> float:
    return ticks / TICKS_PER_SECOND


def seconds_to_ticks(seconds: float) -> int:
    return round(seconds * TICKS_PER_SECOND)


def ticks_to_timecode(ticks: int) -> str:
    total_ms = ticks // 10_000  # 10^7 ticks/s → 10^3 ms/s
    ms = total_ms % 1_000
    total_s = total_ms // 1_000
    secs = total_s % 60
    total_m = total_s // 60
    mins = total_m % 60
    hours = total_m // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}:{ms:03d}"
    

def timecode_to_ticks(tc: str) -> int:
    """Converts HH:MM:SS:mmm back to ticks (10^-7 seconds)."""
    try:
        parts = tc.split(":")
        if len(parts) != 4:
            return 0
        h, m, s, ms = map(int, parts)
        total_ms = (h * 3600 + m * 60 + s) * 1000 + ms
        return total_ms * 10_000
    except ValueError:
        return 0


def find_closest_fps_label(target_fps: float) -> str | None:
    best_label = None
    best_diff = float("inf")
    for label, value in COMMON_FPS:
        diff = abs(value - target_fps)
        if diff < best_diff:
            best_diff = diff
            best_label = label
    # Only accept if within 0.5%
    if best_label and target_fps > 0 and best_diff / target_fps < 0.005:
        return best_label
    return None


def video_info_to_ticks(video_info: dict | None, fps: float | None = None) -> int:
    """Calculate the total duration of a video in ticks from video_info."""
    if not video_info:
        return 0
    try:
        num_frames = int(video_info.get("num_frames") or 0)
    except (ValueError, TypeError):
        num_frames = 0
    try:
        dur = float(video_info.get("duration_s") or 0.0)
    except (ValueError, TypeError):
        dur = 0.0

    try:
        fps_num = int(video_info.get("fps_num") or 0)
        fps_den = int(video_info.get("fps_den") or 0)
    except (ValueError, TypeError):
        fps_num, fps_den = 0, 0

    if num_frames > 0 and fps_num > 0 and fps_den > 0 and fps is None:
        seconds = (num_frames * fps_den) / fps_num
        return round(seconds * TICKS_PER_SECOND)

    effective_fps = fps or video_info.get("fps") or 0.0
    try:
        effective_fps = float(effective_fps)
    except (ValueError, TypeError):
        effective_fps = 0.0

    if num_frames > 0 and effective_fps > 0:
        return frames_to_ticks(num_frames, effective_fps)
    elif dur > 0:
        return seconds_to_ticks(dur)
    return 0
