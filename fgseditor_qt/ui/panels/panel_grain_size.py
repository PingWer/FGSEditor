from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QFrame

from .utils import section_label, create_row
from fgseditor_qt.core.fgs_parser import available_grain_presets


class PanelGrainSize(QWidget):
    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._build_grain_size_section(layout)

        layout.addStretch(1)

    def _build_grain_size_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("GRAIN MORPHOLOGY"))

        self._grain_size_combo = QComboBox()
        self._grain_size_combo.addItem("Manual/Original", "-1")
        sizes = available_grain_presets()
        for s in sizes:
            self._grain_size_combo.addItem(f"Preset: {s}", s)

        self._grain_size_combo.setToolTip(
            "Select 'Manual/Original' to use current event values,\n"
            "or select a grain size preset (0–13)."
        )
        self._grain_size_combo.currentIndexChanged.connect(
            lambda idx: self.sidebar._on_grain_size_changed(
                self._grain_size_combo.itemData(idx)
            )
        )
        parent.addLayout(create_row("Grain Size:", self._grain_size_combo))

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def get_grain_size(self) -> str:
        return self._grain_size_combo.currentData()

    def set_grain_size(self, size_id: str) -> None:
        idx = self._grain_size_combo.findData(size_id)
        if idx >= 0:
            self._grain_size_combo.setCurrentIndex(idx)
        else:
            self._grain_size_combo.setCurrentIndex(0)
