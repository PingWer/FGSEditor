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
    seconds = ticks / TICKS_PER_SECOND
    return round(seconds * fps)


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
