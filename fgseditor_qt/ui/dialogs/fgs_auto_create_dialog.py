from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from fgseditor_qt.math import fgs_optimizer
from fgseditor_qt.core import fgs_parser
from fgseditor_qt.tools import fgs_tools


def detect_denoise_accelerators() -> str:
    exe = fgs_tools.get_av_denoise_path()
    if not exe:
        return "cuda,vulkan"
    try:
        kwargs: dict = {"capture_output": True, "text": True, "timeout": 5}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        res = subprocess.run([exe, "list-devices"], **kwargs)
        if res.returncode == 0 and res.stdout:
            backends = []
            for line in res.stdout.splitlines():
                line_lower = line.lower()
                if "cuda" in line_lower and "cuda" not in backends:
                    backends.append("cuda")
                if "rocm" in line_lower and "rocm" not in backends:
                    backends.append("rocm")
                if "vulkan" in line_lower and "vulkan" not in backends:
                    backends.append("vulkan")
            if backends:
                return ",".join(backends)
    except Exception:
        pass
    return "cuda,vulkan"


class AutoCreateWorker(QThread):
    progress_updated = Signal(int, str)
    finished_data = Signal(bool, str, object)

    def __init__(
        self,
        original_video: str,
        av1_video: str | None,
        is_full_range: bool,
        ignore_chroma: bool,
        denoise_method: str = "nl4d",
        denoise_preset: str = "veryfast",
        denoise_mc: bool = True,
        denoise_channel: str = "luma",
        accelerators: str = "cuda,vulkan",
        is_444: bool = False,
        crop: str | None = None,
        scale: str | None = None,
        video_info: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.original_video = original_video
        self.av1_video = av1_video if av1_video and os.path.isfile(av1_video) else None
        self.is_full_range = is_full_range
        self.ignore_chroma = ignore_chroma
        self.denoise_method = denoise_method
        self.denoise_preset = denoise_preset
        self.denoise_mc = denoise_mc
        self.denoise_channel = denoise_channel
        self.accelerators = accelerators or "cuda,vulkan"
        self.is_444 = is_444
        self.crop = crop.strip() if crop else None
        self.scale = scale.strip() if scale else None
        self.video_info = video_info
        self._is_cancelled = False
        self._subprocesses: list[subprocess.Popen] = []

    def cancel(self):
        self._is_cancelled = True
        for p in self._subprocesses:
            try:
                p.kill()
            except Exception:
                pass

    def run(self):
        try:
            regrain_exe = fgs_tools.get_regrain_path()
            if not regrain_exe:
                self.finished_data.emit(
                    False,
                    "No FGS tool found.\n\n"
                    "Please check Settings.",
                    None,
                )
                return

            import tempfile
            import time
            temp_dir = tempfile.gettempdir()
            clean_base = "".join(c for c in os.path.basename(self.original_video) if c.isalnum() or c in "._-")
            temp_raw_tbl = os.path.join(
                temp_dir, f".tmp_auto_{os.getpid()}_{int(time.time())}_{clean_base}.tbl"
            )

            popen_flags: dict = (
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                if sys.platform == "win32"
                else {}
            )

            target_vid = self.av1_video or self.original_video
            v_info = self.video_info
            total_video_frames: int | None = None
            video_fps_detected: float | None = None

            if self.av1_video:
                self.progress_updated.emit(5, "Extracting grain diff against target video...")
                cmd_regrain = [
                    regrain_exe,
                    "diff",
                    self.original_video,
                    self.av1_video,
                    "-o",
                    temp_raw_tbl,
                    "--scan",
                    "full",
                    "--scene-threshold",
                    "0.5",
                    "--merge",
                    "0",
                    "--full-strength",
                    "-y",
                    "--progress",
                    "json",
                ]
                if self.crop:
                    cmd_regrain.extend(["--crop", self.crop])
                if self.scale:
                    cmd_regrain.extend(["--scale", self.scale])
                if self.ignore_chroma:
                    cmd_regrain.append("--no-chroma")

                p_regrain = subprocess.Popen(
                    cmd_regrain,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **popen_flags,
                )
                self._subprocesses = [p_regrain]

                regrain_lines: list[str] = []
                json_err_a: str | None = None
                for line in p_regrain.stdout:
                    if self._is_cancelled:
                        p_regrain.kill()
                        if os.path.exists(temp_raw_tbl):
                            try:
                                os.remove(temp_raw_tbl)
                            except OSError:
                                pass
                        self.finished_data.emit(False, "Operation cancelled by user.", None)
                        return
                    regrain_lines.append(line)
                    line_s = line.strip()
                    if line_s.startswith("{") and line_s.endswith("}"):
                        try:
                            d = json.loads(line_s)
                            ev = d.get("event")
                            if ev == "start":
                                self.progress_updated.emit(5, "Starting grain extraction...")
                            elif ev == "progress":
                                raw_pct = d.get("percent")
                                pct = float(raw_pct) if raw_pct is not None else 0.0
                                frames = d.get("frames", 0)
                                total = d.get("total")
                                fps = d.get("fps") or 0.0
                                if total is not None and total > 0:
                                    total_video_frames = total
                                if fps > 0:
                                    video_fps_detected = fps
                                stage = d.get("stage", "")
                                stage_desc = f"[{stage.capitalize()}] " if stage else ""
                                if total is not None:
                                    msg = f"{stage_desc}Extracting grain: {frames}/{total} frames ({pct:.1f}%)"
                                else:
                                    msg = f"{stage_desc}Extracting grain: {frames} frames"
                                if fps > 0:
                                    msg += f" @ {fps:.1f} fps"
                                self.progress_updated.emit(int(pct * 0.7), msg)
                            elif ev == "error":
                                json_err_a = f"[{d.get('code', 'error')}] {d.get('message', '')}"
                        except Exception:
                            pass

                rc = p_regrain.wait()
                if rc != 0:
                    if os.path.exists(temp_raw_tbl):
                        try:
                            os.remove(temp_raw_tbl)
                        except OSError:
                            pass
                    detail = json_err_a or "".join(regrain_lines[-10:]).strip()
                    self.finished_data.emit(
                        False, f"Diff extraction failed (exit code {rc}):\n{detail}", None
                    )
                    return

            else:
                denoise_exe = fgs_tools.get_av_denoise_path()
                if not denoise_exe:
                    self.finished_data.emit(
                        False,
                        "av-denoise executable not found.\nPlease install av-denoise or set its path in Settings.",
                        None,
                    )
                    return

                self.progress_updated.emit(5, "Denoising and extracting grain...")

                cmd_denoise = [
                    denoise_exe,
                    self.denoise_method,
                    "-i",
                    self.original_video,
                    "--preset",
                    self.denoise_preset,
                ]
                if self.denoise_method == "nl4d":
                    cmd_denoise.extend(["--lambda-ht-scale", "2.0", "--sigma-scale", "2.0"])
                elif self.denoise_method == "nlmeans":
                    if self.denoise_mc:
                        cmd_denoise.append("--motion-compensation")
                    cmd_denoise.extend(["--strength", "2.0", "--hq-sigma-scale", "2.0"])
                if self.denoise_channel in ("luma", "yuv"):
                    cmd_denoise.extend(["--channel-mode", self.denoise_channel])
                if self.accelerators:
                    cmd_denoise.extend(["--accelerators", self.accelerators])

                cmd_regrain = [
                    regrain_exe,
                    "diff",
                    self.original_video,
                    "-",
                    "-o",
                    temp_raw_tbl,
                    "--scan",
                    "full",
                    "--scene-threshold",
                    "0.5",
                    "--merge",
                    "0",
                    "--full-strength",
                    "-y",
                    "--progress",
                    "json",
                ]
                if self.ignore_chroma:
                    cmd_regrain.append("--no-chroma")

                p_ffmpeg = None
                if self.crop:
                    from fgseditor_qt.tools.video_probe import find_ffmpeg
                    ffmpeg_exe = find_ffmpeg() or "ffmpeg"
                    cmd_ffmpeg = [
                        ffmpeg_exe,
                        "-hide_banner",
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-i",
                        self.original_video,
                        "-vf",
                        f"crop={self.crop}",
                        "-f",
                        "yuv4mpegpipe",
                        "-strict",
                        "-1",
                        "-",
                    ]
                    if "-i" in cmd_denoise:
                        idx_i = cmd_denoise.index("-i")
                        cmd_denoise[idx_i + 1] = "-"
                    cmd_regrain.extend(["--crop", self.crop])

                    p_ffmpeg = subprocess.Popen(
                        cmd_ffmpeg,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        **popen_flags,
                    )
                    p_denoise = subprocess.Popen(
                        cmd_denoise,
                        stdin=p_ffmpeg.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        **popen_flags,
                    )
                    p_ffmpeg.stdout.close()
                    p_regrain = subprocess.Popen(
                        cmd_regrain,
                        stdin=p_denoise.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        **popen_flags,
                    )
                    p_denoise.stdout.close()
                    self._subprocesses = [p_ffmpeg, p_denoise, p_regrain]
                else:
                    p_denoise = subprocess.Popen(
                        cmd_denoise,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        **popen_flags,
                    )
                    p_regrain = subprocess.Popen(
                        cmd_regrain,
                        stdin=p_denoise.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        **popen_flags,
                    )
                    p_denoise.stdout.close()
                    self._subprocesses = [p_denoise, p_regrain]

                denoise_err_lines: list[str] = []
                import threading
                def _drain_stderr():
                    if p_denoise.stderr:
                        for err_line in p_denoise.stderr:
                            denoise_err_lines.append(err_line.decode("utf-8", errors="replace"))
                drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
                drain_thread.start()

                regrain_b_lines: list[str] = []
                json_err_b: str | None = None
                for line in p_regrain.stdout:
                    if self._is_cancelled:
                        for p in self._subprocesses:
                            try:
                                p.kill()
                            except Exception:
                                pass
                        if os.path.exists(temp_raw_tbl):
                            try:
                                os.remove(temp_raw_tbl)
                            except OSError:
                                pass
                        self.finished_data.emit(False, "Operation cancelled by user.", None)
                        return
                    regrain_b_lines.append(line)
                    line_s = line.strip()
                    if line_s.startswith("{") and line_s.endswith("}"):
                        try:
                            d = json.loads(line_s)
                            ev = d.get("event")
                            if ev == "start":
                                self.progress_updated.emit(5, "Starting denoising & extraction...")
                            elif ev == "progress":
                                raw_pct = d.get("percent")
                                pct = float(raw_pct) if raw_pct is not None else 0.0
                                frames = d.get("frames", 0)
                                total = d.get("total")
                                fps = d.get("fps") or 0.0
                                if total is not None and total > 0:
                                    total_video_frames = total
                                if fps > 0:
                                    video_fps_detected = fps
                                stage = d.get("stage", "")
                                stage_desc = f"[{stage.capitalize()}] " if stage else ""
                                if total is not None:
                                    msg = f"{stage_desc}Denoising & extracting: {frames}/{total} frames ({pct:.1f}%)"
                                else:
                                    msg = f"{stage_desc}Denoising & extracting: {frames} frames"
                                if fps > 0:
                                    msg += f" @ {fps:.1f} fps"
                                self.progress_updated.emit(int(pct * 0.7), msg)
                            elif ev == "error":
                                json_err_b = f"[{d.get('code', 'error')}] {d.get('message', '')}"
                        except Exception:
                            pass

                rc = p_regrain.wait()
                rc_denoise = p_denoise.wait()
                if p_ffmpeg:
                    p_ffmpeg.wait()
                drain_thread.join(timeout=2)
                if rc != 0 or rc_denoise != 0:
                    err_msg = "".join(denoise_err_lines).strip()
                    details = []
                    if err_msg:
                        details.append(f"av-denoise: {err_msg}")
                    if json_err_b:
                        details.append(f"Extraction error: {json_err_b}")
                    elif regrain_b_lines:
                        details.append(f"Extraction output: {''.join(regrain_b_lines[-10:]).strip()}")
                    detail = "\n".join(details) or f"Pipeline failed (extraction exit {rc}, denoise exit {rc_denoise})"
                    self.finished_data.emit(
                        False, f"Pipeline failed (extraction exit {rc}, denoise exit {rc_denoise}):\n{detail}", None
                    )
                    if os.path.exists(temp_raw_tbl):
                        try:
                            os.remove(temp_raw_tbl)
                        except OSError:
                            pass
                    return

            if not os.path.isfile(temp_raw_tbl):
                self.finished_data.emit(False, "Grain table file was not produced.", None)
                return

            self.progress_updated.emit(75, "Optimizing extracted grain table...")
            with open(temp_raw_tbl, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            headers, raw_events = fgs_parser.parse_fgs_events(content, return_warnings=False)
            if not raw_events:
                self.finished_data.emit(False, "No raw grain events were parsed from output.", None)
                return

            def _opt_progress(pct, msg):
                scaled_pct = 75 + int(pct * 0.23)
                self.progress_updated.emit(scaled_pct, msg)

            opt_events = fgs_optimizer.optimize_dynamic_fgs(
                raw_events,
                is_full_range=self.is_full_range,
                ignore_chroma=self.ignore_chroma,
                is_444=self.is_444,
                progress_cb=_opt_progress,
            )

            if opt_events:
                from fgseditor_qt.math import time_utils
                if v_info is None and target_vid and os.path.isfile(target_vid):
                    ext = os.path.splitext(target_vid)[1].lower()
                    if ext in {".mkv", ".mp4", ".ivf", ".webm", ".avi", ".mov", ".ts", ".flv", ".m4v", ".y4m", ".m2ts"}:
                        from fgseditor_qt.tools import video_probe
                        try:
                            v_info = video_probe.probe_video(target_vid)
                        except Exception:
                            v_info = None

                vid_ticks = 0
                if v_info:
                    try:
                        vid_ticks = time_utils.video_info_to_ticks(v_info)
                    except Exception:
                        vid_ticks = 0
                if vid_ticks <= 0 and total_video_frames and video_fps_detected:
                    vid_ticks = time_utils.frames_to_ticks(total_video_frames, video_fps_detected)

                if vid_ticks > 0:
                    trimmed = [ev for ev in opt_events if ev.get("start_time", 0) < vid_ticks]
                    if trimmed:
                        for ev in trimmed:
                            if ev.get("end_time", 0) > vid_ticks:
                                ev["end_time"] = vid_ticks
                        if trimmed[-1].get("end_time", 0) != vid_ticks:
                            trimmed[-1]["end_time"] = vid_ticks
                        for ev in trimmed:
                            params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                            ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                        opt_events = trimmed
                    elif opt_events:
                        ev = opt_events[0]
                        ev["start_time"] = 0
                        ev["end_time"] = vid_ticks
                        params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                        ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                        opt_events = [ev]

            opt_text = fgs_optimizer.build_optimized_fgs_text(opt_events, headers)

            with open(temp_raw_tbl, "w", encoding="utf-8", newline="\n") as f:
                f.write(opt_text)

            self.progress_updated.emit(100, "Done!")
            res = {
                "raw_count": len(raw_events),
                "opt_count": len(opt_events),
                "events": opt_events,
                "headers": headers,
                "text": opt_text,
                "tbl_path": temp_raw_tbl,
                "av1_video": self.av1_video,
                "original_video": self.original_video,
            }
            self.finished_data.emit(
                True,
                f"Extracted {len(raw_events)} raw events and optimized into {len(opt_events)} scenes.",
                res,
            )

        except Exception as e:
            self.finished_data.emit(False, str(e), None)


class FgsAutoCreateDialog(QDialog):
    fgs_loaded = Signal(str)

    def __init__(self, parent=None, initial_video_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Automatic FGS Creation & Optimization")
        self.setMinimumWidth(800)
        self.resize(840, 580)
        self.setStyleSheet(
            """
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #cccccc; font-size: 13px; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; font-weight: bold; color: #4da6ff; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit { background-color: #2b2b2b; color: #ffffff; border: 1px solid #555; border-radius: 4px; padding: 6px; }
            QPushButton { background-color: #333333; color: white; border: 1px solid #555; border-radius: 4px; padding: 6px 12px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #444444; }
            QPushButton:disabled { background-color: #222222; color: #666666; border: 1px solid #333; }
            QPushButton#primaryBtn { background-color: #007acc; border: 1px solid #0098ff; }
            QPushButton#primaryBtn:hover { background-color: #0098ff; }
            QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; background-color: #222; }
            QProgressBar::chunk { background-color: #007acc; }
            QRadioButton { color: #dddddd; font-size: 13px; spacing: 6px; }
            QRadioButton::indicator { width: 15px; height: 15px; }
            QCheckBox { color: #dddddd; font-size: 13px; spacing: 6px; }
            QCheckBox::indicator { width: 15px; height: 15px; }
            """
        )

        self._worker: AutoCreateWorker | None = None
        self._result_data: dict | None = None
        self._last_probed_orig: str | None = None
        self._last_probed_av1: str | None = None
        self._orig_probe_info: dict | None = None
        self._av1_probe_info: dict | None = None
        self._is_saved: bool = False
        self.setAcceptDrops(True)

        self._build_ui(initial_video_path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            event.acceptProposedAction()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".mkv", ".mp4", ".ivf", ".hevc", ".webm", ".avi", ".mov", ".ts", ".flv"):
                def _handle_drop(p):
                    if not self.orig_edit.text().strip():
                        self.orig_edit.setText(p)
                    else:
                        self.av1_edit.setText(p)

                QTimer.singleShot(0, lambda: _handle_drop(path))

    def _build_ui(self, initial_video_path: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        inputs_group = QGroupBox("Video Inputs")
        in_layout = QVBoxLayout(inputs_group)

        orig_lbl = QLabel("Source Video (with grain):*")
        in_layout.addWidget(orig_lbl)
        orig_row = QHBoxLayout()
        self.orig_edit = QLineEdit(initial_video_path)
        self.orig_edit.setPlaceholderText("Select source video...")
        self.orig_edit.textChanged.connect(self._check_resolutions_and_crop)
        orig_btn = QPushButton("Browse...")
        orig_btn.clicked.connect(self._browse_orig)
        orig_row.addWidget(self.orig_edit)
        orig_row.addWidget(orig_btn)
        in_layout.addLayout(orig_row)

        av1_lbl = QLabel("Clean Target Video (optional):")
        in_layout.addWidget(av1_lbl)
        av1_row = QHBoxLayout()
        self.av1_edit = QLineEdit()
        self.av1_edit.setPlaceholderText("Leave empty to denoise automatically")
        self.av1_edit.textChanged.connect(self._on_av1_path_changed)
        av1_btn = QPushButton("Browse...")
        av1_btn.clicked.connect(self._browse_av1)
        av1_row.addWidget(self.av1_edit)
        av1_row.addWidget(av1_btn)
        in_layout.addLayout(av1_row)

        crop_row = QHBoxLayout()
        self.crop_checkbox = QCheckBox("Crop / Letterbox:")
        self.crop_checkbox.setToolTip("Crop black bars before grain measurement (W:H:X:Y)")
        self.crop_edit = QLineEdit()
        self.crop_edit.setPlaceholderText("W:H:X:Y (e.g. 1920:816:0:132)")
        self.crop_edit.setEnabled(False)
        self.crop_detect_btn = QPushButton("Auto Detect")
        self.crop_detect_btn.setToolTip("Detect black bars in source video using FFmpeg")
        self.crop_detect_btn.clicked.connect(self._on_detect_crop_clicked)
        self.crop_checkbox.toggled.connect(self.crop_edit.setEnabled)
        self.crop_checkbox.toggled.connect(lambda _: self._check_resolutions_and_crop())

        crop_row.addWidget(self.crop_checkbox)
        crop_row.addWidget(self.crop_edit)
        crop_row.addWidget(self.crop_detect_btn)
        in_layout.addLayout(crop_row)

        scale_row = QHBoxLayout()
        self.scale_checkbox = QCheckBox("Scale Source:")
        self.scale_checkbox.setToolTip("Scale source with Lanczos after --crop for downscaled video (WIDTHxHEIGHT)")
        self.scale_edit = QLineEdit()
        self.scale_edit.setPlaceholderText("WIDTHxHEIGHT (e.g. 1920x1080)")
        self.scale_edit.setEnabled(False)
        self.scale_checkbox.toggled.connect(self.scale_edit.setEnabled)
        self.scale_checkbox.toggled.connect(lambda _: self._check_resolutions_and_crop())
        scale_row.addWidget(self.scale_checkbox)
        scale_row.addWidget(self.scale_edit)
        in_layout.addLayout(scale_row)

        self.crop_warning_label = QLabel()
        self.crop_warning_label.setStyleSheet(
            "color: #ffb84d; font-weight: bold; background: #332200; padding: 4px 8px; border-radius: 4px; border: 1px solid #664400;"
        )
        self.crop_warning_label.setWordWrap(True)
        self.crop_warning_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crop_warning_label.setToolTip("Click to apply suggested crop")
        self.crop_warning_label.mousePressEvent = lambda _: self.crop_checkbox.setChecked(True)
        self.crop_warning_label.hide()
        in_layout.addWidget(self.crop_warning_label)

        layout.addWidget(inputs_group)

        self.denoise_group = QGroupBox("Denoiser Settings")
        d_layout = QVBoxLayout(self.denoise_group)
        d_layout.setSpacing(10)

        row_algo = QHBoxLayout()
        lbl_algo = QLabel("Algorithm:")
        lbl_algo.setStyleSheet("font-weight: bold; min-width: 90px; color: #ffffff;")
        row_algo.addWidget(lbl_algo)
        self.radio_nl4d = QRadioButton("nl4d")
        self.radio_nlmeans = QRadioButton("nlmeans")
        self.radio_nl4d.setChecked(True)
        self.group_algo = QButtonGroup(self)
        self.group_algo.addButton(self.radio_nl4d)
        self.group_algo.addButton(self.radio_nlmeans)
        row_algo.addWidget(self.radio_nl4d)
        row_algo.addWidget(self.radio_nlmeans)
        row_algo.addSpacing(25)

        lbl_preset = QLabel("Preset:")
        lbl_preset.setStyleSheet("font-weight: bold; min-width: 50px; color: #ffffff;")
        row_algo.addWidget(lbl_preset)
        self.radio_veryfast = QRadioButton("veryfast")
        self.radio_fast = QRadioButton("fast")
        self.radio_veryfast.setChecked(True)
        self.group_preset = QButtonGroup(self)
        self.group_preset.addButton(self.radio_veryfast)
        self.group_preset.addButton(self.radio_fast)
        row_algo.addWidget(self.radio_veryfast)
        row_algo.addWidget(self.radio_fast)
        row_algo.addStretch(1)
        d_layout.addLayout(row_algo)

        row_chan = QHBoxLayout()
        lbl_chan = QLabel("Channel Mode:")
        lbl_chan.setStyleSheet("font-weight: bold; min-width: 90px; color: #ffffff;")
        row_chan.addWidget(lbl_chan)
        self.radio_luma = QRadioButton("luma")
        self.radio_yuv = QRadioButton("yuv")
        self.radio_luma.setChecked(True)
        self.group_chan = QButtonGroup(self)
        self.group_chan.addButton(self.radio_luma)
        self.group_chan.addButton(self.radio_yuv)
        row_chan.addWidget(self.radio_luma)
        row_chan.addWidget(self.radio_yuv)
        row_chan.addSpacing(25)

        self.check_mc = QCheckBox("Motion Compensation (MC)")
        self.check_mc.setChecked(True)
        row_chan.addWidget(self.check_mc)
        row_chan.addStretch(1)
        d_layout.addLayout(row_chan)

        self.edit_accel = QLineEdit(detect_denoise_accelerators())
        self.edit_accel.setVisible(False)

        self.denoise_note = QLabel(
            "Denoising is enabled: no clean target provided."
        )
        self.denoise_note.setStyleSheet("color: #888888; font-size: 11px;")
        d_layout.addWidget(self.denoise_note)

        layout.addWidget(self.denoise_group)

        opt_group = QGroupBox("Optimizer Settings")
        opt_layout = QHBoxLayout(opt_group)

        self.radio_limited = QRadioButton("Limited Range (16-235)")
        self.radio_limited.setChecked(True)
        self.radio_full = QRadioButton("Full Range (0-255)")
        opt_layout.addWidget(self.radio_limited)
        opt_layout.addWidget(self.radio_full)

        self.check_ignore_chroma = QCheckBox("Ignore Chroma (Luma only)")
        self.check_ignore_chroma.setChecked(True)
        opt_layout.addWidget(self.check_ignore_chroma)

        layout.addWidget(opt_group)

        prog_group = QGroupBox("Status")
        p_layout = QVBoxLayout(prog_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        p_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        p_layout.addWidget(self.status_label)

        layout.addWidget(prog_group)

        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Creation")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setMinimumWidth(130)
        self.start_btn.clicked.connect(self._start_pipeline)
        btn_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_pipeline)
        btn_layout.addWidget(self.cancel_btn)

        btn_layout.addStretch()

        self.open_editor_btn = QPushButton("Open in Editor")
        self.open_editor_btn.setMinimumWidth(120)
        self.open_editor_btn.setEnabled(False)
        self.open_editor_btn.clicked.connect(self._open_in_editor)
        btn_layout.addWidget(self.open_editor_btn)

        self.save_tbl_btn = QPushButton("Save FGS...")
        self.save_tbl_btn.setMinimumWidth(110)
        self.save_tbl_btn.setEnabled(False)
        self.save_tbl_btn.clicked.connect(self._save_fgs)
        btn_layout.addWidget(self.save_tbl_btn)

        self.save_apply_btn = QPushButton("Save & Apply...")
        self.save_apply_btn.setMinimumWidth(130)
        self.save_apply_btn.setEnabled(False)
        self.save_apply_btn.clicked.connect(self._save_and_apply)
        btn_layout.addWidget(self.save_apply_btn)

        layout.addLayout(btn_layout)
        self._check_resolutions_and_crop()

    def _browse_orig(self):
        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Input Video",
            get_dialog_dir("last_video_dir"),
            "Video Files (*.mkv *.mp4 *.ivf *.avi *.webm *.mov *.ts);;All Files (*.*)",
        )
        if path:
            update_dialog_dir("last_video_dir", path)
            self.orig_edit.setText(path)

    def _browse_av1(self):
        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Clean / Denoised AV1 Video Target",
            get_dialog_dir("last_video_dir"),
            "Video Files (*.mkv *.mp4 *.ivf *.webm);;All Files (*.*)",
        )
        if path:
            update_dialog_dir("last_video_dir", path)
            self.av1_edit.setText(path)

    def _on_av1_path_changed(self, text: str):
        clean = text.strip().strip('"').strip("'")
        has_av1 = bool(clean and os.path.isfile(clean))
        if has_av1:
            self.denoise_group.setEnabled(False)
            self.denoise_note.setText(
                "Denoising disabled: Clean target supplied. Running direct diff."
            )
            self.denoise_note.setStyleSheet("color: #4da6ff; font-size: 11px;")
        else:
            self.denoise_group.setEnabled(True)
            self.denoise_note.setText(
                "Denoising is enabled: no clean target provided."
            )
            self.denoise_note.setStyleSheet("color: #888888; font-size: 11px;")
        self._check_resolutions_and_crop()

    def _check_resolutions_and_crop(self):
        orig_video = self.orig_edit.text().strip().strip('"').strip("'")
        av1_video = self.av1_edit.text().strip().strip('"').strip("'")

        if not orig_video or not os.path.isfile(orig_video) or not av1_video or not os.path.isfile(av1_video):
            self.crop_warning_label.hide()
            return

        from fgseditor_qt.tools import video_probe
        if not video_probe.find_ffprobe():
            self.crop_warning_label.hide()
            return

        try:
            if not self._orig_probe_info or self._last_probed_orig != orig_video:
                self._orig_probe_info = video_probe.probe_video(orig_video)
                self._last_probed_orig = orig_video
            if not self._av1_probe_info or self._last_probed_av1 != av1_video:
                self._av1_probe_info = video_probe.probe_video(av1_video)
                self._last_probed_av1 = av1_video

            info1 = self._orig_probe_info
            info2 = self._av1_probe_info
            w1, h1 = info1.get("width"), info1.get("height")
            w2, h2 = info2.get("width"), info2.get("height")

            if w1 and w2 and h1 and h2 and (w1 != w2 or h1 != h2):
                crop_val = None
                scale_val = None

                is_pure_downscale = (w1 > w2 and h1 > h2 and abs((w1 / h1) - (w2 / h2)) < 0.02)

                if is_pure_downscale:
                    scale_val = f"{w2}x{h2}"
                    if not self.scale_edit.text().strip():
                        self.scale_edit.setText(scale_val)

                    if self.scale_checkbox.isChecked():
                        self.crop_warning_label.hide()
                    else:
                        self.crop_warning_label.setText(
                            f"⚠️ Video resolutions differ ({w1}x{h1} vs {w2}x{h2}). Apply scale: {scale_val}"
                        )
                        self.crop_warning_label.mousePressEvent = lambda _: self.scale_checkbox.setChecked(True)
                        self.crop_warning_label.show()
                    return

                if w1 == w2 and h1 > h2:
                    y = (h1 - h2) // 2
                    crop_val = f"{w2}:{h2}:0:{y}"
                elif h1 == h2 and w1 > w2:
                    x = (w1 - w2) // 2
                    crop_val = f"{w2}:{h2}:{x}:0"
                elif w1 >= w2 and h1 >= h2:
                    aspect_target = w2 / h2
                    expected_h1 = int(round(w1 / aspect_target))
                    if expected_h1 < h1:
                        y = (h1 - expected_h1) // 2
                        crop_val = f"{w1}:{expected_h1}:0:{y}"
                        scale_val = f"{w2}x{h2}"
                    else:
                        x = (w1 - w2) // 2
                        y = (h1 - h2) // 2
                        crop_val = f"{w2}:{h2}:{x}:{y}"
                        scale_val = f"{w2}x{h2}"

                if crop_val and not self.crop_edit.text().strip():
                    self.crop_edit.setText(crop_val)
                if scale_val and not self.scale_edit.text().strip():
                    self.scale_edit.setText(scale_val)

                if self.crop_checkbox.isChecked() or (self.scale_checkbox.isChecked() and not crop_val):
                    self.crop_warning_label.hide()
                else:
                    self.crop_warning_label.setText(
                        f"⚠️ Video resolutions differ ({w1}x{h1} vs {w2}x{h2}). Apply crop: {crop_val}"
                        if crop_val
                        else f"⚠️ Video resolutions differ ({w1}x{h1} vs {w2}x{h2}). Please apply a crop."
                    )
                    self.crop_warning_label.mousePressEvent = lambda _: self.crop_checkbox.setChecked(True)
                    self.crop_warning_label.show()
            else:
                self.crop_warning_label.hide()
        except Exception:
            self.crop_warning_label.hide()

    def _on_detect_crop_clicked(self):
        orig_video = self.orig_edit.text().strip().strip('"').strip("'")
        if not orig_video or not os.path.isfile(orig_video):
            QMessageBox.warning(self, "Auto Detect Crop", "Please select a valid source video first.")
            return

        from fgseditor_qt.tools import video_probe
        if not video_probe.find_ffmpeg():
            QMessageBox.warning(self, "Auto Detect Crop", "FFmpeg is required for automatic crop detection.")
            return

        self.status_label.setText("Detecting black bars...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dur = 0.0
            if video_probe.find_ffprobe():
                info = video_probe.probe_video(orig_video)
                dur = float(info.get("duration_s", 0.0) or info.get("duration", 0.0))
            detected = video_probe.detect_crop_parameters(orig_video, duration_s=dur)
            if detected:
                self.crop_checkbox.setChecked(True)
                self.crop_edit.setText(detected)
                self.status_label.setText(f"Detected crop: {detected}")
            else:
                self.status_label.setText("No black bars detected.")
                QMessageBox.information(self, "Auto Detect Crop", "No black bars detected in the source video.")
        finally:
            QApplication.restoreOverrideCursor()

    @property
    def combo_method(self):
        class _MethodProxy:
            def __init__(self, dlg): self.dlg = dlg
            def currentText(self): return "nl4d" if self.dlg.radio_nl4d.isChecked() else "nlmeans"
        return _MethodProxy(self)

    @property
    def combo_preset(self):
        class _PresetProxy:
            def __init__(self, dlg): self.dlg = dlg
            def currentText(self): return "veryfast" if self.dlg.radio_veryfast.isChecked() else "fast"
        return _PresetProxy(self)

    @property
    def combo_channel(self):
        class _ChannelProxy:
            def __init__(self, dlg): self.dlg = dlg
            def currentText(self): return "luma" if self.dlg.radio_luma.isChecked() else "yuv"
        return _ChannelProxy(self)

    def _start_pipeline(self):
        orig_video = self.orig_edit.text().strip().strip('"').strip("'")
        if not orig_video or not os.path.isfile(orig_video):
            QMessageBox.warning(self, "Invalid Input", "Please specify a valid source video.")
            return

        av1_video = self.av1_edit.text().strip().strip('"').strip("'")
        if av1_video and not os.path.isfile(av1_video):
            QMessageBox.warning(
                self, "Invalid Input", "The target video does not exist."
            )
            return

        crop = self.crop_edit.text().strip() if self.crop_checkbox.isChecked() else None
        if crop:
            parts = crop.split(":")
            if len(parts) != 4 or not all(p.isdigit() for p in parts):
                QMessageBox.warning(
                    self,
                    "Invalid Crop",
                    "Crop format must be W:H:X:Y (e.g. 1920:816:0:132).",
                )
                return

        scale = self.scale_edit.text().strip() if self.scale_checkbox.isChecked() else None
        if scale:
            if "x" not in scale.lower():
                QMessageBox.warning(
                    self,
                    "Invalid Scale",
                    "Scale format must be WIDTHxHEIGHT (e.g. 1920x1080).",
                )
                return
            sp = scale.lower().split("x")
            if len(sp) != 2 or not all(p.isdigit() for p in sp):
                QMessageBox.warning(
                    self,
                    "Invalid Scale",
                    "Scale format must be WIDTHxHEIGHT (e.g. 1920x1080).",
                )
                return

        from fgseditor_qt.tools import video_probe
        if crop and not av1_video:
            if not video_probe.find_ffmpeg():
                QMessageBox.warning(
                    self,
                    "FFmpeg Required",
                    "FFmpeg is required to crop single video input on-the-fly.",
                )
                return

        is_444 = False
        try:
            if video_probe.find_ffprobe():
                if not self._orig_probe_info or self._last_probed_orig != orig_video:
                    self._orig_probe_info = video_probe.probe_video(orig_video)
                    self._last_probed_orig = orig_video
                orig_info = self._orig_probe_info
                is_444 = bool(orig_info.get("is_444", False))
                if av1_video:
                    if not self._av1_probe_info or self._last_probed_av1 != av1_video:
                        self._av1_probe_info = video_probe.probe_video(av1_video)
                        self._last_probed_av1 = av1_video
                    av1_info = self._av1_probe_info
                    w1, h1 = orig_info.get("width"), orig_info.get("height")
                    w2, h2 = av1_info.get("width"), av1_info.get("height")
                    if w1 and w2 and (w1 != w2 or h1 != h2):
                        eff_w, eff_h = w1, h1
                        if crop:
                            cw, ch, _, _ = map(int, crop.split(":"))
                            eff_w, eff_h = cw, ch
                        if scale:
                            sw, sh = map(int, scale.lower().split("x"))
                            eff_w, eff_h = sw, sh

                        if (eff_w, eff_h) != (w2, h2):
                            QMessageBox.critical(
                                self,
                                "Resolution Mismatch",
                                f"Resolution mismatch:\nSource: {w1}x{h1}\nTarget: {w2}x{h2}\n\n"
                                "Diff extraction requires matching dimensions. Please enable and specify a Crop or Scale Source.",
                            )
                            return
                    elif crop:
                        cw, ch, _, _ = map(int, crop.split(":"))
                        if cw != w2 or ch != h2:
                            QMessageBox.critical(
                                self,
                                "Crop Mismatch",
                                f"Crop dimensions ({cw}x{ch}) do not match clean target ({w2}x{h2}).",
                            )
                            return

                    if av1_info.get("codec") and av1_info.get("codec") != "av1":
                        QMessageBox.warning(
                            self,
                            "Invalid Codec",
                            f"Target codec is '{av1_info.get('codec')}', not 'av1'.\n"
                            "Film grain synthesis requires an AV1 stream.",
                        )
                        return
        except Exception:
            pass

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_editor_btn.setEnabled(False)
        self.save_tbl_btn.setEnabled(False)
        self.save_apply_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Initializing worker...")

        self._worker = AutoCreateWorker(
            original_video=orig_video,
            av1_video=av1_video if av1_video else None,
            is_full_range=self.radio_full.isChecked(),
            ignore_chroma=self.check_ignore_chroma.isChecked(),
            denoise_method=self.combo_method.currentText(),
            denoise_preset=self.combo_preset.currentText(),
            denoise_mc=self.check_mc.isChecked(),
            denoise_channel=self.combo_channel.currentText(),
            accelerators=self.edit_accel.text().strip() or detect_denoise_accelerators(),
            is_444=is_444,
            crop=crop,
            scale=scale,
            video_info=(self._av1_probe_info if av1_video else self._orig_probe_info) or self._orig_probe_info or self._av1_probe_info,
            parent=self,
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.finished_data.connect(self._on_finished)
        self._worker.start()

    def _cancel_pipeline(self):
        if self._worker:
            self.status_label.setText("Cancelling...")
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)

    def _on_finished(self, success: bool, msg: str, data: object):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if not success:
            self.status_label.setText(f"Failed: {msg}")
            QMessageBox.critical(self, "Creation Failed", msg)
            return

        self._result_data = data if isinstance(data, dict) else None
        self._is_saved = False
        self.status_label.setText(msg)
        self.progress_bar.setValue(100)

        self.open_editor_btn.setEnabled(True)
        self.save_tbl_btn.setEnabled(True)

        has_av1 = bool(self._result_data and self._result_data.get("av1_video"))
        self.save_apply_btn.setEnabled(has_av1)

        QMessageBox.information(self, "Creation Complete", msg)

    def _open_in_editor(self):
        if not self._result_data:
            return
        tbl_path = self._result_data.get("tbl_path")
        if tbl_path and os.path.isfile(tbl_path):
            self._opened_in_editor = True
            self._is_saved = True
            self.fgs_loaded.emit(tbl_path)
            self.accept()

    def _save_fgs(self) -> bool:
        if not self._result_data:
            return False
        tbl_path = self._result_data.get("tbl_path")
        if not tbl_path or not os.path.isfile(tbl_path):
            return False

        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir
        default_out = os.path.join(get_dialog_dir("last_fgs_dir"), "grain.tbl")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Optimized Film Grain Table", default_out, "Film Grain Table (*.tbl *.txt)"
        )
        if out_path:
            update_dialog_dir("last_fgs_dir", out_path)
            try:
                shutil.copy2(tbl_path, out_path)
                self._is_saved = True
                QMessageBox.information(
                    self, "Saved Successfully", f"Optimized FGS saved to:\n{out_path}"
                )
                return True
            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))
                return False
        return False

    def _save_and_apply(self):
        if not self._result_data:
            return
        tbl_path = self._result_data.get("tbl_path")
        av1_video = self._result_data.get("av1_video")
        if not tbl_path or not av1_video:
            QMessageBox.warning(
                self,
                "Cannot Apply",
                "Cannot apply film grain: no AV1 target video was provided.",
            )
            return

        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir
        src_base = os.path.splitext(os.path.basename(av1_video))[0]
        default_out = os.path.join(get_dialog_dir("last_video_dir"), f"{src_base}_with_fgs.mkv")

        out_video, _ = QFileDialog.getSaveFileName(
            self,
            "Save Grain-Injected AV1 Video",
            default_out,
            "Video Files (*.mkv *.ivf *.webm *.mp4)",
        )
        if not out_video:
            return

        if os.path.abspath(out_video) == os.path.abspath(av1_video):
            QMessageBox.warning(
                self,
                "Invalid Output Video",
                "The output video path cannot be the same as the source video.",
            )
            return

        update_dialog_dir("last_video_dir", out_video)

        self.status_label.setText("Injecting film grain into AV1 stream...")

        def _apply_prog(pct: float, msg: str):
            self.progress_bar.setValue(int(pct))
            self.status_label.setText(msg)

        ok, res_msg = fgs_tools.apply_fgs(
            video_path=av1_video,
            grain_file=tbl_path,
            output_path=out_video,
            is_static=False,
            progress_callback=_apply_prog,
        )
        if ok:
            self._is_saved = True
            self.progress_bar.setValue(100)
            self.status_label.setText(f"Applied successfully to {out_video}")
            QMessageBox.information(self, "Application Complete", res_msg)
        else:
            self.status_label.setText("Application failed.")
            QMessageBox.critical(self, "Apply Error", res_msg)

    def closeEvent(self, event):
        if not self.isVisible():
            event.accept()
            return

        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Operation?",
                "Creation in progress.\nCancel and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._worker.cancel()
                self._worker.wait(2000)
                event.accept()
            else:
                event.ignore()
                return

        if self._result_data and not getattr(self, "_is_saved", False):
            reply = QMessageBox.question(
                self,
                "Unsaved Output",
                "Save created film grain table before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                saved = self._save_fgs()
                if saved or getattr(self, "_is_saved", False):
                    event.accept()
                else:
                    event.ignore()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

        if event.isAccepted() and not getattr(self, "_opened_in_editor", False):
            tbl_path = self._result_data.get("tbl_path") if self._result_data else None
            if tbl_path and os.path.isfile(tbl_path):
                try:
                    os.remove(tbl_path)
                except OSError:
                    pass

    def reject(self):
        self.close()
