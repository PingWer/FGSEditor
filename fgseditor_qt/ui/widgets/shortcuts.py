SHORTCUTS = [
    ("Left Click + Drag", "Move point", ""),
    ("Left Click + Shift", "Lock axis", ""),
    ("Double Left Click", "Edit point", ""),
    ("Right Click", "Add / Remove point", ""),
    ("Middle Click + Drag", "Pan", " — In Event Editor Only"),
    ("Right Click + Drag", "Pan", " — In Timeline Editor Only"),
    ("CTRL + Scroll", "Zoom", ""),
    ("CTRL + Z", "Undo", ""),
    ("CTRL + Y", "Redo", ""),
]


def show_shortcuts(parent=None):
    from PySide6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QPushButton,
        QLabel,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QAbstractItemView,
    )
    from PySide6.QtCore import Qt

    dialog = QDialog(parent)
    dialog.setWindowTitle("Keyboard & Mouse Shortcuts")
    dialog.setMinimumSize(560, 380)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)

    header = QLabel("Keyboard & Mouse Shortcuts")
    header.setStyleSheet(
        "font-size: 16px; font-weight: bold; margin-bottom: 4px; color: #4da6ff;"
    )
    layout.addWidget(header)

    table = QTableWidget(len(SHORTCUTS), 3)
    table.setHorizontalHeaderLabels(["Shortcut / Input", "Action", "Scope"])
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(
        "QTableWidget { background-color: #1e1e1e; color: #ffffff; gridline-color: #333333; alternate-background-color: #252525; border: 1px solid #444444; border-radius: 4px; }"
        "QHeaderView::section { background-color: #2a2a2a; color: #4da6ff; font-weight: bold; padding: 6px; border: 1px solid #333333; }"
        "QTableWidget::item { padding: 6px; }"
    )

    for row, (label, desc, other) in enumerate(SHORTCUTS):
        scope = other.replace(" — ", "").strip()
        if not scope:
            scope = "Global"

        item_shortcut = QTableWidgetItem(label)
        item_shortcut.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        item_action = QTableWidgetItem(desc)
        item_action.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        item_scope = QTableWidgetItem(scope)
        item_scope.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        table.setItem(row, 0, item_shortcut)
        table.setItem(row, 1, item_action)
        table.setItem(row, 2, item_scope)

    layout.addWidget(table)

    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dialog.accept)
    close_btn.setStyleSheet(
        "QPushButton { padding: 8px 24px; background-color: #2a82da; color: white; border-radius: 4px; font-weight: bold; }"
        "QPushButton:hover { background-color: #3294f0; }"
    )
    layout.addWidget(close_btn, alignment=Qt.AlignCenter)

    dialog.exec()


def show_credits(parent=None):
    from PySide6.QtWidgets import QMessageBox

    msg = QMessageBox(parent)
    msg.setWindowTitle(" ")
    msg.setText(
        "FGSEditor v5.0.0\n\n"
        'Copyright \u00a9 2026 Michele "PingWer" Cosentino\n\n'
        'Collaborators:\nManuel "Mhanz3500" Moscardi'
    )
    msg.setStyleSheet("QLabel { font-size: 15px; font-weight: bold; }")
    msg.exec()


def show_notice(parent=None):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel
    from PySide6.QtCore import Qt
    import os
    from fgseditor_qt.core.app_paths import get_base_dir

    dialog = QDialog(parent)
    dialog.setWindowTitle("Licenses && Copyright")
    dialog.setMinimumSize(800, 600)

    layout = QVBoxLayout(dialog)

    header = QLabel("FGSEditor - Project Licenses and Copyright")
    header.setStyleSheet(
        "font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #4da6ff;"
    )
    layout.addWidget(header)

    from PySide6.QtWidgets import QTextBrowser

    text_edit = QTextBrowser()
    text_edit.setOpenExternalLinks(True)
    text_edit.setStyleSheet(
        "QTextBrowser { background-color: #1e1e1e; color: #cccccc; font-size: 14px; border: 1px solid #444; padding: 10px; }"
    )

    notice_path = os.path.join(get_base_dir(), "NOTICE.md")
    if os.path.exists(notice_path):
        try:
            with open(notice_path, "r", encoding="utf-8") as f:
                content = f.read()
                text_edit.setMarkdown(content)
        except Exception as e:
            text_edit.setMarkdown(f"**Error loading NOTICE.md:** {e}")
    else:
        text_edit.setMarkdown(
            "# NOTICE.md not found\nThe file was not found in the application directory."
        )

    layout.addWidget(text_edit)

    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dialog.accept)
    close_btn.setStyleSheet(
        "QPushButton { padding: 8px 20px; background-color: #2a82da; color: white; border-radius: 4px; font-weight: bold; }"
        "QPushButton:hover { background-color: #3294f0; }"
    )
    layout.addWidget(close_btn, alignment=Qt.AlignCenter)

    dialog.exec()


def open_github():
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl

    QDesktopServices.openUrl(QUrl("https://github.com/PingWer/FGSEditor"))


def create_standard_menu(
    parent, show_credits_cb=None, open_github_cb=None, show_notice_cb=None
):
    from PySide6.QtWidgets import QMenuBar, QMenu

    if show_credits_cb is None:

        def show_credits_cb():
            show_credits(parent)

    if open_github_cb is None:
        open_github_cb = open_github

    if show_notice_cb is None:

        def show_notice_cb():
            show_notice(parent)

    menu_bar = QMenuBar()
    menu_bar.setStyleSheet(
        "QMenuBar { background-color: #1e1e1e; color: #dddddd; font-size: 13px; }"
        "QMenuBar::item { padding: 4px 10px; }"
        "QMenuBar::item:selected { background-color: #2a82da; border-radius: 4px; }"
        "QMenu { background-color: #2d2d2d; border: 1px solid #444; border-radius: 6px; padding: 4px; }"
        "QMenu::item { padding: 6px 20px; color: white; border-radius: 3px; }"
        "QMenu::item:selected { background-color: #2a82da; }"
    )

    shortcuts_menu = QMenu("Shortcuts", menu_bar)
    action_view_shortcuts = shortcuts_menu.addAction("Keyboard & Mouse Shortcuts...")
    action_view_shortcuts.triggered.connect(lambda: show_shortcuts(parent))
    menu_bar.addMenu(shortcuts_menu)

    settings_menu = QMenu("Settings", menu_bar)
    action_settings = settings_menu.addAction("Preferences...")
    
    def _open_settings():
        from fgseditor_qt.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent)
        dlg.exec()
        
    action_settings.triggered.connect(_open_settings)
    menu_bar.addMenu(settings_menu)

    tools_menu = QMenu("Tools", menu_bar)

    create_menu = tools_menu.addMenu("Create FGS")
    action_manual = create_menu.addAction("Manual Creation")
    action_auto = create_menu.addAction("Automatic Creation")

    def _find_main_ui(obj):
        curr = obj
        visited = set()
        while curr is not None and id(curr) not in visited:
            visited.add(id(curr))
            if hasattr(curr, "create_static_fgs") and hasattr(curr, "load_file_from_path"):
                return curr
            if hasattr(curr, "main_ui") and curr.main_ui is not None:
                curr = curr.main_ui
            elif hasattr(curr, "dynamic_timeline_ui") and curr.dynamic_timeline_ui is not None:
                curr = curr.dynamic_timeline_ui
            elif hasattr(curr, "parent") and callable(curr.parent):
                curr = curr.parent()
            else:
                break
        return None

    def _open_manual():
        if hasattr(parent, "create_static_fgs"):
            parent.create_static_fgs()
        else:
            main_win = _find_main_ui(parent)
            if main_win is not None and hasattr(main_win, "create_static_fgs"):
                if hasattr(parent, "close") and parent != main_win:
                    if not parent.close():
                        return
                main_win.create_static_fgs()
                main_win.show()
                main_win.raise_()
                main_win.activateWindow()

    def _open_auto():
        main_win = _find_main_ui(parent)
        target = parent if hasattr(parent, "load_file_from_path") else main_win

        if hasattr(parent, "open_auto_create_dialog"):
            parent.open_auto_create_dialog()
        elif main_win is not None and hasattr(main_win, "open_auto_create_dialog"):
            main_win.open_auto_create_dialog()
        else:
            from fgseditor_qt.ui.dialogs.fgs_auto_create_dialog import FgsAutoCreateDialog
            dlg = FgsAutoCreateDialog(parent)
            if target is not None and hasattr(target, "load_file_from_path"):
                def _on_auto_loaded(path):
                    if parent != main_win and hasattr(parent, "close"):
                        if not parent.close():
                            return
                    target.load_file_from_path(path)
                dlg.fgs_loaded.connect(_on_auto_loaded)
            dlg.exec()

    action_manual.triggered.connect(_open_manual)
    action_auto.triggered.connect(_open_auto)

    action_optimize = tools_menu.addAction("Optimize FGS...")

    def _open_optimizer():
        main_win = _find_main_ui(parent)
        target = parent if hasattr(parent, "load_file_from_path") else main_win

        if hasattr(parent, "open_optimizer_dialog"):
            parent.open_optimizer_dialog()
        elif main_win is not None and hasattr(main_win, "open_optimizer_dialog"):
            main_win.open_optimizer_dialog()
        else:
            from fgseditor_qt.ui.dialogs.fgs_optimizer_dialog import FgsOptimizerDialog
            dlg = FgsOptimizerDialog(parent)
            if target is not None and hasattr(target, "load_file_from_path"):
                def _on_opt_loaded(path):
                    if parent != main_win and hasattr(parent, "close"):
                        if not parent.close():
                            return
                    target.load_file_from_path(path)
                dlg.fgs_loaded.connect(_on_opt_loaded)
            dlg.exec()

    action_optimize.triggered.connect(_open_optimizer)
    menu_bar.addMenu(tools_menu)

    info_menu = QMenu("Info", menu_bar)

    info_menu.addAction("Keyboard Shortcuts...").triggered.connect(
        lambda: show_shortcuts(parent)
    )
    info_menu.addAction("Credits").triggered.connect(show_credits_cb)
    info_menu.addAction("GitHub").triggered.connect(open_github_cb)
    info_menu.addAction("Licenses && Copyright").triggered.connect(show_notice_cb)
    menu_bar.addMenu(info_menu)

    return menu_bar
