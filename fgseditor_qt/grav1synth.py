from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .app_paths import get_base_dir


def get_grav1synth_path() -> str | None:
    base = get_base_dir()
    if sys.platform == "win32":
        candidates = ["grav1synth.exe"]
    else:
        candidates = ["grav1synth"]

    for name in candidates:
        path = os.path.join(base, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    found = shutil.which("grav1synth")
    if found:
        return found

    return None


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    kwargs = dict(
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(args, **kwargs)


def inspect_fgs(video_path: str, output_txt: str) -> bool:
    """
    Run ``grav1synth inspect`` to extract the FGS table from a video.

    Args:
        video_path:  Path to the input AV1 video.
        output_txt:  Path where the extracted FGS .txt will be written.

    Returns:
        True if FGS was found and extracted, False if no FGS in the video.

    Raises:
        FileNotFoundError: grav1synth binary not found.
        RuntimeError:      Unexpected error from grav1synth.
    """
    exe = get_grav1synth_path()
    if exe is None:
        raise FileNotFoundError(
            "grav1synth not found.\n\n"
            "Place the grav1synth binary next to the FGSEditor executable "
            "or ensure it is in your system PATH."
        )

    result = _run([exe, "inspect", "-o", output_txt, "-y", video_path])

    if result.returncode != 0:
        stderr = (result.stderr or "").strip().lower()
        stdout = (result.stdout or "").strip().lower()
        combined = stderr + " " + stdout

        if any(
            phrase in combined
            for phrase in [
                "no film grain",
                "no grain",
                "not found",
                "does not contain",
                "no fgs",
            ]
        ):
            return False

        # If output file was not created, assume no grain
        if not os.path.isfile(output_txt):
            return False

        raise RuntimeError(
            f"grav1synth inspect failed (exit {result.returncode}):\n"
            f"{result.stderr or result.stdout or '(no output)'}"
        )

    if not os.path.isfile(output_txt):
        return False

    try:
        size = os.path.getsize(output_txt)
    except OSError:
        return False

    return size > 0


def apply_fgs(
    video_path: str,
    grain_txt: str,
    output_path: str,
) -> tuple[bool, str]:
    """
    Run ``grav1synth apply`` to write film grain into a video.

    Args:
        video_path:  Path to the input AV1 video.
        grain_txt:   Path to the FGS table .txt file.
        output_path: Path for the output video.

    Returns:
        (success: bool, message: str)
    """
    exe = get_grav1synth_path()
    if exe is None:
        return False, (
            "grav1synth not found.\n\n"
            "Place the grav1synth binary next to the FGSEditor executable "
            "or ensure it is in your system PATH."
        )

    result = _run(
        [exe, "apply", "-g", grain_txt, "-o", output_path, "-y", video_path],
        timeout=600,
    )

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "(no output)").strip()
        return False, f"grav1synth apply failed (exit {result.returncode}):\n{msg}"

    if not os.path.isfile(output_path):
        return False, "grav1synth finished but the output file was not created."

    return True, f"Video saved to: {output_path}"


# Not used yet, but could be useful in the future
def remove_fgs(
    video_path: str,
    output_path: str,
) -> tuple[bool, str]:
    """
    Run ``grav1synth remove`` to strip all film grain from a video.

    Args:
        video_path:  Path to the input AV1 video.
        output_path: Path for the output video.

    Returns:
        (success: bool, message: str)
    """
    exe = get_grav1synth_path()
    if exe is None:
        return False, (
            "grav1synth not found.\n\n"
            "Place the grav1synth binary next to the FGSEditor executable "
            "or ensure it is in your system PATH."
        )

    result = _run(
        [exe, "remove", "-o", output_path, "-y", video_path],
        timeout=600,
    )

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "(no output)").strip()
        return False, f"grav1synth remove failed (exit {result.returncode}):\n{msg}"

    if not os.path.isfile(output_path):
        return False, "grav1synth finished but the output file was not created."

    return True, f"Video saved to: {output_path}"
