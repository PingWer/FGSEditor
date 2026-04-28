from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QSpinBox

def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #569cd6; font-size: 10px; font-weight: bold; "
        "margin-top: 8px; margin-bottom: 2px; letter-spacing: 1px;"
    )
    return lbl

def create_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.setContentsMargins(0, 0, 0, 0)
    hb.setSpacing(6)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color: #cccccc; font-size: 11px;")
    lbl.setMinimumWidth(115)
    hb.addWidget(lbl, stretch=0)
    hb.addWidget(widget, stretch=1)
    return hb

def create_spin(min_val: int, max_val: int, default: int, tooltip: str = "") -> QSpinBox:
    sp = QSpinBox()
    sp.setRange(min_val, max_val)
    sp.setValue(default)
    if tooltip:
        sp.setToolTip(tooltip)
    return sp
