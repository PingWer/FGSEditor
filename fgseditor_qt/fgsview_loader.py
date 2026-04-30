import sys
import os
import pathlib

_root = pathlib.Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPalette, QColor, QIcon  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from fgseditor_qt.main_ui import MainUI  # noqa: E402


def setup_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(18, 18, 18))
    dark_palette.setColor(QPalette.AlternateBase, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)

    dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
    dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
    dark_palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(127, 127, 127))

    app.setPalette(dark_palette)

    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #111111;
        }
        QFrame#toolbar {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
        }
        QLabel {
            background-color: transparent;
            font-size: 13px;
            color: #dddddd;
        }
        QPushButton { 
            font-size: 15px;
            padding: 8px 16px; 
            border-radius: 6px; 
            border: 1px solid #3d3d3d; 
            background-color: #2d2d2d;
            font-weight: bold;
            color: #ffffff;
        }
        QPushButton#bigButton {
            font-size: 16px;
            background-color: #2a82da;
            border-radius: 12px;
            border: none;
        }
        QPushButton#bigButton:hover { 
            background-color: #3b93eb; 
        }
        QPushButton#bigButton::menu-indicator { 
            image: none; 
        }
        QMenu {
            background-color: #2d2d2d;
            border: 1px solid #444444;
            border-radius: 8px;
            padding: 8px;
            font-size: 15px;
        }
        QMenu::item {
            padding: 8px 30px;
            color: white;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #2a82da;
        }
        QPushButton:hover { background-color: #404040; border: 1px solid #5a5a5a; }
        QPushButton:pressed { background-color: #555555; }
        QPushButton:disabled { background-color: #1a1a1a; color: #555555; border: 1px solid #222222; }
        QComboBox { 
            padding: 6px 12px; 
            border-radius: 6px; 
            border: 1px solid #3d3d3d; 
            background-color: #2d2d2d; 
        }
        QComboBox::drop-down { border: 0px; }
        QComboBox QAbstractItemView { 
            background-color: #2d2d2d; 
            color: white; 
            selection-background-color: #2a82da; 
            border: 1px solid #3d3d3d;
            outline: 0px;
        }
        QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid #4da6ff; padding: 4px; border-radius: 4px; }
        
        QCheckBox {
            spacing: 8px;
            color: #dddddd;
            font-size: 13px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            background-color: #2d2d2d;
            border: 1px solid #444444;
            border-radius: 4px;
        }
        QCheckBox::indicator:hover {
            border: 1px solid #4da6ff;
            background-color: #353535;
        }
        QCheckBox::indicator:checked {
            background-color: #2a82da;
            border: 1px solid #4da6ff;
            image: url(none); /* Fallback to handle some systems */
        }
        QCheckBox::indicator:checked:hover {
            background-color: #3b93eb;
            border: 1px solid #80bdff;
        }
        /* Custom checkmark alternative if no image: we use the background color change + border */
        
        QRadioButton {
            spacing: 8px;
            color: #dddddd;
            font-size: 13px;
        }
        QRadioButton::indicator {
            width: 18px;
            height: 18px;
            background-color: #2d2d2d;
            border: 1px solid #444444;
            border-radius: 9px; /* Circular */
        }
        QRadioButton::indicator:hover {
            border: 1px solid #4da6ff;
            background-color: #353535;
        }
        QRadioButton::indicator:checked {
            background-color: #2a82da;
            border: 1px solid #4da6ff;
            image: url(none);
        }
        QRadioButton::indicator:checked:hover {
            background-color: #3b93eb;
            border: 1px solid #80bdff;
        }
    """)


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    
    if os.name == "nt":
        import ctypes

        try:
            myappid = "PingWer.fgseditor.3.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)

    if hasattr(sys, "_MEIPASS"):
        icon_path = os.path.join(sys._MEIPASS, "icon.ico")
    else:
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico"
        )

    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    setup_dark_theme(app)

    window = MainUI()
    window.resize(1200, 800)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
