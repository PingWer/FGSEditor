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
        "FGSEditor v2.0.1\n\n"
        'Copyright \u00a9 2026 Michele "PingWer" Cosentino\n\n'
        'Collaborators:\nManuel "Mhanz3500" Moscardi'
    )
    msg.setStyleSheet("QLabel { font-size: 15px; font-weight: bold; }")
    msg.exec()


def open_github():
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl

    QDesktopServices.openUrl(QUrl("https://github.com/PingWer/FGSEditor"))


def create_standard_menu(parent, show_credits_cb=None, open_github_cb=None):
    from PySide6.QtWidgets import QMenuBar, QMenu

    if show_credits_cb is None:

        def show_credits_cb():
            show_credits(parent)

    if open_github_cb is None:
        open_github_cb = open_github

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
    menu_bar.addMenu(info_menu)

    return menu_bar
