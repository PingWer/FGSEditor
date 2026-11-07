from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QComboBox,
    QPushButton,
    QFileDialog,
    QDialog,
    QRadioButton,
    QButtonGroup,
    QHBoxLayout,
    QMessageBox,
    QLabel,
    QFrame,
)

from .utils import section_label, create_row
from fgseditor_qt.core.fgs_templates import list_templates, load_template_event, import_user_template


class ApplyTemplateDialog(QDialog):
    def __init__(self, parent=None, template_name=""):
        super().__init__(parent)
        self.setWindowTitle("Apply Template")
        self.setModal(True)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        lbl = QLabel(f"Template: {template_name}\nSelect parameters to copy:")
        layout.addWidget(lbl)

        self.rg = QButtonGroup(self)

        self.radio_all = QRadioButton("All Parameters (S, C, P)")
        self.radio_s_only = QRadioButton("Scaling Curves only (sY, sCb, sCr)")
        self.radio_c_only = QRadioButton("AR Coefficients only (cY, cCb, cCr)")

        self.radio_all.setChecked(True)

        self.rg.addButton(self.radio_all, 0)
        self.rg.addButton(self.radio_s_only, 1)
        self.rg.addButton(self.radio_c_only, 2)

        layout.addWidget(self.radio_all)
        layout.addWidget(self.radio_s_only)
        layout.addWidget(self.radio_c_only)

        btns_layout = QHBoxLayout()
        btns_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.accept)

        btns_layout.addWidget(cancel_btn)
        btns_layout.addWidget(apply_btn)

        layout.addLayout(btns_layout)

    def get_mode(self):
        return self.rg.checkedId()


class PanelTemplates(QWidget):
    def __init__(self, parent_sidebar=None) -> None:
        super().__init__()
        self.sidebar = parent_sidebar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._build_templates_section(layout)
        layout.addStretch(1)

    def _build_templates_section(self, parent: QVBoxLayout) -> None:
        parent.addWidget(section_label("TEMPLATES"))

        self._system_combo = QComboBox()
        self._system_combo.addItem("Select System Template...", "")
        for t in list_templates("system"):
            self._system_combo.addItem(t, ("system", t))
        self._system_combo.currentIndexChanged.connect(self._on_system_selected)

        parent.addLayout(create_row("System Template:", self._system_combo))

        self._user_combo = QComboBox()
        self._refresh_user_combo()
        self._user_combo.currentIndexChanged.connect(self._on_user_selected)

        parent.addLayout(create_row("User Template:", self._user_combo))

        self._upload_btn = QPushButton("Import Template...")
        self._upload_btn.clicked.connect(self._on_upload)
        parent.addWidget(self._upload_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333355;")
        parent.addWidget(sep)

    def _refresh_user_combo(self):
        self._user_combo.blockSignals(True)
        self._user_combo.clear()
        self._user_combo.addItem("Select User Template...", "")
        for t in list_templates("user"):
            self._user_combo.addItem(t, ("user", t))
        self._user_combo.blockSignals(False)

    def _on_upload(self):
        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select FGS Template",
            get_dialog_dir("last_template_dir"),
            "FGS Files (*.txt *.tbl);;All Files (*)",
        )
        if filepath:
            update_dialog_dir("last_template_dir", filepath)
            from fgseditor_qt.core.fgs_templates import get_user_dir
            import os
            dst_name = os.path.basename(filepath)
            dst_path = os.path.join(get_user_dir(), dst_name)
            if os.path.exists(dst_path) and os.path.abspath(filepath) != os.path.abspath(dst_path):
                reply = QMessageBox.question(
                    self,
                    "Overwrite Template?",
                    f"A user template named '{dst_name}' already exists.\n\nDo you want to overwrite it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
            try:
                name = import_user_template(filepath)
                if name:
                    self._refresh_user_combo()
                    idx = self._user_combo.findText(name)
                    if idx >= 0:
                        self._user_combo.setCurrentIndex(idx)
                else:
                    QMessageBox.warning(self, "Error", "Could not import template.")
            except Exception as e:
                QMessageBox.warning(self, "Import Error", f"Could not import template:\n{str(e)}")

    def _on_system_selected(self, idx):
        if idx > 0:
            data = self._system_combo.itemData(idx)
            self._system_combo.setCurrentIndex(0)
            self._apply_template(data[0], data[1])

    def _on_user_selected(self, idx):
        if idx > 0:
            data = self._user_combo.itemData(idx)
            self._user_combo.setCurrentIndex(0)
            self._apply_template(data[0], data[1])

    def _apply_template(self, folder_type: str, name: str):
        evt = load_template_event(folder_type, name)
        if not evt:
            QMessageBox.warning(self, "Error", "Could not load template.")
            return

        dlg = ApplyTemplateDialog(self, template_name=name)
        if dlg.exec() == QDialog.Accepted:
            mode = dlg.get_mode()
            self.sidebar.apply_template_to_current(evt, mode)
