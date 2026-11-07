from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Callable

from fgseditor_qt.core.app_paths import get_base_dir, find_executable, NO_WINDOW_FLAG
from fgseditor_qt.core.settings_manager import get_setting


def _get_staging_dir(fallback_path: str) -> str:
    base = get_base_dir()
    if os.access(base, os.W_OK):
        return base
    fallback_dir = os.path.dirname(os.path.abspath(fallback_path))
    if os.access(fallback_dir, os.W_OK):
        return fallback_dir
    import tempfile
    return tempfile.gettempdir()


def _normalize_cli_path(path: str) -> str:
    p = path.strip().strip('"').strip("'")
    if sys.platform == "win32" and len(p) >= 240 and not p.startswith("\\\\?\\") and os.path.isabs(p):
        return "\\\\?\\" + os.path.normpath(p)
    return p


def get_regrain_path() -> str | None:
    return find_executable("regrain", "regrain_path")


def get_grav1synth_path() -> str | None:
    return find_executable("grav1synth", "grav1synth_path")


def get_av_denoise_path() -> str | None:
    return find_executable("av-denoise", "av_denoise_path")


def get_preferred_tool() -> str | None:
    pref = get_setting("preferred_backend", "regrain")
    if pref == "grav1synth":
        if get_grav1synth_path() is not None:
            return "grav1synth"
        if get_regrain_path() is not None:
            return "regrain"
    else:
        if get_regrain_path() is not None:
            return "regrain"
        if get_grav1synth_path() is not None:
            return "grav1synth"
    return None


def detect_backend() -> str | None:
    return get_preferred_tool()


def is_tool_available() -> bool:
    return get_preferred_tool() is not None


def get_active_tool_path() -> tuple[str, str] | tuple[None, None]:
    pref = get_setting("preferred_backend", "regrain")
    if pref == "grav1synth":
        g1s = get_grav1synth_path()
        if g1s is not None:
            return "grav1synth", g1s
        rg = get_regrain_path()
        if rg is not None:
            return "regrain", rg
    else:
        rg = get_regrain_path()
        if rg is not None:
            return "regrain", rg
        g1s = get_grav1synth_path()
        if g1s is not None:
            return "grav1synth", g1s
    return None, None


def _run_with_streaming(
    args: list[str],
    progress_callback: Callable[[float, str], None] | None = None,
    timeout: int = 600,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[int, str, str]:
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if NO_WINDOW_FLAG:
        kwargs["creationflags"] = NO_WINDOW_FLAG

    proc = subprocess.Popen(args, **kwargs)
    stdout_lines: list[str] = []

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_check and cancel_check():
                proc.kill()
                proc.communicate()
                return -2, "".join(stdout_lines), "Operation cancelled by user."
            stdout_lines.append(line)
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    ev = data.get("event")
                    if ev == "start" and progress_callback is not None:
                        cmd = data.get("command", "")
                        cmd_name = f" {cmd}" if cmd else ""
                        progress_callback(0.0, f"Starting{cmd_name}...")
                    elif ev == "progress" and progress_callback is not None:
                        raw_pct = data.get("percent")
                        pct = float(raw_pct) if raw_pct is not None else 0.0
                        frames = data.get("frames", 0)
                        total = data.get("total")
                        fps = data.get("fps") or 0.0
                        stage = data.get("stage", "")

                        if stage == "read":
                            stage_desc = "Reading"
                        elif stage == "write":
                            stage_desc = "Writing grain"
                        elif stage == "verify":
                            stage_desc = "Verifying with dav1d"
                        elif stage:
                            stage_desc = stage.capitalize()
                        else:
                            stage_desc = "Processing"

                        if total is not None:
                            msg = f"{stage_desc}: {frames}/{total} frames ({pct:.1f}%)"
                        else:
                            msg = f"{stage_desc}: {frames} frames"

                        if fps > 0:
                            msg += f" @ {fps:.1f} fps"
                        progress_callback(pct, msg)
                    elif ev == "summary" and progress_callback is not None:
                        entries = data.get("entries")
                        frames = data.get("frames")
                        cmd = data.get("command", "")
                        if entries is not None:
                            msg = f"Completed: {entries} grain table entries created ({frames or 0} frames)."
                        elif cmd:
                            msg = f"Completed {cmd} successfully ({frames or 0} frames)."
                        else:
                            msg = f"Completed successfully ({frames or 0} frames)."
                        progress_callback(100.0, msg)
                except Exception:
                    pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return -1, "".join(stdout_lines), "Command timed out."
    except Exception as e:
        proc.kill()
        proc.communicate()
        return -1, "".join(stdout_lines), str(e)
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass

    return proc.returncode, "".join(stdout_lines), ""


def inspect_fgs(
    video_path: str,
    output_txt: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> bool:
    video_path = _normalize_cli_path(video_path)
    output_txt = _normalize_cli_path(output_txt)

    pref = get_preferred_tool()
    if pref is None:
        raise FileNotFoundError(
            "No FGS tool found.\n\n"
            "Please check Settings."
        )

    if pref == "regrain":
        exe = get_regrain_path()
        assert exe is not None
        args = [exe, "export", "--progress", "json", "-y", "--output", output_txt, video_path]
        rc, stdout, stderr = _run_with_streaming(args, progress_callback)
        if rc != 0:
            combined = (stdout + " " + stderr).lower()
            if any(p in combined for p in ["accesso negato", "os error 5", "access is denied", "permission denied"]):
                staging_file = os.path.join(_get_staging_dir(output_txt), f".tmp_export_{os.getpid()}_{os.path.basename(output_txt)}")
                stage_args = [exe, "export", "--progress", "json", "-y", "--output", staging_file, video_path]
                rc, stdout, stderr = _run_with_streaming(stage_args, progress_callback)
                if rc == 0 and os.path.isfile(staging_file):
                    shutil.move(staging_file, output_txt)
                else:
                    if os.path.exists(staging_file):
                        try:
                            os.remove(staging_file)
                        except OSError:
                            pass
            combined = (stdout + " " + stderr).lower()
            if rc != 0:
                if any(p in combined for p in ["no grain", "no_grain", "no film grain", "0 entries", "entries\":0", "entries\": 0", "not an av1", "unsupported_input", "no_frames"]):
                    return False
                raise RuntimeError(f"regrain export failed (exit {rc}):\n{stderr or stdout}")

        if not os.path.isfile(output_txt):
            return False

        try:
            with open(output_txt, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            has_events = any(line.startswith("E ") for line in content.splitlines())
            if not has_events:
                try:
                    os.remove(output_txt)
                except OSError:
                    pass
                return False
            return True
        except OSError:
            return False

    else:
        exe = get_grav1synth_path()
        assert exe is not None

        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "timeout": 300,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if NO_WINDOW_FLAG:
            kwargs["creationflags"] = NO_WINDOW_FLAG
        res = subprocess.run([exe, "inspect", "-o", output_txt, "-y", video_path], **kwargs)
        if res.returncode != 0:
            combined = (res.stdout or "").strip().lower()
            if any(p in combined for p in ["no film grain", "no grain", "not found", "does not contain", "no fgs"]):
                return False
            if not os.path.isfile(output_txt):
                return False
            raise RuntimeError(f"grav1synth inspect failed (exit {res.returncode}):\n{res.stdout}")

        if not os.path.isfile(output_txt):
            return False
        return os.path.getsize(output_txt) > 0


def apply_fgs(
    video_path: str,
    grain_file: str | None = None,
    output_path: str = "",
    is_static: bool = False,
    progress_callback: Callable[[float, str], None] | None = None,
    grain_txt: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    raw_tbl = grain_file or grain_txt
    if not raw_tbl:
        return False, "No grain table path provided."

    table_path = _normalize_cli_path(raw_tbl)
    video_path = _normalize_cli_path(video_path)
    output_path = _normalize_cli_path(output_path)

    pref = get_preferred_tool()
    if pref is None:
        return False, (
            "No FGS tool found.\n\n"
            "Please check Settings."
        )

    clean_table_path = table_path
    tmp_clean_table = None
    staging_file = None
    success = False

    try:
        if os.path.isfile(table_path):
            with open(table_path, "r", encoding="utf-8", errors="replace") as f:
                tbl_lines = f.readlines()
            filmgrn_idx = None
            for idx, line in enumerate(tbl_lines):
                if line.strip().lower() == "filmgrn1":
                    filmgrn_idx = idx
                    break
            if filmgrn_idx is not None and filmgrn_idx > 0:
                import tempfile
                fd, tmp_clean_table = tempfile.mkstemp(prefix="clean_fgs_", suffix=".tbl")
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as clean_f:
                    clean_f.writelines(tbl_lines[filmgrn_idx:])
                clean_table_path = _normalize_cli_path(tmp_clean_table)
    except Exception:
        pass

    try:
        if pref == "regrain":
            exe = get_regrain_path()
            assert exe is not None
            args = [exe, "apply", "--progress", "json", "-y", "--table", clean_table_path, "--output", output_path]
            if is_static:
                args.append("--static-grain")
            args.append(video_path)

            rc, stdout, stderr = _run_with_streaming(args, progress_callback, timeout=600, cancel_check=cancel_check)
            if rc == -2:
                return False, "Operation cancelled by user."
            if rc != 0:
                combined = (stdout + " " + stderr).lower()
                if any(p in combined for p in ["accesso negato", "os error 5", "access is denied", "permission denied"]):
                    staging_file = os.path.join(_get_staging_dir(output_path), f".tmp_apply_{os.getpid()}_{os.path.basename(output_path)}")
                    stage_args = [exe, "apply", "--progress", "json", "-y", "--table", clean_table_path, "--output", staging_file]
                    if is_static:
                        stage_args.append("--static-grain")
                    stage_args.append(video_path)
                    rc, stdout, stderr = _run_with_streaming(stage_args, progress_callback, timeout=600, cancel_check=cancel_check)
                    if rc == -2:
                        return False, "Operation cancelled by user."
                    if rc == 0 and os.path.isfile(staging_file):
                        shutil.move(staging_file, output_path)
                    else:
                        if os.path.exists(staging_file):
                            try:
                                os.remove(staging_file)
                            except OSError:
                                pass
                if rc != 0:
                    msg = (stderr or stdout).strip()
                    return False, f"regrain apply failed (exit {rc}):\n{msg}"
            if not os.path.isfile(output_path):
                return False, "regrain apply finished but the output file was not created."
            success = True
            return True, f"Video saved to: {output_path}"

        else:
            exe = get_grav1synth_path()
            assert exe is not None

            from fgseditor_qt.tools.video_probe import find_ffmpeg
            ffmpeg_exe = find_ffmpeg()
            is_mkv = video_path.lower().endswith(".mkv") and output_path.lower().endswith(".mkv")

            target_out = output_path
            if ffmpeg_exe and is_mkv:
                staging_file = os.path.join(_get_staging_dir(output_path), f".tmp_grav_{os.getpid()}_{os.path.basename(output_path)}")
                target_out = _normalize_cli_path(staging_file)

            args = [exe, "apply"]
            if is_static:
                args.append("--strict")
            args.extend(["-g", clean_table_path, "-o", target_out, "-y", "--replace", video_path])

            kwargs: dict = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if NO_WINDOW_FLAG:
                kwargs["creationflags"] = NO_WINDOW_FLAG

            proc = subprocess.Popen(args, **kwargs)
            try:
                import time
                while proc.poll() is None:
                    if cancel_check and cancel_check():
                        proc.kill()
                        proc.communicate()
                        return False, "Operation cancelled by user."
                    time.sleep(0.05)
                stdout_out, _ = proc.communicate(timeout=10)
            except Exception as e:
                proc.kill()
                proc.communicate()
                return False, f"grav1synth execution error: {e}"

            if proc.returncode != 0:
                msg = (stdout_out or "(no output)").strip()
                return False, f"grav1synth apply failed (exit {proc.returncode}):\n{msg}"
            if not os.path.isfile(target_out):
                return False, "grav1synth finished but the output file was not created."

            if staging_file and os.path.isfile(staging_file):
                if progress_callback:
                    progress_callback(90.0, "Remuxing audio, subtitles, and metadata with FFmpeg...")
                ff_args = [
                    ffmpeg_exe,
                    "-y",
                    "-i", target_out,
                    "-i", video_path,
                    "-map", "0:v",
                    "-map", "1:a?",
                    "-map", "1:s?",
                    "-map", "1:t?",
                    "-map_chapters", "1",
                    "-c", "copy",
                    output_path,
                ]
                ff_proc = subprocess.Popen(ff_args, **kwargs)
                try:
                    while ff_proc.poll() is None:
                        if cancel_check and cancel_check():
                            ff_proc.kill()
                            ff_proc.communicate()
                            return False, "Operation cancelled by user."
                        time.sleep(0.05)
                    ff_out, _ = ff_proc.communicate(timeout=30)
                except Exception as e:
                    ff_proc.kill()
                    ff_proc.communicate()
                    return False, f"FFmpeg remux error: {e}"

                if ff_proc.returncode != 0:
                    msg = (ff_out or "(no output)").strip()
                    return False, f"FFmpeg remux failed (exit {ff_proc.returncode}):\n{msg}"
                if not os.path.isfile(output_path):
                    return False, "FFmpeg remux finished but output file was not created."

            success = True
            return True, f"Video saved to: {output_path}"
    finally:
        if tmp_clean_table and os.path.isfile(tmp_clean_table):
            try:
                os.remove(tmp_clean_table)
            except OSError:
                pass
        if staging_file and os.path.isfile(staging_file):
            try:
                os.remove(staging_file)
            except OSError:
                pass
        if not success and output_path and output_path != video_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


def remove_fgs(
    video_path: str,
    output_path: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> tuple[bool, str]:
    video_path = _normalize_cli_path(video_path)
    output_path = _normalize_cli_path(output_path)

    pref = get_preferred_tool()
    if pref is None:
        return False, (
            "No FGS tool found.\n\n"
            "Please check Settings."
        )

    if pref == "regrain":
        exe = get_regrain_path()
        assert exe is not None
        args = [exe, "remove", "--progress", "json", "-y", "--output", output_path, video_path]
        rc, stdout, stderr = _run_with_streaming(args, progress_callback, timeout=600)
        if rc != 0:
            combined = (stdout + " " + stderr).lower()
            if any(p in combined for p in ["accesso negato", "os error 5", "access is denied", "permission denied"]):
                staging_file = os.path.join(_get_staging_dir(output_path), f".tmp_remove_{os.getpid()}_{os.path.basename(output_path)}")
                stage_args = [exe, "remove", "--progress", "json", "-y", "--output", staging_file, video_path]
                rc, stdout, stderr = _run_with_streaming(stage_args, progress_callback, timeout=600)
                if rc == 0 and os.path.isfile(staging_file):
                    shutil.move(staging_file, output_path)
                else:
                    if os.path.exists(staging_file):
                        try:
                            os.remove(staging_file)
                        except OSError:
                            pass
            if rc != 0:
                msg = (stderr or stdout).strip()
                return False, f"regrain remove failed (exit {rc}):\n{msg}"
        if not os.path.isfile(output_path):
            return False, "regrain remove finished but the output file was not created."
        return True, f"Video saved to: {output_path}"

    else:
        exe = get_grav1synth_path()
        assert exe is not None
        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "timeout": 600,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if NO_WINDOW_FLAG:
            kwargs["creationflags"] = NO_WINDOW_FLAG
        res = subprocess.run([exe, "remove", "-o", output_path, "-y", video_path], **kwargs)
        if res.returncode != 0:
            msg = (res.stdout or "").strip()
            return False, f"grav1synth remove failed (exit {res.returncode}):\n{msg}"
        if not os.path.isfile(output_path):
            return False, "grav1synth finished but the output file was not created."
        return True, f"Video saved to: {output_path}"
