from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QCheckBox, QComboBox, QPushButton, QFrame, QScrollArea,
)
from PySide6.QtCore import Signal, Qt

from .fgs_math import P_DEFAULTS, parse_p_row
from .fgs_size_table import available_sizes, load_size_preset
from .time_utils import COMMON_FPS, DEFAULT_FPS_LABEL, fps_from_label


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #569cd6; font-size: 10px; font-weight: bold; "
        "margin-top: 8px; margin-bottom: 2px; letter-spacing: 1px;"
    )
    return lbl


def _row(label_text: str, widget: QWidget) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.setContentsMargins(0, 0, 0, 0)
    hb.setSpacing(6)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color: #cccccc; font-size: 11px;")
    lbl.setMinimumWidth(115)
    hb.addWidget(lbl, stretch=0)
    hb.addWidget(widget, stretch=1)
    return hb


class ParamsSidebar(QWidget):
    params_changed     = Signal(dict)
    grain_size_changed = Signal(int)
    fps_changed        = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suppress = False
        self._p_params: dict = dict(P_DEFAULTS)

        self.setObjectName("paramsSidebar")
        self.setStyleSheet(
            "#paramsSidebar { background-color: #1a1a2e; border-right: 1px solid #333355; }"
            "QSpinBox { background: #2d2d2d; color: #dddddd; border: 1px solid #444; "
            "           border-radius: 3px; padding: 1px 4px; min-height: 20px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 14px; }"
            "QCheckBox { color: #cccccc; font-size: 11px; }"
            "QComboBox { background: #2d2d2d; color: #dddddd; border: 1px solid #444; "
            "            border-radius: 3px; padding: 1px 6px; min-height: 22px; }"
        )

        self._collapsed = False
        self.setMinimumWidth(230)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Collapse button
        self._collapse_btn = QPushButton("◀  Parameters")
        self._collapse_btn.setCheckable(True)
        self._collapse_btn.setFixedHeight(28)
        self._collapse_btn.setStyleSheet(
            "QPushButton { background: #252540; color: #aaaacc; border: none; "
            "font-size: 11px; font-weight: bold; text-align: left; padding-left: 8px; }"
            "QPushButton:checked { background: #1a1a2e; color: #4da6ff; }"
        )
        self._collapse_btn.toggled.connect(self._on_collapse)
        outer.addWidget(self._collapse_btn)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        scroll.setWidget(self._content_widget)
        outer.addWidget(scroll, stretch=1)
        self._scroll_area = scroll

        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(2)

        self._build_grain_size_section(content_layout)
        self._build_ui_options_section(content_layout)
        self._build_ar_section(content_layout)
        self._build_scaling_section(content_layout)
        self._build_chroma_section(content_layout)
        self._build_fps_section(content_layout)

        content_layout.addStretch(1)

    def _build_grain_size_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("GRAIN MORPHOLOGY"))

        self._grain_size_combo = QComboBox()
        self._grain_size_combo.addItem("Manual/Original", -1)
        sizes = available_sizes()
        for s in sorted(sizes):
            self._grain_size_combo.addItem(f"Size {s}", s)

        self._grain_size_combo.setToolTip(
            "Select 'Manual/Original' to use the values from the FGS file.\n"
            "Select a size (0-13) to load a preset from FGS_size_table/."
        )
        self._grain_size_combo.currentIndexChanged.connect(self._on_grain_size_changed)
        parent.addLayout(_row("Grain Size:", self._grain_size_combo))

        self._noise_setting_spin = QSpinBox()
        self._noise_setting_spin.setRange(1, 300)  # 100% = AV1_PRNG_RMS (≈24.0)
        self._noise_setting_spin.setValue(100)
        self._noise_setting_spin.setSuffix("%")
        self._noise_setting_spin.setToolTip(
            "Base amplitude of the AV1 Gaussian noise generator.\n"
            "100% = full AV1 PRNG reference (≈24.0 RMS).\n"
            "Increase to simulate louder film grain, decrease for subtle."
        )
        self._noise_setting_spin.valueChanged.connect(self._on_p_param_changed)
        parent.addLayout(_row("Gaussian Base:", self._noise_setting_spin))

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def _build_ui_options_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("UI OPTIONS"))

        self._autobalance_chk = QCheckBox("Strength Autobalance")
        self._autobalance_chk.setChecked(False)
        self._autobalance_chk.setToolTip(
            "When ON (default):\n"
            "  • Preview shows constant perceived amplitude across grain sizes.\n"
            "  • On SAVE, sY/sCb/sCr values are scaled to compensate\n"
            "    for psychovisual size reduction.\n\n"
            "When OFF:\n"
            "  • Preview shows the real amplitude (decreases with larger grain).\n"
            "  • Saved values are written as-is (no compensation)."
        )
        self._autobalance_chk.stateChanged.connect(self._on_p_param_changed)
        parent.addWidget(self._autobalance_chk)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def _build_ar_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("AR FILTER"))

        self._ar_lag   = self._spin(0, 3,   P_DEFAULTS["ar_coeff_lag"],
                                    "AR coefficient lag (0=no AR, 3=full 24-coeff)")
        self._ar_shift = self._spin(6, 9,  P_DEFAULTS["ar_coeff_shift"],
                                    "AR shift (divisor = 2^shift)")
        self._gs_shift = self._spin(0, 3,   P_DEFAULTS["grain_scale_shift"],
                                    "Grain scale shift (Gaussian pre-scale)")

        for label, widget in [
            ("ar_coeff_lag:",   self._ar_lag),
            ("ar_coeff_shift:", self._ar_shift),
            ("grain_scale_sh:", self._gs_shift),
        ]:
            parent.addLayout(_row(label, widget))

        self._ar_lag.valueChanged.connect(self._on_p_param_changed)
        self._ar_shift.valueChanged.connect(self._on_p_param_changed)
        self._gs_shift.valueChanged.connect(self._on_p_param_changed)

    def _build_scaling_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("SCALING"))

        self._sc_shift = self._spin(8, 11, P_DEFAULTS["scaling_shift"],
                                    "Scaling shift — grain intensity divisor (2^shift).\n"
                                    "Lower = stronger grain!  (8 = aggressive, 11 = subtle)")
        self._sc_shift.valueChanged.connect(self._on_p_param_changed)
        parent.addLayout(_row("scaling_shift:", self._sc_shift))

    def _build_chroma_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("CHROMA LINK"))

        self._chroma_from_luma = QCheckBox("chroma_from_luma")
        self._chroma_from_luma.setToolTip(
            "If checked the chroma scaling curve is copied directly from luma."
        )
        self._chroma_from_luma.setChecked(False)
        self._chroma_from_luma.stateChanged.connect(self._on_p_param_changed)
        parent.addWidget(self._chroma_from_luma)

        self._overlap_flag = QCheckBox("overlap_flag")
        self._overlap_flag.setToolTip("Whether film grain blocks overlap.")
        self._overlap_flag.setChecked(True)
        self._overlap_flag.stateChanged.connect(self._on_p_param_changed)
        parent.addWidget(self._overlap_flag)

        # Cb
        parent.addWidget(_section_label("── Cb ──"))
        self._cb_mult      = self._spin(0, 255, P_DEFAULTS["cb_mult"],     "Cb chroma mult")
        self._cb_luma_mult = self._spin(0, 255, P_DEFAULTS["cb_luma_mult"],
                                        "Cb luma_mult (192 = copy from luma)")
        self._cb_offset    = self._spin(0, 512, P_DEFAULTS["cb_offset"],   "Cb offset")
        for label, w in [("cb_mult:", self._cb_mult),
                          ("cb_luma_mult:", self._cb_luma_mult),
                          ("cb_offset:", self._cb_offset)]:
            parent.addLayout(_row(label, w))
            w.valueChanged.connect(self._on_p_param_changed)

        # Cr
        parent.addWidget(_section_label("── Cr ──"))
        self._cr_mult      = self._spin(0, 255, P_DEFAULTS["cr_mult"],     "Cr chroma mult")
        self._cr_luma_mult = self._spin(0, 255, P_DEFAULTS["cr_luma_mult"],
                                        "Cr luma_mult (192 = copy from luma)")
        self._cr_offset    = self._spin(0, 512, P_DEFAULTS["cr_offset"],   "Cr offset")
        for label, w in [("cr_mult:", self._cr_mult),
                          ("cr_luma_mult:", self._cr_luma_mult),
                          ("cr_offset:", self._cr_offset)]:
            parent.addLayout(_row(label, w))
            w.valueChanged.connect(self._on_p_param_changed)

    def _build_fps_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(_section_label("FPS"))
        self._fps_combo = QComboBox()
        for lbl, _ in COMMON_FPS:
            self._fps_combo.addItem(lbl)
        self._fps_combo.setCurrentText(DEFAULT_FPS_LABEL)
        self._fps_combo.currentTextChanged.connect(self._on_fps_changed)
        parent.addLayout(_row("Frame rate:", self._fps_combo))

    @staticmethod
    def _clip3(min_val: int, max_val: int, val: int) -> int:
        return max(min_val, min(max_val, val))

    @staticmethod
    def _spin(min_val: int, max_val: int, default: int, tooltip: str = "") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(min_val, max_val)
        sp.setValue(default)
        if tooltip:
            sp.setToolTip(tooltip)
        return sp

    def _on_collapse(self, checked: bool) -> None:
        self._collapsed = checked
        self._scroll_area.setVisible(not checked)
        if checked:
            self.setFixedWidth(28)
        else:
            self.setMinimumWidth(230)
            self.setMaximumWidth(16777215)
        self._collapse_btn.setText("▶" if checked else "◀  Parameters")

    def _on_p_param_changed(self, *_) -> None:
        if self._suppress:
            return
        self._p_params = self._read_p_params()
        self.params_changed.emit(self._p_params)

    def _on_grain_size_changed(self, index: int) -> None:
        if self._suppress:
            return

        size_id = self._grain_size_combo.itemData(index)

        if size_id == -1:
            self._suppress = True
            self._autobalance_chk.setChecked(False)
            self._autobalance_chk.setEnabled(False)
            self._suppress = False
        else:
            self._autobalance_chk.setEnabled(True)

            preset = load_size_preset(size_id)
            if preset and preset["p_tokens"]:
                try:
                    ar_coeff_lag = int(preset["p_tokens"][0])
                    self._suppress = True
                    self._ar_lag.setValue(ar_coeff_lag)
                    self._suppress = False
                except (ValueError, IndexError):
                    pass

        self.grain_size_changed.emit(size_id)
        self._on_p_param_changed()

    def _on_fps_changed(self, label: str) -> None:
        if self._suppress:
            return
        self.fps_changed.emit(fps_from_label(label))

    def _read_p_params(self) -> dict:
        return {
            "ar_coeff_lag":           self._ar_lag.value(),
            "ar_coeff_shift":         self._ar_shift.value(),
            "grain_scale_shift":      self._gs_shift.value(),
            "scaling_shift":          self._sc_shift.value(),
            "chroma_scaling_from_luma": int(self._chroma_from_luma.isChecked()),
            "overlap_flag":           int(self._overlap_flag.isChecked()),
            "cb_mult":                self._cb_mult.value(),
            "cb_luma_mult":           self._cb_luma_mult.value(),
            "cb_offset":              self._cb_offset.value(),
            "cr_mult":                self._cr_mult.value(),
            "cr_luma_mult":           self._cr_luma_mult.value(),
            "cr_offset":              self._cr_offset.value(),
            "noise_setting":          self._noise_setting_spin.value() / 100.0,
        }

    def _load_p_params(self, p: dict) -> None:
        self._ar_lag.setValue(p.get("ar_coeff_lag", P_DEFAULTS["ar_coeff_lag"]))
        self._ar_shift.setValue(p.get("ar_coeff_shift", P_DEFAULTS["ar_coeff_shift"]))
        self._gs_shift.setValue(p.get("grain_scale_shift", P_DEFAULTS["grain_scale_shift"]))
        self._sc_shift.setValue(p.get("scaling_shift", P_DEFAULTS["scaling_shift"]))
        self._chroma_from_luma.setChecked(bool(p.get("chroma_scaling_from_luma", 0)))
        self._overlap_flag.setChecked(bool(p.get("overlap_flag", 1)))
        self._cb_mult.setValue(p.get("cb_mult", P_DEFAULTS["cb_mult"]))
        self._cb_luma_mult.setValue(p.get("cb_luma_mult", P_DEFAULTS["cb_luma_mult"]))
        self._cb_offset.setValue(p.get("cb_offset", P_DEFAULTS["cb_offset"]))
        self._cr_mult.setValue(p.get("cr_mult", P_DEFAULTS["cr_mult"]))
        self._cr_luma_mult.setValue(p.get("cr_luma_mult", P_DEFAULTS["cr_luma_mult"]))
        self._cr_offset.setValue(p.get("cr_offset", P_DEFAULTS["cr_offset"]))
        noise_val = p.get("noise_setting", 1.0)
        self._noise_setting_spin.setValue(int(noise_val * 100))

    def load_from_event(self, event: dict, size_id: int | None = None) -> None:
        p = event.get("p_params")
        if p is None:
            for raw_line in event.get("raw_lines", []):
                tokens = raw_line.strip().split()
                if tokens and tokens[0] == "p":
                    p = parse_p_row(tokens[1:])
                    break
        if p:
            self._suppress = True
            self._load_p_params(p)
            if size_id is not None:
                self.set_grain_size(size_id)
            else:
                self.set_grain_size(-1)
            self._suppress = False
            self._p_params = p

    def get_p_params(self) -> dict:
        return dict(self._p_params)

    def set_ar_shift_warning(self, is_unstable: bool) -> None:
        if is_unstable:
            self._ar_shift.setStyleSheet(
                "QSpinBox { background: #5c1a1a; color: #ff6b6b; "
                "border: 2px solid #ff4444; border-radius: 3px; "
                "padding: 1px 4px; min-height: 20px; }"
                "QSpinBox::up-button, QSpinBox::down-button { width: 14px; }"
            )
            self._ar_shift.setToolTip(
                "⚠ UNSTABLE AR FILTER!\n"
                "sum(cY) / 2^ar_shift > 1.0 → the AR gain is infinite or negative.\n"
                "Increase ar_coeff_shift to stabilise (e.g. shift 8 → divisor 256)."
            )
        else:
            self._ar_shift.setStyleSheet("")
            self._ar_shift.setToolTip("AR shift (divisor = 2^shift)")



    def get_grain_size(self) -> int:
        return self._grain_size_combo.currentData()

    def get_fps(self) -> float:
        return fps_from_label(self._fps_combo.currentText())

    def get_noise_setting(self) -> float:
        return float(self._noise_setting_spin.value())

    def get_autobalance(self) -> bool:
        return self._autobalance_chk.isChecked()

    def set_grain_size(self, size_id: int) -> None:
        """Select index matching the size_id data."""
        idx = self._grain_size_combo.findData(size_id)
        if idx >= 0:
            self._grain_size_combo.setCurrentIndex(idx)
        else:
            self._grain_size_combo.setCurrentIndex(0)

    def fps_combo_widget(self) -> QComboBox:
        """Return the fps QComboBox for external connection (e.g. DynamicTimelineUI)."""
        return self._fps_combo
