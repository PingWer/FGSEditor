from __future__ import annotations
import re
from collections import defaultdict
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QApplication,
    QStyle,
)
from PySide6.QtGui import QFont, QFontDatabase, QColor, QBrush
from PySide6.QtCore import Qt, QTimer


def categorize_warning(w: str) -> tuple[str, str]:
    w_clean = w.strip()

    if "outside standard TV Range" in w_clean:
        m = re.match(r"^(Event \d+):\s*Channel '([^']+)'", w_clean)
        cat = "Points outside standard TV Range [Full Range enabled]"
        det = f"{m.group(1)} ({m.group(2)} channel)" if m else w_clean
        return cat, det

    if "out of AFGS1 spec range" in w_clean:
        m = re.match(r"^(Event \d+):\s*Parameter '([^']+)' \(([^)]+)\).*clamped to (\d+)", w_clean)
        if m:
            return f"Parameter '{m.group(2)}' clamped to AFGS1 spec range", f"{m.group(1)}: {m.group(3)} -> {m.group(4)}"
        return "Parameter clamped to AFGS1 spec range", w_clean

    if "Missing line '" in w_clean and "for lag" in w_clean:
        m = re.match(r"^(Event \d+):\s*Missing line '([^']+)'", w_clean)
        return (f"Missing AR line '{m.group(2)}' (zero-padded)" if m else "Missing AR coefficient line"), (m.group(1) if m else w_clean)

    if "contained coefficients outside AFGS1 range" in w_clean:
        m = re.match(r"^(Event \d+):\s*Line '([^']+)'", w_clean)
        return (f"AR line '{m.group(2)}' clamped to [-128..127]" if m else "AR coefficients clamped"), (m.group(1) if m else w_clean)

    if "coefficients (expected" in w_clean:
        m = re.match(r"^(Event \d+):\s*Line '([^']+)'", w_clean)
        return (f"AR line '{m.group(2)}' count adjusted to lag" if m else "AR coefficient count adjusted"), (m.group(1) if m else w_clean)

    if "Negative start timestamp" in w_clean:
        return "Negative start timestamp clamped to 0", w_clean

    if "End timestamp" in w_clean and "<= start timestamp" in w_clean:
        return "End timestamp <= start timestamp adjusted", w_clean

    if "UINT64_MAX dummy" in w_clean or "Extreme dummy timestamp" in w_clean:
        return "Extreme dummy timestamp clamped", w_clean

    if "Overlapping event timestamps" in w_clean:
        return "Overlapping event timestamps aligned", w_clean

    if "Gap detected between" in w_clean:
        return "Timestamp gap between events filled", w_clean

    if "format identifier" in w_clean.lower():
        return "Format identifier normalized to 'filmgrn1'", w_clean

    if "Missing line 'p'" in w_clean:
        return "Missing 'p' parameter line (populated defaults)", w_clean

    if "chroma_scaling_from_luma" in w_clean:
        return "Chroma curves cleared (chroma_scaling_from_luma active)", w_clean

    m = re.match(r"^(Event \d+):\s*(.*)", w_clean)
    if m:
        return m.group(2), m.group(1)

    return "General Normalization Notices", w_clean


class NonStandardFgsDialog(QDialog):
    MAX_CHILDREN_PER_CAT = 250

    def __init__(self, parent=None, warnings: list[str] | None = None) -> None:
        super().__init__(parent)
        self.raw_warnings = warnings or []
        self.setWindowTitle("FGS Syntax Warnings")
        self.setMinimumSize(680, 420)
        self.resize(750, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        header_layout = QHBoxLayout()
        header_icon = QLabel()
        warning_icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning)
        header_icon.setPixmap(warning_icon.pixmap(32, 32))
        header_layout.addWidget(header_icon, stretch=0)

        header_text = QLabel(
            "The loaded FGS file contains non-standard syntax.\n"
            "The table was automatically normalized to comply with AFGS1. Warnings are grouped below:"
        )
        header_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #f59e0b;")
        header_text.setWordWrap(True)
        header_layout.addWidget(header_text, stretch=1)
        layout.addLayout(header_layout)

        self.groups: dict[str, list[str]] = defaultdict(list)
        if not self.raw_warnings:
            self.groups["Notice"].append("No specific warnings recorded.")
        else:
            for w in self.raw_warnings:
                cat, det = categorize_warning(w)
                self.groups[cat].append(det)

        # Tree view
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Issue Type / Event Details", "Count"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)

        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(9)
        self.tree.setFont(font)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #121214;
                color: #e4e4e7;
                border: 1px solid #27272a;
                border-radius: 4px;
                padding: 4px;
            }
            QTreeWidget::item {
                padding: 3px 4px;
            }
            QTreeWidget::item:hover {
                background-color: #27272a;
            }
            QTreeWidget::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #18181b;
                color: #a1a1aa;
                padding: 4px 8px;
                border: 1px solid #27272a;
                font-weight: bold;
            }
        """)

        layout.addWidget(self.tree, stretch=1)

        amber_brush = QBrush(QColor("#fbbf24"))
        muted_brush = QBrush(QColor("#a1a1aa"))
        sub_brush = QBrush(QColor("#d4d4d8"))

        for cat_title, items in sorted(self.groups.items(), key=lambda x: -len(x[1])):
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setIcon(0, warning_icon)
            cat_item.setText(0, cat_title)
            cat_item.setText(1, f"[{len(items):,} events]")
            cat_item.setForeground(0, amber_brush)
            cat_item.setForeground(1, amber_brush)
            f = cat_item.font(0)
            f.setBold(True)
            cat_item.setFont(0, f)
            cat_item.setFont(1, f)

            disp_count = min(len(items), self.MAX_CHILDREN_PER_CAT)
            for i in range(disp_count):
                child = QTreeWidgetItem(cat_item)
                child.setText(0, f"• {items[i]}")
                child.setForeground(0, sub_brush)

            if len(items) > self.MAX_CHILDREN_PER_CAT:
                rem = len(items) - self.MAX_CHILDREN_PER_CAT
                more_item = QTreeWidgetItem(cat_item)
                more_item.setText(0, f"• ... and {rem:,} more occurrences (use 'Copy Full Log' to view all)")
                more_item.setForeground(0, muted_brush)
                mf = more_item.font(0)
                mf.setItalic(True)
                more_item.setFont(0, mf)

        bottom_bar = QHBoxLayout()

        expand_btn = QPushButton("Expand All")
        expand_btn.clicked.connect(self.tree.expandAll)
        expand_btn.setStyleSheet("background-color: #27272a; color: #e4e4e7; padding: 5px 10px; border-radius: 4px;")
        bottom_bar.addWidget(expand_btn)

        collapse_btn = QPushButton("Collapse All")
        collapse_btn.clicked.connect(self.tree.collapseAll)
        collapse_btn.setStyleSheet("background-color: #27272a; color: #e4e4e7; padding: 5px 10px; border-radius: 4px;")
        bottom_bar.addWidget(collapse_btn)

        copy_summary_btn = QPushButton("Copy Summary")
        copy_summary_btn.clicked.connect(self._copy_summary)
        copy_summary_btn.setStyleSheet("background-color: #27272a; color: #e4e4e7; padding: 5px 10px; border-radius: 4px;")
        bottom_bar.addWidget(copy_summary_btn)

        copy_all_btn = QPushButton("Copy Full Log")
        copy_all_btn.clicked.connect(self._copy_all)
        copy_all_btn.setStyleSheet("background-color: #27272a; color: #e4e4e7; padding: 5px 10px; border-radius: 4px;")
        bottom_bar.addWidget(copy_all_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #10b981; font-weight: bold; margin-left: 8px;")
        bottom_bar.addWidget(self.status_lbl)

        bottom_bar.addStretch(1)

        ok_btn = QPushButton("OK")
        ok_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        ok_btn.setMinimumWidth(90)
        ok_btn.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px;"
        )
        ok_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(ok_btn)

        layout.addLayout(bottom_bar)

    def _copy_summary(self):
        lines = [f"FGS Normalization Summary ({len(self.raw_warnings):,} total warnings):"]
        for cat, items in sorted(self.groups.items(), key=lambda x: -len(x[1])):
            lines.append(f" - {cat}: {len(items):,} occurrences")
        QApplication.clipboard().setText("\n".join(lines))
        self._show_status("Summary copied to clipboard!")

    def _copy_all(self):
        formatted = "\n".join(self.raw_warnings) if self.raw_warnings else "No warnings."
        QApplication.clipboard().setText(formatted)
        self._show_status("Full log copied to clipboard!")

    def _show_status(self, msg: str):
        self.status_lbl.setText(msg)
        QTimer.singleShot(3000, lambda: self.status_lbl.setText(""))


def ask_static_dynamic_mode(parent=None, title: str = "Binary Export Mode") -> bool | None:
    from PySide6.QtCore import Qt

    mode_dialog = QDialog(parent)
    mode_dialog.setWindowTitle(title)
    mode_dialog.setMinimumWidth(460)
    layout = QVBoxLayout(mode_dialog)
    layout.setSpacing(12)

    title_lbl = QLabel("<b>Select binary export mode:</b>")
    title_lbl.setTextFormat(Qt.RichText)
    layout.addWidget(title_lbl)

    static_desc = QLabel("<b>Static</b> — Constant seed across frames.")
    static_desc.setWordWrap(True)
    layout.addWidget(static_desc)

    dynamic_desc = QLabel("<b>Dynamic</b> — Unique seed per frame.")
    dynamic_desc.setWordWrap(True)
    layout.addWidget(dynamic_desc)

    btn_layout = QHBoxLayout()
    static_btn = QPushButton("Static")
    static_btn.setMinimumWidth(90)
    dynamic_btn = QPushButton("Dynamic")
    dynamic_btn.setMinimumWidth(90)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.setMinimumWidth(80)
    btn_layout.addWidget(static_btn)
    btn_layout.addWidget(dynamic_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    result = [None]

    def _pick_static():
        result[0] = True
        mode_dialog.accept()

    def _pick_dynamic():
        result[0] = False
        mode_dialog.accept()

    static_btn.clicked.connect(_pick_static)
    dynamic_btn.clicked.connect(_pick_dynamic)
    cancel_btn.clicked.connect(mode_dialog.reject)

    if mode_dialog.exec() != QDialog.Accepted or result[0] is None:
        return None
    return result[0]

