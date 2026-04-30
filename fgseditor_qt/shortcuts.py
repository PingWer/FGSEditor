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


def show_credits(parent=None):
    from PySide6.QtWidgets import QMessageBox

    msg = QMessageBox(parent)
    msg.setWindowTitle(" ")
    msg.setText(
        "FGSEditor v3.0.0\n\n"
        'Copyright \u00a9 2026 Michele "PingWer" Cosentino\n\n'
        'Collaborators:\nManuel "Mhanz3500" Moscardi'
    )
    msg.setStyleSheet("QLabel { font-size: 15px; font-weight: bold; }")
    msg.exec()


def show_notice(parent=None):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel
    from PySide6.QtCore import Qt
    import os
    from .app_paths import get_base_dir

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
    shortcuts_menu.setStyleSheet("QMenu::item { font-size: 11px; }")
    for label, desc, other in SHORTCUTS:
        act = shortcuts_menu.addAction(f"{label}  —  {desc}{other}")
        act.setEnabled(False)
    menu_bar.addMenu(shortcuts_menu)

    settings_menu = QMenu("Settings", menu_bar)
    settings_menu.addAction("Coming soon…").setEnabled(False)
    menu_bar.addMenu(settings_menu)

    info_menu = QMenu("Info", menu_bar)
    info_menu.addAction("Credits").triggered.connect(show_credits_cb)
    info_menu.addAction("GitHub").triggered.connect(open_github_cb)
    info_menu.addAction("Licenses && Copyright").triggered.connect(show_notice_cb)
    menu_bar.addMenu(info_menu)

    return menu_bar
