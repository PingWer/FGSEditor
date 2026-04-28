from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QFrame,
    QMessageBox,
)

from .utils import section_label, create_row, create_spin
from ..svt_photon_noise import TFS, FILM_FORMATS


class PanelPhotonNoise(QWidget):
    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._build_photon_noise_section(layout)
        layout.addStretch(1)

    def _build_photon_noise_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("PHOTON NOISE"))

        self._pn_enable_chk = QCheckBox("Apply Photon Noise")
        self._pn_enable_chk.setToolTip(
            "Overwrite luma values using photon noise values"
        )
        self._pn_enable_chk.setChecked(False)
        self._pn_enable_chk.clicked.connect(self._on_pn_enable_toggled)
        parent.addWidget(self._pn_enable_chk)

        self._pn_width = QLineEdit("1920")
        self._pn_width.setEnabled(False)
        self._pn_height = QLineEdit("1080")
        self._pn_height.setEnabled(False)
        self._pn_iso = create_spin(1, 100000, 400)
        self._pn_iso.setEnabled(False)

        self._pn_tf = QComboBox()
        self._pn_tf.addItems(list(TFS.keys()))
        self._pn_tf.setCurrentText("BT_1886")
        self._pn_tf.setEnabled(False)

        self._pn_range = QComboBox()
        self._pn_range.addItems(["LIMITED", "FULL"])
        self._pn_range.setCurrentText("LIMITED")
        self._pn_range.setEnabled(False)

        self._pn_format = QComboBox()
        self._pn_format.addItems(list(FILM_FORMATS.keys()))
        self._pn_format.setCurrentText("35mm")
        self._pn_format.setEnabled(False)

        parent.addLayout(create_row("Width:", self._pn_width))
        parent.addLayout(create_row("Height:", self._pn_height))
        parent.addLayout(create_row("ISO:", self._pn_iso))
        parent.addLayout(create_row("Transfer:", self._pn_tf))
        parent.addLayout(create_row("Range:", self._pn_range))
        parent.addLayout(create_row("Sensor/Film:", self._pn_format))

        self._pn_width.textChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )
        self._pn_height.textChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )
        self._pn_iso.valueChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )
        self._pn_tf.currentTextChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )
        self._pn_range.currentTextChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )
        self._pn_format.currentTextChanged.connect(
            lambda: self.sidebar._generate_and_emit_photon_noise()
        )

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def _on_pn_enable_toggled(self, checked: bool) -> None:
        if checked:
            reply = QMessageBox.question(
                self,
                "Overwrite Warning",
                "Stai per perdere i valori originali sY, sCb, sCr.\nContinuare?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                self._pn_enable_chk.setChecked(False)
                return

        state = self._pn_enable_chk.isChecked()
        self._pn_width.setEnabled(state)
        self._pn_height.setEnabled(state)
        self._pn_iso.setEnabled(state)
        self._pn_tf.setEnabled(state)
        self._pn_range.setEnabled(state)
        self._pn_format.setEnabled(state)

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
        }

    def set_state(self, state: dict) -> None:
        self._pn_width.setText(state.get("pn_width", "1920"))
        self._pn_height.setText(state.get("pn_height", "1080"))
        self._pn_iso.setValue(state.get("pn_iso", 400))
        self._pn_tf.setCurrentText(state.get("pn_tf", "BT_709"))
        self._pn_range.setCurrentText(state.get("pn_range", "LIMITED"))
        self._pn_format.setCurrentText(state.get("pn_format", "35mm"))
        self._pn_enable_chk.setChecked(state.get("pn_enabled", False))

        pn_state = self._pn_enable_chk.isChecked()
        self._pn_width.setEnabled(pn_state)
        self._pn_height.setEnabled(pn_state)
        self._pn_iso.setEnabled(pn_state)
        self._pn_tf.setEnabled(pn_state)
        self._pn_range.setEnabled(pn_state)
        self._pn_format.setEnabled(pn_state)
