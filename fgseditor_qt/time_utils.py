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
