from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QScrollArea,
)
from PySide6.QtCore import Signal, Qt

from . import fgs_parser
from .fgs_parser import load_grain_preset
from .svt_photon_noise import PhotonNoiseGenerator
from .panels.panel_fgs_value import PanelFGSValue
from .panels.panel_grain_size import PanelGrainSize
from .panels.panel_photon_noise import PanelPhotonNoise
from .panels.panel_templates import PanelTemplates
from .panels.panel_time import PanelTime


class ParamsSidebar(QWidget):
    params_changed = Signal(dict)
    grain_size_changed = Signal(str)
    photon_noise_changed = Signal(dict)
    template_apply_requested = Signal(dict, int)
    time_changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suppress = False
        self._p_params: dict = dict(fgs_parser.P_DEFAULTS)

        self.setObjectName("paramsSidebar")
        self.setStyleSheet(
            "#paramsSidebar { background-color: #1a1a2e; border-right: 1px solid #333355; }"
            "QSpinBox { background: #2d2d2d; color: #dddddd; border: 1px solid #444; "
            "           border-radius: 3px; padding: 1px 4px; min-height: 20px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 14px; }"
            "QComboBox { background: #2d2d2d; color: #dddddd; border: 1px solid #444; "
            "            border-radius: 3px; padding: 1px 6px; min-height: 22px; }"
            "QLineEdit { background: #2d2d2d; color: #dddddd; border: 1px solid #444; border-radius: 3px; padding: 1px 4px;}"
        )

        self._collapsed = False
        self.setMinimumWidth(300)

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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        scroll.setWidget(self._content_widget)
        outer.addWidget(scroll, stretch=1)
        self._scroll_area = scroll

        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(2)

        self.panel_grain = PanelGrainSize(self)
        self.panel_fgs = PanelFGSValue(self)
        self.panel_photon = PanelPhotonNoise(self)
        self.panel_templates = PanelTemplates(self)
        self.panel_time = PanelTime(self)
        self.panel_time.time_changed.connect(self.time_changed)

        content_layout.addWidget(self.panel_fgs)
        content_layout.addWidget(self.panel_grain)
        content_layout.addWidget(self.panel_photon)
        content_layout.addWidget(self.panel_templates)
        content_layout.addWidget(self.panel_time)
        content_layout.addStretch(1)

        self.set_tab(5)  # "All" by default

    def set_tab(self, index: int):
        """Changes active panel visibility"""
        self.panel_fgs.setVisible(index == 0 or index == 5)
        self.panel_grain.setVisible(index == 1 or index == 5)
        self.panel_photon.setVisible(index == 2 or index == 5)
        self.panel_templates.setVisible(index == 3 or index == 5)
        self.panel_time.setVisible(index == 4 or index == 5)

    def _generate_and_emit_photon_noise(self, *_) -> None:
        if self._suppress or not self.panel_photon._pn_enable_chk.isChecked():
            return

        try:
            w = int(self.panel_photon._pn_width.text())
            h = int(self.panel_photon._pn_height.text())
        except ValueError:
            return

        iso = self.panel_photon._pn_iso.value()
        tf = self.panel_photon._pn_tf.currentText()
        color_range = self.panel_photon._pn_range.currentText()
        film_format = self.panel_photon._pn_format.currentText()

        generator = PhotonNoiseGenerator(
            width=w,
            height=h,
            iso_setting=iso,
            tc_name=tf,
            color_range=color_range,
            film_format=film_format,
        )
        sy_points = generator.generate_points()

        payload = {
            "sY": {"x": [p[0] for p in sy_points], "y": [p[1] for p in sy_points]},
            "sCb": {"x": [], "y": []},
            "sCr": {"x": [], "y": []},
        }
        self.photon_noise_changed.emit(payload)

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

    def _on_seed_changed(self, *_) -> None:
        if self._suppress:
            return
        self._p_params = self._read_p_params()
        self.params_changed.emit(self._p_params)

    def _on_grain_size_changed(self, name: str) -> None:
        if self._suppress:
            return

        import re

        has_digit = bool(re.search(r"\d+", str(name)))

        if name == "-1" or not has_digit:
            pass
        else:
            preset = load_grain_preset(name)
            if preset and preset["p_tokens"]:
                try:
                    ar_coeff_lag = int(preset["p_tokens"][0])
                    self._suppress = True
                    self.panel_fgs._ar_lag.setValue(ar_coeff_lag)
                    self._suppress = False
                except (ValueError, IndexError):
                    pass

        self.grain_size_changed.emit(name)

    def apply_template_to_current(self, evt: dict, mode: int):
        self.template_apply_requested.emit(evt, mode)

    def _read_p_params(self) -> dict:
        d = {}
        self.panel_fgs.update_p_params_dict(d)
        return d

    def _load_p_params(self, p: dict) -> None:
        self.panel_fgs.load_p_params_dict(p)
        self.panel_grain.load_p_params_dict(p)

    def load_from_event(self, event: dict, size_id: str | None = None) -> None:
        p = fgs_parser.get_p_params(event)
        if p:
            self._suppress = True
            self._load_p_params(p)

            seed = fgs_parser.get_grain_seed(event)
            self.panel_fgs.set_seed(seed)

            if size_id is not None:
                self.set_grain_size(size_id)
            else:
                self.set_grain_size("-1")

            if "start_time" in event and "end_time" in event:
                self.set_event_times(event["start_time"], event["end_time"])

            self._suppress = False
            self._p_params = p

    def get_p_params(self) -> dict:
        return dict(self._p_params)

    def set_ar_shift_warning(self, is_unstable: bool) -> None:
        self.panel_fgs.set_ar_shift_warning(is_unstable)

    def get_grain_size(self) -> str:
        return self.panel_grain.get_grain_size()

    def get_seed(self) -> int:
        return self.panel_fgs.get_seed()

    def set_seed(self, seed: int) -> None:
        self.panel_fgs.set_seed(seed)

    def set_video_info(self, info: dict | None) -> None:
        self.panel_time.set_video_info(info)

    def get_event_time_bounds(self) -> tuple[int, int]:
        return self.panel_time.get_times()

    def set_time_limits(self, min_ticks: int, max_ticks: int) -> None:
        self.panel_time.set_limits(min_ticks, max_ticks)

    def set_event_times(self, start_ticks: int, end_ticks: int) -> None:
        self.panel_time.set_times(start_ticks, end_ticks)

    def set_grain_size(self, size_id: str) -> None:
        self.panel_grain.set_grain_size(size_id)

    def get_full_state(self) -> dict:
        import copy

        state = {
            "p_params": copy.deepcopy(self._p_params),
            "grain_size": self.get_grain_size(),
            "grain_seed": self.get_seed(),
        }
        state.update(self.panel_photon.get_state())
        return state

    def set_full_state(self, state: dict) -> None:
        if not state:
            return
        self._suppress = True

        p_from_state = fgs_parser.get_p_params(state)
        self._load_p_params(p_from_state)
        self._p_params = p_from_state
        self.set_grain_size(state.get("grain_size", "-1"))

        self.panel_fgs.set_seed(state.get("grain_seed", 7391))

        self.panel_photon.set_state(state)

        self._suppress = False
