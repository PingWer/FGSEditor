from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QStackedWidget,
    QFrame,
)
from PySide6.QtCore import Signal

from .utils import section_label
from ..time_utils import (
    COMMON_FPS,
    DEFAULT_FPS_LABEL,
    fps_from_label,
    frames_to_ticks,
    ticks_to_frames,
    ticks_to_seconds,
    seconds_to_ticks,
    ticks_to_timecode,
    timecode_to_ticks,
    find_closest_fps_label,
    MAX_QT_INT,
    TICKS_PER_SECOND,
)


class PanelTime(QWidget):
    time_changed = Signal(object, object)

    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        self._suppress = False
        self._video_info: dict | None = None

        self._start_ticks: int = 0
        self._end_ticks: int = 100_000_000
        self._min_allowed_ticks: int = 0
        self._max_allowed_ticks: int = 1000 * 3600 * TICKS_PER_SECOND

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        layout.addWidget(section_label("EVENT TIME"))

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("FPS:"))
        self._fps_combo = QComboBox()
        for lbl, _ in COMMON_FPS:
            self._fps_combo.addItem(lbl)
        self._fps_combo.setCurrentText(DEFAULT_FPS_LABEL)
        self._fps_combo.currentTextChanged.connect(self._on_fps_changed)
        fps_row.addWidget(self._fps_combo, stretch=1)
        layout.addLayout(fps_row)

        self._all_duration_chk = QCheckBox("All video duration")
        self._all_duration_chk.setToolTip(
            "Set start to 0 and end to the full video duration"
        )
        self._all_duration_chk.setEnabled(False)  # Disabled until a video is loaded
        self._all_duration_chk.toggled.connect(self._on_all_duration_toggled)
        layout.addWidget(self._all_duration_chk)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._rb_frames = QRadioButton("Frames")
        self._rb_seconds = QRadioButton("Seconds")
        self._rb_timecode = QRadioButton("Timecode")
        self._rb_frames.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self._rb_frames, 0)
        grp.addButton(self._rb_seconds, 1)
        grp.addButton(self._rb_timecode, 2)
        mode_row.addWidget(self._rb_frames)
        mode_row.addWidget(self._rb_seconds)
        mode_row.addWidget(self._rb_timecode)
        layout.addLayout(mode_row)

        # Stacked pages
        self._stack = QStackedWidget()
        grp.idClicked.connect(self._stack.setCurrentIndex)

        page_frames = QWidget()
        pf = QVBoxLayout(page_frames)
        pf.setContentsMargins(0, 4, 0, 4)
        self._start_frame = QSpinBox()
        self._start_frame.setMinimum(0)
        self._start_frame.setMaximum(99_999_999)
        self._start_frame.setValue(0)
        self._start_frame.valueChanged.connect(self._on_frame_start_changed)
        pf.addLayout(self._row("Start frame:", self._start_frame))
        self._end_frame = QSpinBox()
        self._end_frame.setMinimum(0)
        self._end_frame.setMaximum(99_999_999)
        self._end_frame.setValue(240)
        self._end_frame.valueChanged.connect(self._on_frame_end_changed)
        pf.addLayout(self._row("End frame:", self._end_frame))
        self._stack.addWidget(page_frames)

        page_secs = QWidget()
        ps = QVBoxLayout(page_secs)
        ps.setContentsMargins(0, 4, 0, 4)
        self._start_sec = QDoubleSpinBox()
        self._start_sec.setDecimals(4)
        self._start_sec.setMinimum(0.0)
        self._start_sec.setMaximum(99_999.0)
        self._start_sec.setValue(0.0)
        self._start_sec.valueChanged.connect(self._on_sec_start_changed)
        ps.addLayout(self._row("Start (s):", self._start_sec))
        self._end_sec = QDoubleSpinBox()
        self._end_sec.setDecimals(4)
        self._end_sec.setMinimum(0.0)
        self._end_sec.setMaximum(99_999.0)
        self._end_sec.setValue(10.0)
        self._end_sec.valueChanged.connect(self._on_sec_end_changed)
        ps.addLayout(self._row("End (s):", self._end_sec))
        self._stack.addWidget(page_secs)

        page_tc = QWidget()
        pt = QVBoxLayout(page_tc)
        pt.setContentsMargins(0, 4, 0, 4)
        self._start_tc = QLineEdit()
        self._start_tc.setInputMask("99:99:99:999;_")
        self._start_tc.setText("00:00:00:000")
        self._start_tc.editingFinished.connect(self._on_tc_start_changed)
        pt.addLayout(self._row("Start (TC):", self._start_tc))
        self._end_tc = QLineEdit()
        self._end_tc.setInputMask("99:99:99:999;_")
        self._end_tc.setText("00:00:10:000")
        self._end_tc.editingFinished.connect(self._on_tc_end_changed)
        pt.addLayout(self._row("End (TC):", self._end_tc))
        self._stack.addWidget(page_tc)

        layout.addWidget(self._stack)

        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #888888; font-size: 11px;")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        layout.addWidget(sep)

        layout.addStretch(1)

        self._update_info()

    def set_video_info(self, info: dict | None) -> None:
        self._video_info = info
        has_video = info is not None and info.get("duration_s", 0) > 0

        self._all_duration_chk.setEnabled(has_video)

        if has_video:
            video_fps = info.get("fps", 0)
            if video_fps > 0:
                best_label = find_closest_fps_label(video_fps)
                if best_label:
                    self._suppress = True
                    self._fps_combo.setCurrentText(best_label)
                    self._suppress = False

            # Default to all video duration
            self._all_duration_chk.setChecked(True)

        if not has_video:
            self._all_duration_chk.setChecked(False)

    def set_times(self, start_ticks: int, end_ticks: int) -> None:
        self._suppress = True
        self._start_ticks = max(self._min_allowed_ticks, start_ticks)
        self._end_ticks = min(self._max_allowed_ticks, end_ticks)
        self._sync_widgets_from_ticks()
        self._suppress = False
        self._update_info()

    def set_limits(self, min_ticks: int, max_ticks: int) -> None:
        self._min_allowed_ticks = min_ticks
        self._max_allowed_ticks = max_ticks
        self._sync_widgets_from_ticks()

    def get_times(self) -> tuple[int, int]:
        return self._start_ticks, self._end_ticks

    def get_fps(self) -> float:
        return fps_from_label(self._fps_combo.currentText())

    @staticmethod
    def _row(text: str, widget: QWidget) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(QLabel(text))
        h.addWidget(widget, stretch=1)
        return h

    def _current_fps(self) -> float:
        return fps_from_label(self._fps_combo.currentText())

    def _sync_widgets_from_ticks(self) -> None:
        old = self._suppress
        self._suppress = True

        fps = self._current_fps()

        # Frames
        if fps > 0:
            min_f = int(min(MAX_QT_INT, ticks_to_frames(self._min_allowed_ticks, fps)))
            max_f = int(min(MAX_QT_INT, ticks_to_frames(self._max_allowed_ticks, fps)))

            self._start_frame.setRange(min_f, max(min_f, max_f - 1))
            self._start_frame.setValue(
                int(min(max_f, ticks_to_frames(self._start_ticks, fps)))
            )

            self._end_frame.setRange(
                max(min_f + 1, self._start_frame.value() + 1), max_f
            )
            self._end_frame.setValue(
                int(min(max_f, ticks_to_frames(self._end_ticks, fps)))
            )

        # Seconds
        min_s = min(float(MAX_QT_INT), ticks_to_seconds(self._min_allowed_ticks))
        max_s = min(float(MAX_QT_INT), ticks_to_seconds(self._max_allowed_ticks))
        self._start_sec.setRange(min_s, max(min_s, max_s - 0.0001))
        self._start_sec.setValue(min(max_s, ticks_to_seconds(self._start_ticks)))
        self._end_sec.setRange(
            max(min_s + 0.0001, self._start_sec.value() + 0.0001), max_s
        )
        self._end_sec.setValue(min(max_s, ticks_to_seconds(self._end_ticks)))

        # Timecode
        self._start_tc.setText(ticks_to_timecode(self._start_ticks))
        self._end_tc.setText(ticks_to_timecode(self._end_ticks))

        self._suppress = old

    def _emit_change(self) -> None:
        if self._suppress:
            return
        self._update_info()
        self.time_changed.emit(self._start_ticks, self._end_ticks)

    def _update_info(self) -> None:
        s = ticks_to_seconds(self._start_ticks)
        e = ticks_to_seconds(self._end_ticks)
        fps = self._current_fps()
        parts = [f"{s:.4f}s → {e:.4f}s"]
        if fps > 0:
            sf = ticks_to_frames(self._start_ticks, fps)
            ef = ticks_to_frames(self._end_ticks, fps)
            parts.append(f"frame {sf} → {ef}")
        if self._video_info:
            vid_dur = self._video_info.get("duration_s", 0)
            vid_frames = self._video_info.get("num_frames", 0)
            parts.append(f"video: {vid_dur:.2f}s / {vid_frames} frames")
        self._info_label.setText("  |  ".join(parts))

    def _on_fps_changed(self) -> None:
        if self._suppress:
            return
        self._sync_widgets_from_ticks()
        self._update_info()

    def _on_all_duration_toggled(self, checked: bool) -> None:
        if self._suppress:
            return
        if checked and self._video_info:
            fps = self._current_fps()
            num_frames = self._video_info.get("num_frames", 0)
            dur = self._video_info.get("duration_s", 0)
            self._start_ticks = 0
            if num_frames > 0 and fps > 0:
                self._end_ticks = frames_to_ticks(num_frames, fps)
            elif dur > 0:
                self._end_ticks = seconds_to_ticks(dur)
            self._sync_widgets_from_ticks()
            self._emit_change()

    def _on_frame_start_changed(self, val: int) -> None:
        if self._suppress:
            return
        fps = self._current_fps()
        if fps > 0:
            self._start_ticks = frames_to_ticks(val, fps)
            self._sync_widgets_from_ticks()
            self._emit_change()

    def _on_frame_end_changed(self, val: int) -> None:
        if self._suppress:
            return
        fps = self._current_fps()
        if fps > 0:
            self._end_ticks = frames_to_ticks(val, fps)
            self._sync_widgets_from_ticks()
            self._emit_change()

    def _on_sec_start_changed(self, val: float) -> None:
        if self._suppress:
            return
        self._start_ticks = seconds_to_ticks(val)
        self._sync_widgets_from_ticks()
        self._emit_change()

    def _on_sec_end_changed(self, val: float) -> None:
        if self._suppress:
            return
        self._end_ticks = seconds_to_ticks(val)
        self._sync_widgets_from_ticks()
        self._emit_change()

    def _on_tc_start_changed(self) -> None:
        if self._suppress:
            return
        t = timecode_to_ticks(self._start_tc.text())
        t = max(self._min_allowed_ticks, min(self._max_allowed_ticks - 1, t))
        self._start_ticks = t
        self._sync_widgets_from_ticks()
        self._emit_change()

    def _on_tc_end_changed(self) -> None:
        if self._suppress:
            return
        t = timecode_to_ticks(self._end_tc.text())
        t = max(self._start_ticks + 1, min(self._max_allowed_ticks, t))
        self._end_ticks = t
        self._sync_widgets_from_ticks()
        self._emit_change()
