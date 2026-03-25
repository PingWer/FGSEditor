import copy
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QFrame,
    QStackedWidget,
    QMenu,
)
from PySide6.QtCore import Qt

from . import fgs_parser
from .plotter import InteractiveFGSPlotter
from .shortcuts import create_standard_menu, show_credits, open_github


class WelcomeScreen(QFrame):
    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui
        self.setAcceptDrops(True)
        self.setObjectName("welcomeScreen")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        self.open_btn = QPushButton("Open FGS File")
        self.open_btn.setObjectName("bigButton")
        self.open_btn.setFixedSize(320, 80)
        self.open_btn.clicked.connect(self.main_ui.load_file)
        layout.addWidget(self.open_btn, alignment=Qt.AlignCenter)

        self.create_btn = QPushButton("Create FGS")
        self.create_btn.setObjectName("bigButton")
        self.create_btn.setFixedSize(320, 80)

        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Single Event (TODO)").triggered.connect(
            lambda: print("Dummy: Single Event")
        )
        create_menu.addAction("Multiple Event (TODO)").triggered.connect(
            lambda: print("Dummy: Multiple Event")
        )
        self.create_btn.setMenu(create_menu)

        layout.addWidget(self.create_btn, alignment=Qt.AlignCenter)

        drop_label = QLabel("Or drag and drop an FGS .txt file here")
        drop_label.setAlignment(Qt.AlignCenter)
        drop_label.setStyleSheet("color: #777777; font-size: 15px; margin-top: 15px;")
        layout.addWidget(drop_label, alignment=Qt.AlignCenter)

        layout.addSpacing(40)

        bottom_layout = QHBoxLayout()
        bottom_layout.setAlignment(Qt.AlignCenter)

        self.credits_btn = QPushButton("Credits")
        self.credits_btn.setStyleSheet(
            "background-color: transparent; color: #4da6ff; text-decoration: underline; border: none; font-weight: normal;"
        )
        self.credits_btn.setCursor(Qt.PointingHandCursor)
        self.credits_btn.clicked.connect(self.show_credits)
        bottom_layout.addWidget(self.credits_btn)

        dot_label = QLabel(" • ")
        dot_label.setStyleSheet("color: #555555; background-color: transparent;")
        bottom_layout.addWidget(dot_label)

        self.github_btn = QPushButton("GitHub")
        self.github_btn.setStyleSheet(
            "background-color: transparent; color: #4da6ff; text-decoration: underline; border: none; font-weight: normal;"
        )
        self.github_btn.setCursor(Qt.PointingHandCursor)
        self.github_btn.clicked.connect(self.open_github)
        bottom_layout.addWidget(self.github_btn)

        layout.addLayout(bottom_layout)

    def show_credits(self):
        show_credits(self)

    def open_github(self):
        open_github()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            if filepath.endswith(".txt"):
                self.main_ui.load_file_from_path(filepath)


class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FGSEditor")
        self.setMinimumSize(800, 600)

        self.filepath = None
        self.original_data = {}
        self.current_data = {}

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.welcome_screen = WelcomeScreen(self)
        self.stacked_widget.addWidget(self.welcome_screen)

        self.editor_widget = QWidget()
        main_layout = QVBoxLayout(self.editor_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        self.stacked_widget.addWidget(self.editor_widget)

        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        top_layout = QHBoxLayout(top_frame)

        self.close_btn = QPushButton("Close FGS")
        self.close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.close_btn.clicked.connect(self.close_fgs)
        top_layout.addWidget(self.close_btn, stretch=0)

        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        top_layout.addWidget(self.file_label, stretch=1)

        main_layout.addWidget(top_frame)

        menu_bar = create_standard_menu(self)
        main_layout.setMenuBar(menu_bar)

        # Middle controls
        mid_frame = QFrame()
        mid_frame.setObjectName("toolbar")
        mid_layout = QHBoxLayout(mid_frame)

        mid_layout.addWidget(QLabel("Channel to edit:"), stretch=0)
        self.channel_dropdown = QComboBox()
        self.channel_dropdown.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.channel_dropdown.addItems(["sY", "sCb", "sCr"])
        self.channel_dropdown.currentTextChanged.connect(self.on_channel_change)
        mid_layout.addWidget(self.channel_dropdown, stretch=0)

        mid_layout.addStretch(1)

        self.save_btn = QPushButton("Save FGS")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        mid_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reset_btn.clicked.connect(self.reset_data)
        self.reset_btn.setEnabled(False)
        mid_layout.addWidget(self.reset_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.clear_btn.clicked.connect(self.clear_channel)
        self.clear_btn.setEnabled(False)
        mid_layout.addWidget(self.clear_btn)

        self.save_plot_btn = QPushButton("Save Plot")
        self.save_plot_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_plot_btn.clicked.connect(self.save_plot_as_png)
        mid_layout.addWidget(self.save_plot_btn)

        main_layout.addWidget(mid_frame)

        self.plotter = InteractiveFGSPlotter()
        self.plotter.data_changed.connect(self.on_plotter_changed)
        main_layout.addWidget(self.plotter, stretch=1)

    def on_channel_change(self, text):
        self.plotter.set_active_channel(text)

    def on_plotter_changed(self):
        self.current_data = self.plotter.current_data

    def closeEvent(self, event):
        if (
            self.current_data
            and self.original_data
            and self.current_data != self.original_data
        ):
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_file()
                event.accept()
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        event.accept()

    def close_fgs(self):
        if (
            self.current_data
            and self.original_data
            and self.current_data != self.original_data
        ):
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_file()
            elif reply == QMessageBox.Cancel:
                return

        self.filepath = None
        self.current_data = {}
        self.original_data = {}
        self.plotter.set_data({})
        self.stacked_widget.setCurrentIndex(0)

    def load_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select FGS file", "", "Text Files (*.txt)"
        )
        if not filename:
            return
        self.load_file_from_path(filename)

    def load_file_from_path(self, filepath):
        self.filepath = filepath
        self.file_label.setText(f"Editing: {self.filepath}")

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read()

            header_lines, events = fgs_parser.parse_fgs_events(content)

            if fgs_parser.is_dynamic(events):
                from .dynamic_ui import DynamicTimelineUI

                self.dynamic_ui = DynamicTimelineUI(
                    self,
                    {
                        "header_lines": header_lines,
                        "events": events,
                        "filepath": self.filepath,
                    },
                )
                self.hide()
                self.dynamic_ui.show()
            else:
                parsed = events[0]["scale_data"] if events else {}
                self.original_data = copy.deepcopy(parsed)
                self.current_data = copy.deepcopy(parsed)
                self.save_btn.setEnabled(True)
                self.reset_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.plotter.set_data(self.current_data)
                self.stacked_widget.setCurrentIndex(1)
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(ex)}")

    def reset_data(self):
        if not self.original_data:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Are you sure you want to revert all changes?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.current_data = copy.deepcopy(self.original_data)
            self.plotter.set_data(self.current_data)

    def clear_channel(self):
        if not self.current_data:
            return

        ch = self.channel_dropdown.currentText()
        reply = QMessageBox.question(
            self,
            "Confirm Clear",
            f"Are you sure you want to remove all points from {ch}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.current_data[ch]["x"] = []
            self.current_data[ch]["y"] = []
            self.plotter.set_data(self.current_data)

    def save_file(self):
        if not self.filepath:
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Modified FGS", "modified_fgs.txt", "Text Files (*.txt)"
        )
        if not save_path:
            return

        with open(self.filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            tokens = line.strip().split()
            if not tokens:
                continue
            prefix = tokens[0]
            if prefix in ["sY", "sCb", "sCr"]:
                data = self.current_data[prefix]
                pts_count = len(data["x"])
                if pts_count == 0:
                    lines[i] = f"{prefix} 0\n"
                else:
                    pairs = []
                    for x, y in zip(data["x"], data["y"]):
                        pairs.extend([str(x), str(y)])
                    lines[i] = f"{prefix} {pts_count} " + " ".join(pairs) + "\n"

        with open(save_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        QMessageBox.information(self, "Success", "File saved successfully!")

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot as PNG", "plot.png", "PNG Images (*.png)"
        )
        if not save_path:
            return

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
        plt.style.use("dark_background")

        ax.set_facecolor("#111111")
        styles = {
            "sY": {"color": "#2ca02c", "label": "Luma (sY)", "marker": "o"},
            "sCb": {"color": "#1f77b4", "label": "Chroma (sCb)", "marker": "s"},
            "sCr": {"color": "#d62728", "label": "Chroma (sCr)", "marker": "^"},
        }

        min_y = float("inf")
        max_y = 0
        has_data = False

        for channel, data in self.current_data.items():
            if data["x"]:
                has_data = True
                min_y = min(min_y, min(data["y"]))
                max_y = max(max_y, max(data["y"]))
                ax.plot(
                    data["x"],
                    data["y"],
                    color=styles[channel]["color"],
                    label=styles[channel]["label"],
                    marker=styles[channel]["marker"],
                    linestyle="-",
                    markersize=6,
                    linewidth=2,
                )

        ax.set_title("Film Grain Strength - Saved Plot")
        ax.set_xlabel("Y Value")
        ax.set_ylabel("Strength")
        ax.grid(True, linestyle="--", color="#444444", alpha=0.5)

        if has_data:
            y_margin = max(5, (max_y - min_y) * 0.15)
            ax.legend()
            ax.set_xlim(0, 255)
            ax.set_ylim(min_y - y_margin, max_y + y_margin)
            ax.set_xticks([0, 16, 50, 100, 150, 200, 235, 255])
            ax.axvline(16, color="#555555", linestyle=":", alpha=0.5)
            ax.axvline(235, color="#555555", linestyle=":", alpha=0.5)
            ax.axhline(100, color="#555555", linestyle=":", alpha=0.5)

        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close(fig)

        QMessageBox.information(self, "Success", f"Plot saved to:\n{save_path}")
