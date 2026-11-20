from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QFrame,
    QSlider,
    QLabel,
    QPushButton,
)

from .utils import section_label, create_row, create_spin, create_info_icon
from fgseditor_qt.math.svt_photon_noise import CONTAINER_TFS, AUTHORING_TFS, FILM_FORMATS


class PanelPhotonNoise(QWidget):
    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        self._internal_update = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._build_photon_noise_section(layout)
        layout.addStretch(1)

    def _build_photon_noise_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("PHOTON NOISE"))

        self._pn_enable_chk = QCheckBox("Apply Photon Noise")
        self._pn_enable_chk.setToolTip("Apply photon noise to luma curve")
        self._pn_enable_chk.setChecked(False)
        self._pn_enable_chk.clicked.connect(self._on_pn_enable_toggled)
        parent.addWidget(self._pn_enable_chk)

        self._pn_apply_chroma_chk = QCheckBox("Apply to Chroma channels")
        self._pn_apply_chroma_chk.setToolTip("Apply photon noise to chroma curves (sCb, sCr)")
        self._pn_apply_chroma_chk.setChecked(False)
        self._pn_apply_chroma_chk.setEnabled(False)
        self._pn_apply_chroma_chk.clicked.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise() if self.sidebar else None
        )
        parent.addWidget(self._pn_apply_chroma_chk)

        self._pn_show_noise_chk = QCheckBox("Overlay Theoretical Noise")
        self._pn_show_noise_chk.setToolTip("Show continuous theoretical photon noise curve σ(x) in plotter")
        self._pn_show_noise_chk.setChecked(True)
        self._pn_show_noise_chk.toggled.connect(self._on_overlay_toggled)
        parent.addWidget(self._pn_show_noise_chk)

        self._pn_width = QLineEdit("1920")
        self._pn_height = QLineEdit("1080")
        self._pn_iso = create_spin(1, 100000, 400)

        self._pn_tf = QComboBox()
        self._pn_tf.addItems(list(CONTAINER_TFS.keys()))
        self._pn_tf.setCurrentText("BT_709")

        self._pn_range = QComboBox()
        self._pn_range.addItems(["LIMITED", "FULL"])
        self._pn_range.setCurrentText("LIMITED")

        self._pn_format = QComboBox()
        self._pn_format.addItems(list(FILM_FORMATS.keys()))
        self._pn_format.setCurrentText("35mm")

        parent.addLayout(create_row("Width:", self._pn_width))
        parent.addLayout(create_row("Height:", self._pn_height))
        parent.addLayout(create_row("ISO:", self._pn_iso))
        parent.addLayout(
            create_row(
                "Container TF:",
                self._pn_tf,
                info_tooltip=(
                    "Target ITU-T H.273 (CICP) video container transfer function.\n\n"
                    "• BT_709 / BT_2020 SDR / sRGB: Standard Dynamic Range containers.\n"
                    "• SMPTE_2084 (PQ): HDR10 absolute luminance container (0–10,000 nits).\n"
                    "• HLG: Scene-referred ARIB STD-B67 HDR container.\n"
                    "(Display/monitor EOTFs such as BT.1886 are excluded.)"
                ),
            )
        )
        parent.addLayout(create_row("Range:", self._pn_range))
        parent.addLayout(create_row("Sensor/Film:", self._pn_format))

        parent.addWidget(section_label("AUTHORING NOISE SHAPING"))

        self._pn_auth_tf = QComboBox()
        for key, tf_obj in AUTHORING_TFS.items():
            label = "None (Direct Transfer)" if tf_obj is None else (tf_obj.label or key)
            self._pn_auth_tf.addItem(label, key)
        self._pn_auth_tf.setCurrentIndex(0)

        parent.addLayout(
            create_row(
                "Camera/DI Log:",
                self._pn_auth_tf,
                info_tooltip=(
                    "Optional scene-referred Camera or Color Grading Log working space\n"
                    "used to model physical noise shaping prior to container delivery.\n\n"
                    "• None (Direct Transfer): Shapes sensor noise directly on the\n"
                    "  Container Transfer curve (legacy SVT-AV1 mode).\n"
                    "• Camera / DI Log: Shapes noise through the physical camera toe,\n"
                    "  logarithmic slope, and full-well highlight saturation before\n"
                    "  mapping to the SDR or HDR delivery container."
                ),
            )
        )

        # Slider 1: Log Influence (0% -> 100%)
        self._pn_auth_slider = QSlider(Qt.Horizontal)
        self._pn_auth_slider.setRange(0, 100)
        self._pn_auth_slider.setValue(0)
        self._pn_auth_slider.setEnabled(False)
        self._pn_auth_val_lbl = QLabel("0%")
        self._pn_auth_val_lbl.setFixedWidth(34)
        self._pn_auth_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._pn_auth_val_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        auth_mix_widget = QWidget()
        auth_mix_hb = QHBoxLayout(auth_mix_widget)
        auth_mix_hb.setContentsMargins(0, 0, 0, 0)
        auth_mix_hb.setSpacing(4)
        auth_mix_hb.addWidget(self._pn_auth_slider, stretch=1)
        auth_mix_hb.addWidget(self._pn_auth_val_lbl, stretch=0)

        parent.addLayout(
            create_row(
                "Log Influence:",
                auth_mix_widget,
                info_tooltip=(
                    "Blends noise shaping between Direct Container encoding and the\n"
                    "selected Camera/DI Log working space:\n\n"
                    "• 0% — Direct Container Transfer (current legacy behavior).\n"
                    "• 50% — Graded Cinema Hybrid (geometric blend reproducing real\n"
                    "  DI grading & tone-mapping between camera Log and delivery).\n"
                    "• 100% — Pure Camera/DI Log slope profile & sensor full-well\n"
                    "  saturation (prevents deep-shadow PQ explosion & models clip)."
                ),
            )
        )

        # Slider 2: Toe/Clip Roll-Off (0% -> 50%) + Adaptive Lock button
        self._pn_drt_slider = QSlider(Qt.Horizontal)
        self._pn_drt_slider.setRange(0, 50)
        self._pn_drt_slider.setValue(0)
        self._pn_drt_slider.setEnabled(False)
        self._pn_drt_val_lbl = QLabel("0%")
        self._pn_drt_val_lbl.setFixedWidth(34)
        self._pn_drt_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._pn_drt_val_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        self._pn_drt_lock_btn = QPushButton("🔒")
        self._pn_drt_lock_btn.setCheckable(True)
        self._pn_drt_lock_btn.setChecked(True)
        self._pn_drt_lock_btn.setFixedSize(22, 22)
        self._pn_drt_lock_btn.setToolTip(
            "Adaptive lock enabled (20% of Log Influence).\n"
            "Click to unlock for manual Toe/Clip Roll-Off control."
        )
        self._pn_drt_lock_btn.setStyleSheet(
            "QPushButton { background: #262b3d; color: #9bb8ff; border: 1px solid #3f4a6b; "
            "border-radius: 3px; font-size: 11px; padding: 0; }"
            "QPushButton:checked { background: #1e3a5f; color: #ffffff; border: 1px solid #4da6ff; }"
            "QPushButton:hover { background: #324468; }"
        )

        drt_widget = QWidget()
        drt_hb = QHBoxLayout(drt_widget)
        drt_hb.setContentsMargins(0, 0, 0, 0)
        drt_hb.setSpacing(4)
        drt_hb.addWidget(self._pn_drt_slider, stretch=1)
        drt_hb.addWidget(self._pn_drt_val_lbl, stretch=0)
        drt_hb.addWidget(self._pn_drt_lock_btn, stretch=0)

        parent.addLayout(
            create_row(
                "Toe/Clip Roll:",
                drt_widget,
                info_tooltip=(
                    "Attenuates extreme shadow toe (black) and peak highlight shoulder (clip)\n"
                    "smoothly around the mid-gray anchor (0% attenuation at mid-gray).\n"
                    "Models S-curve LUT / DRT highlight & black compression.\n\n"
                    "• 🔒 Locked (Auto): Automatically scales as 20% of Log Influence\n"
                    "  (0% in Direct mode, 10% at 50% Hybrid, 20% at 100% Log).\n"
                    "• 🔓 Unlocked (Manual): Adjust independently from 0% to 50%."
                ),
            )
        )

        self._pn_width.textChanged.connect(self._on_param_changed)
        self._pn_height.textChanged.connect(self._on_param_changed)
        self._pn_iso.valueChanged.connect(self._on_param_changed)
        self._pn_tf.currentTextChanged.connect(self._on_param_changed)
        self._pn_range.currentTextChanged.connect(self._on_range_changed)
        self._pn_format.currentTextChanged.connect(self._on_param_changed)

        self._pn_auth_tf.currentIndexChanged.connect(self._on_auth_tf_changed)
        self._pn_auth_slider.valueChanged.connect(self._on_auth_slider_changed)
        self._pn_auth_slider.sliderReleased.connect(self._on_slider_released)
        self._pn_drt_lock_btn.toggled.connect(self._on_drt_lock_toggled)
        self._pn_drt_slider.valueChanged.connect(self._on_drt_slider_changed)
        self._pn_drt_slider.sliderReleased.connect(self._on_slider_released)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def get_authoring_tf_key(self) -> str:
        data = self._pn_auth_tf.currentData()
        return str(data) if data else "NONE"

    def get_authoring_strength(self) -> float:
        if self.get_authoring_tf_key() == "NONE":
            return 0.0
        return self._pn_auth_slider.value() / 100.0

    def get_drt_rolloff(self) -> float | None:
        if self._pn_drt_lock_btn.isChecked():
            return None
        return self._pn_drt_slider.value() / 100.0

    def _sync_drt_adaptive_value(self) -> None:
        if not self._pn_drt_lock_btn.isChecked():
            return
        w_pct = 0 if self.get_authoring_tf_key() == "NONE" else self._pn_auth_slider.value()
        adaptive_pct = int(round(0.20 * w_pct))
        self._pn_drt_slider.blockSignals(True)
        self._pn_drt_slider.setValue(adaptive_pct)
        self._pn_drt_slider.blockSignals(False)
        self._pn_drt_val_lbl.setText(f"{adaptive_pct}%")

    def _refresh_authoring_controls_state(self) -> None:
        has_auth = self.get_authoring_tf_key() != "NONE"
        self._pn_auth_slider.setEnabled(has_auth)
        locked = self._pn_drt_lock_btn.isChecked()
        self._pn_drt_lock_btn.setText("🔒" if locked else "🔓")
        self._pn_drt_slider.setEnabled(not locked)
        if locked:
            self._sync_drt_adaptive_value()
        self._pn_auth_val_lbl.setText(f"{self._pn_auth_slider.value()}%")
        self._pn_drt_val_lbl.setText(f"{self._pn_drt_slider.value()}%")

    def _on_auth_tf_changed(self, _idx: int) -> None:
        if self._internal_update:
            return
        self._internal_update = True
        try:
            key = self.get_authoring_tf_key()
            if key == "NONE":
                self._pn_auth_slider.setValue(0)
            elif self._pn_auth_slider.value() == 0:
                self._pn_auth_slider.setValue(50)
            self._refresh_authoring_controls_state()
        finally:
            self._internal_update = False
        self._on_param_changed()

    def _on_auth_slider_changed(self, val: int) -> None:
        self._pn_auth_val_lbl.setText(f"{val}%")
        if self._pn_drt_lock_btn.isChecked():
            self._sync_drt_adaptive_value()
        if self._internal_update:
            return
        if self.sidebar:
            self.sidebar.recompute_photon_noise_overlays()
            if self._pn_enable_chk.isChecked() and not self._pn_auth_slider.isSliderDown():
                self.sidebar._generate_and_emit_photon_noise()

    def _on_drt_lock_toggled(self, checked: bool) -> None:
        self._pn_drt_lock_btn.setText("🔒" if checked else "🔓")
        self._pn_drt_slider.setEnabled(not checked)
        if checked:
            self._pn_drt_lock_btn.setToolTip(
                "Adaptive lock enabled (20% of Log Influence).\n"
                "Click to unlock for manual Toe/Clip Roll-Off control."
            )
            self._sync_drt_adaptive_value()
        else:
            self._pn_drt_lock_btn.setToolTip(
                "Manual mode enabled.\n"
                "Click to lock back to adaptive 20% of Log Influence."
            )
        if not self._internal_update:
            self._on_param_changed()

    def _on_drt_slider_changed(self, val: int) -> None:
        self._pn_drt_val_lbl.setText(f"{val}%")
        if self._internal_update:
            return
        if self.sidebar:
            self.sidebar.recompute_photon_noise_overlays()
            if self._pn_enable_chk.isChecked() and not self._pn_drt_slider.isSliderDown():
                self.sidebar._generate_and_emit_photon_noise()

    def _on_slider_released(self) -> None:
        if self.sidebar and self._pn_enable_chk.isChecked():
            self.sidebar._generate_and_emit_photon_noise()

    def _on_overlay_toggled(self, _=False) -> None:
        if self.sidebar:
            self.sidebar._on_photon_noise_visibility_changed(
                self._pn_show_noise_chk.isChecked(),
            )

    def _on_range_changed(self, text: str) -> None:
        if self.sidebar:
            self.sidebar._on_range_changed_from_panel(text)
        self._on_param_changed()

    def _on_param_changed(self, *_) -> None:
        if self.sidebar:
            self.sidebar.recompute_photon_noise_overlays()
            if self._pn_enable_chk.isChecked():
                self.sidebar._generate_and_emit_photon_noise()

    def _on_pn_enable_toggled(self, checked: bool) -> None:
        if checked:
            from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QHBoxLayout

            dialog = QDialog(self)
            dialog.setWindowTitle("Overwrite Confirmation")
            dialog.setMinimumWidth(380)

            d_layout = QVBoxLayout(dialog)
            d_layout.addWidget(
                QLabel("This will overwrite existing luma (sY) scaling points.\nProceed?")
            )

            chroma_chk = QCheckBox("Apply to Chroma (sCb, sCr)")
            chroma_chk.setChecked(self._pn_apply_chroma_chk.isChecked())
            d_layout.addWidget(chroma_chk)

            btn_layout = QHBoxLayout()
            yes_btn = QPushButton("Yes")
            no_btn = QPushButton("No")
            btn_layout.addWidget(yes_btn)
            btn_layout.addWidget(no_btn)
            d_layout.addLayout(btn_layout)

            yes_btn.clicked.connect(dialog.accept)
            no_btn.clicked.connect(dialog.reject)

            if dialog.exec() == QDialog.Rejected:
                self._pn_enable_chk.setChecked(False)
                return

            self._pn_apply_chroma_chk.setChecked(chroma_chk.isChecked())

        state = self._pn_enable_chk.isChecked()
        self._pn_apply_chroma_chk.setEnabled(state)

        if self.sidebar:
            self.sidebar.recompute_photon_noise_overlays()
            if state:
                self.sidebar._generate_and_emit_photon_noise()

    def get_state(self) -> dict:
        return {
            "pn_enabled": self._pn_enable_chk.isChecked(),
            "pn_width": self._pn_width.text(),
            "pn_height": self._pn_height.text(),
            "pn_iso": self._pn_iso.value(),
            "pn_tf": self._pn_tf.currentText(),
            "pn_range": self._pn_range.currentText(),
            "pn_format": self._pn_format.currentText(),
            "pn_auth_tf": self.get_authoring_tf_key(),
            "pn_auth_strength": self._pn_auth_slider.value(),
            "pn_drt_locked": self._pn_drt_lock_btn.isChecked(),
            "pn_drt_rolloff": self._pn_drt_slider.value(),
            "pn_apply_chroma": self._pn_apply_chroma_chk.isChecked(),
            "pn_show_noise": self._pn_show_noise_chk.isChecked(),
        }

    def set_state(self, state: dict) -> None:
        self._internal_update = True
        try:
            self._pn_width.setText(str(state.get("pn_width", "1920")))
            self._pn_height.setText(str(state.get("pn_height", "1080")))
            self._pn_iso.setValue(state.get("pn_iso", 400))

            tf_val = str(state.get("pn_tf", "BT_709"))
            tf_idx = self._pn_tf.findText(tf_val)
            if tf_idx >= 0:
                self._pn_tf.setCurrentIndex(tf_idx)
            else:
                self._pn_tf.setCurrentText("BT_709")

            self._pn_range.setCurrentText(state.get("pn_range", "LIMITED"))

            fmt_val = state.get("pn_format", "35mm")
            fmt_idx = self._pn_format.findText(fmt_val)
            if fmt_idx < 0:
                for i in range(self._pn_format.count()):
                    if self._pn_format.itemText(i).lower() == fmt_val.lower():
                        fmt_idx = i
                        break
            if fmt_idx >= 0:
                self._pn_format.setCurrentIndex(fmt_idx)
            else:
                self._pn_format.setCurrentText(fmt_val)

            auth_key = str(state.get("pn_auth_tf", "NONE")).upper()
            auth_idx = self._pn_auth_tf.findData(auth_key)
            self._pn_auth_tf.setCurrentIndex(auth_idx if auth_idx >= 0 else 0)

            self._pn_auth_slider.setValue(int(state.get("pn_auth_strength", 0)))
            locked = bool(state.get("pn_drt_locked", True))
            self._pn_drt_lock_btn.setChecked(locked)
            self._pn_drt_slider.setValue(int(state.get("pn_drt_rolloff", 0)))
            self._refresh_authoring_controls_state()

            self._pn_enable_chk.setChecked(state.get("pn_enabled", False))
            self._pn_apply_chroma_chk.setChecked(state.get("pn_apply_chroma", False))
            if "pn_show_noise" in state:
                self._pn_show_noise_chk.setChecked(bool(state["pn_show_noise"]))

            pn_state = self._pn_enable_chk.isChecked()
            self._pn_apply_chroma_chk.setEnabled(pn_state)
        finally:
            self._internal_update = False

    def set_video_info(self, info: dict | None) -> None:
        if info:
            w = str(info.get("width", "1920"))
            h = str(info.get("height", "1080"))
            self._pn_width.setText(w)
            self._pn_height.setText(h)
