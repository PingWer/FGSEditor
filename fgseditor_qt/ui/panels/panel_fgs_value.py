import random

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QSpinBox,
    QLabel,
)

from .utils import section_label, create_row, create_spin
from fgseditor_qt.core import fgs_parser
from fgseditor_qt.core.fgs_parser import P_DEFAULTS
from fgseditor_qt.core.AFGS_TABLE_and_SEEDS import CHERRY_SEEDS


class PanelFGSValue(QWidget):
    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._build_seed_section(layout)
        self._build_ar_section(layout)
        self._build_scaling_section(layout)
        self._build_chroma_section(layout)

        layout.addStretch(1)

    def _build_seed_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("GRAIN SEED"))

        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("seed:")
        lbl.setStyleSheet("color: #aaaacc; font-size: 11px;")
        lbl.setMinimumWidth(60)
        lbl.setMaximumWidth(70)
        seed_row.addWidget(lbl)

        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(1, 65535)
        self._seed_spin.setValue(7391)
        self._seed_spin.setToolTip("16-bit deterministic noise seed.")
        seed_row.addWidget(self._seed_spin, stretch=1)

        self._seed_rand_btn = QPushButton("Rnd")
        self._seed_rand_btn.setMinimumWidth(38)
        self._seed_rand_btn.setMaximumWidth(45)
        self._seed_rand_btn.setToolTip("Pick random seed")
        self._seed_rand_btn.setStyleSheet(
            "QPushButton { background: #3a3a5c; color: #aaccff; border: 1px solid #555577; "
            "border-radius: 3px; font-size: 10px; font-weight: bold; padding: 2px; }"
            "QPushButton:hover { background: #4a4a7c; color: #ccddff; }"
            "QPushButton:pressed { background: #2a2a4c; }"
        )
        self._seed_rand_btn.clicked.connect(self._on_random_seed)
        seed_row.addWidget(self._seed_rand_btn)

        parent.addLayout(seed_row)

        self._seed_spin.valueChanged.connect(self._on_seed_changed)

    def _on_random_seed(self):
        seeds_list = list(CHERRY_SEEDS)
        new_seed = random.choice(seeds_list)
        while new_seed == 0:
            new_seed = random.choice(seeds_list)
        self._seed_spin.setValue(new_seed)

    def _on_seed_changed(self):
        if self.sidebar:
            self.sidebar._on_seed_changed()

    def get_seed(self) -> int:
        return self._seed_spin.value()

    def set_seed(self, seed: int) -> None:
        self._seed_spin.blockSignals(True)
        self._seed_spin.setValue(max(1, seed & 0xFFFF))
        self._seed_spin.blockSignals(False)

    def _build_ar_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("AR FILTER"))

        self._ar_lag = create_spin(
            0,
            3,
            P_DEFAULTS["ar_coeff_lag"],
            "AR coefficient lag (0=none, 3=full 24-coeff)",
        )
        self._ar_shift = create_spin(
            6, 9, P_DEFAULTS["ar_coeff_shift"], "AR shift (divisor = 2^shift)"
        )
        self._gs_shift = create_spin(
            0,
            3,
            P_DEFAULTS["grain_scale_shift"],
            "Grain scale shift (Gaussian pre-scale)",
        )

        for label, widget in [
            ("ar_coeff_lag:", self._ar_lag),
            ("ar_coeff_shift:", self._ar_shift),
            ("grain_scale_sh:", self._gs_shift),
        ]:
            parent.addLayout(create_row(label, widget))

        self._ar_lag.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())
        self._ar_shift.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())
        self._gs_shift.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())

    def _build_scaling_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("SCALING"))

        self._sc_shift = create_spin(
            8,
            11,
            P_DEFAULTS["scaling_shift"],
            "Scaling shift (intensity divisor 2^shift).\n"
            "Lower = stronger grain (8 = high, 11 = subtle).",
        )
        self._sc_shift.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())
        parent.addLayout(create_row("scaling_shift:", self._sc_shift))

    def _build_chroma_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("CHROMA LINK"))

        self._chroma_from_luma = QCheckBox("chroma_from_luma")
        self._chroma_from_luma.setToolTip(
            "Copy chroma scaling curve directly from luma."
        )
        self._chroma_from_luma.setChecked(False)
        self._chroma_from_luma.stateChanged.connect(
            lambda: self.sidebar._on_p_param_changed()
        )
        self._chroma_from_luma.stateChanged.connect(self._update_chroma_spinbox_state)
        parent.addWidget(self._chroma_from_luma)

        self._overlap_flag = QCheckBox("overlap_flag")
        self._overlap_flag.setToolTip("Enable film grain block overlapping.")
        self._overlap_flag.setChecked(True)
        self._overlap_flag.stateChanged.connect(
            lambda: self.sidebar._on_p_param_changed()
        )
        parent.addWidget(self._overlap_flag)

        parent.addWidget(section_label("── Cb ──"))
        self._cb_mult = create_spin(0, 255, P_DEFAULTS["cb_mult"], "Cb chroma mult")
        self._cb_luma_mult = create_spin(
            0, 255, P_DEFAULTS["cb_luma_mult"], "Cb luma multiplier (192 = match luma)"
        )
        self._cb_offset = create_spin(0, 511, P_DEFAULTS["cb_offset"], "Cb offset")
        for label, w in [
            ("cb_mult:", self._cb_mult),
            ("cb_luma_mult:", self._cb_luma_mult),
            ("cb_offset:", self._cb_offset),
        ]:
            parent.addLayout(create_row(label, w))
            w.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())

        parent.addWidget(section_label("── Cr ──"))
        self._cr_mult = create_spin(0, 255, P_DEFAULTS["cr_mult"], "Cr chroma mult")
        self._cr_luma_mult = create_spin(
            0, 255, P_DEFAULTS["cr_luma_mult"], "Cr luma multiplier (192 = match luma)"
        )
        self._cr_offset = create_spin(0, 511, P_DEFAULTS["cr_offset"], "Cr offset")
        for label, w in [
            ("cr_mult:", self._cr_mult),
            ("cr_luma_mult:", self._cr_luma_mult),
            ("cr_offset:", self._cr_offset),
        ]:
            parent.addLayout(create_row(label, w))
            w.valueChanged.connect(lambda: self.sidebar._on_p_param_changed())

        self._update_chroma_spinbox_state()

    def _update_chroma_spinbox_state(self):
        is_linked = self._chroma_from_luma.isChecked()
        for w in [
            self._cb_mult,
            self._cb_luma_mult,
            self._cb_offset,
            self._cr_mult,
            self._cr_luma_mult,
            self._cr_offset,
        ]:
            w.setEnabled(not is_linked)

    def update_p_params_dict(self, d: dict):
        d.update(
            {
                "ar_coeff_lag": self._ar_lag.value(),
                "ar_coeff_shift": self._ar_shift.value(),
                "grain_scale_shift": self._gs_shift.value(),
                "scaling_shift": self._sc_shift.value(),
                "chroma_scaling_from_luma": int(self._chroma_from_luma.isChecked()),
                "overlap_flag": int(self._overlap_flag.isChecked()),
                "cb_mult": self._cb_mult.value(),
                "cb_luma_mult": self._cb_luma_mult.value(),
                "cb_offset": self._cb_offset.value(),
                "cr_mult": self._cr_mult.value(),
                "cr_luma_mult": self._cr_luma_mult.value(),
                "cr_offset": self._cr_offset.value(),
            }
        )

    def load_p_params_dict(self, p: dict):
        p = fgs_parser.get_p_params(p)

        self._ar_lag.setValue(p["ar_coeff_lag"])
        self._ar_shift.setValue(p["ar_coeff_shift"])
        self._gs_shift.setValue(p["grain_scale_shift"])
        self._sc_shift.setValue(p["scaling_shift"])
        self._chroma_from_luma.setChecked(bool(p.get("chroma_scaling_from_luma", 0)))
        self._overlap_flag.setChecked(bool(p.get("overlap_flag", 1)))
        self._cb_mult.setValue(p["cb_mult"])
        self._cb_luma_mult.setValue(p["cb_luma_mult"])
        self._cb_offset.setValue(p["cb_offset"])
        self._cr_mult.setValue(p["cr_mult"])
        self._cr_luma_mult.setValue(p["cr_luma_mult"])
        self._cr_offset.setValue(p["cr_offset"])

        self._update_chroma_spinbox_state()

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
                "sum(cY) / 2^ar_shift > 1.0 → AR gain is unstable.\n"
                "Increase ar_coeff_shift to stabilize."
            )
        else:
            self._ar_shift.setStyleSheet("")
            self._ar_shift.setToolTip("AR shift (divisor = 2^shift)")
