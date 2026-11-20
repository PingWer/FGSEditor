from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QWidget,
)


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #569cd6; font-size: 10px; font-weight: bold; "
        "margin-top: 8px; margin-bottom: 2px; letter-spacing: 1px;"
    )
    return lbl


def create_info_icon(tooltip: str) -> QLabel:
    badge = QLabel("i")
    badge.setFixedSize(16, 16)
    badge.setAlignment(Qt.AlignCenter)
    badge.setToolTip(tooltip)
    badge.setCursor(Qt.WhatsThisCursor)
    badge.setStyleSheet(
        "QLabel { "
        "  background-color: #2b3350; color: #7cc4ff; "
        "  border: 1px solid #4a5a88; border-radius: 8px; "
        "  font-size: 10px; font-weight: bold; font-style: italic; "
        "}"
        "QLabel:hover { "
        "  background-color: #3a466e; color: #ffffff; border-color: #7cc4ff; "
        "}"
    )
    return badge


def create_row(
    label_text: str, widget: QWidget, info_tooltip: str | None = None
) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.setContentsMargins(0, 0, 0, 0)
    hb.setSpacing(6)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color: #cccccc; font-size: 11px;")
    lbl.setMinimumWidth(115)
    hb.addWidget(lbl, stretch=0)
    hb.addWidget(widget, stretch=1)
    if info_tooltip:
        hb.addWidget(create_info_icon(info_tooltip), stretch=0)
    return hb


def create_spin(min_val: int, max_val: int, default: int, tooltip: str = "") -> QSpinBox:
    sp = QSpinBox()
    sp.setRange(min_val, max_val)
    sp.setValue(default)
    if tooltip:
        sp.setToolTip(tooltip)
    return sp


def ask_fix_clipping_options(
    parent: QWidget | None, *, is_dynamic: bool = False
) -> tuple[bool, bool]:
    """Prompt the user before Fix Clipping to choose whether endpoints should also be fixed.

    Returns ``(proceed, fix_endpoints)``. The endpoint option is checked by default.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Fix Clipping")
    scope = "all events and channels" if is_dynamic else "the current channel"
    box.setText(f"Fix clipping across {scope}?")
    box.setInformativeText(
        "Interior points are shifted horizontally to eliminate clipping.\n"
        "When 'Also fix endpoints' is enabled:\n"
        "• Curves with 3+ points set clipping endpoints to strength 0.\n"
        "• Curves with 2 points add safety-ramp points at 0 on the borders to preserve grain."
    )
    cb = QCheckBox("Also fix endpoints (first and last point)")
    cb.setChecked(True)
    box.setCheckBox(cb)
    box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    box.setDefaultButton(QMessageBox.Ok)
    if box.exec() != QMessageBox.Ok:
        return False, False
    return True, cb.isChecked()
