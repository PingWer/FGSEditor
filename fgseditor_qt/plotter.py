import copy
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator


class InteractiveFGSPlotter(QWidget):
    data_changed = Signal()
    undo_push_requested = Signal(object)
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor("#1e1e1e")
        self.ax.set_facecolor("#111111")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: #1e1e1e;")

        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self.styles = {
            "sY": {"color": "#2ca02c", "label": "Luma (sY)", "marker": "o"},
            "sCb": {"color": "#1f77b4", "label": "Chroma (sCb)", "marker": "s"},
            "sCr": {"color": "#d62728", "label": "Chroma (sCr)", "marker": "^"},
        }

        self.active_channel = "sY"
        self.current_data = {
            "sY": {"x": [], "y": []},
            "sCb": {"x": [], "y": []},
            "sCr": {"x": [], "y": []},
        }

        self.lines = {}

        self.drag_point_index = None
        self._drag_start_x = None
        self._drag_start_y = None
        self._drag_lock_axis = None
        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_start_xlim = None
        self._pan_start_ylim = None

        self._user_xlim = None
        self._user_ylim = None

        self._user_ylim = None

        # Clipping alert data: set from outside via set_clip_extremes()
        self._clip_extremes: dict | None = None
        self._clip_scaling_shift: int = 8
        self._is_chroma_linked: bool = False

        self.annot = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="black", ec="white", alpha=0.8),
            color="white",
            zorder=10,
        )
        self.annot.set_visible(False)

        # Connect matplotlib events
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("button_release_event", self.on_release)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.canvas.mpl_connect("axes_enter_event", self.on_enter)
        self.canvas.mpl_connect("axes_leave_event", self.on_leave)
        self.canvas.mpl_connect("key_press_event", self._on_mpl_key_press)

    def _push_undo(self, old_data=None):
        self.undo_push_requested.emit(old_data)

    def _on_mpl_key_press(self, event):
        if event.key == "ctrl+z":
            self.undo_requested.emit()
        elif event.key == "ctrl+y":
            self.redo_requested.emit()

    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                self.undo_requested.emit()
                return
            if event.key() == Qt.Key_Y:
                self.redo_requested.emit()
                return
        super().keyPressEvent(event)

    def on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        if event.key != "control":
            return

        base_scale = 1.25
        scale_factor = 1.0 / base_scale if event.button == "up" else base_scale

        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()

        # Stable zoom using pixel-space relative position
        bbox = self.ax.get_window_extent()
        rel_x = (event.x - bbox.x0) / bbox.width
        rel_y = (event.y - bbox.y0) / bbox.height

        x_range = cur_xlim[1] - cur_xlim[0]
        y_range = cur_ylim[1] - cur_ylim[0]

        xdata_now = cur_xlim[0] + rel_x * x_range
        ydata_now = cur_ylim[0] + rel_y * y_range

        new_x_range = x_range * scale_factor
        new_y_range = y_range * scale_factor

        new_xlim = [
            xdata_now - new_x_range * rel_x,
            xdata_now + new_x_range * (1 - rel_x),
        ]
        new_ylim = [
            ydata_now - new_y_range * rel_y,
            ydata_now + new_y_range * (1 - rel_y),
        ]

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self._user_xlim = tuple(new_xlim)
        self._user_ylim = tuple(new_ylim)

        if self._is_panning:
            self._pan_start_x = event.x
            self._pan_start_y = event.y
            self._pan_start_xlim = tuple(new_xlim)
            self._pan_start_ylim = tuple(new_ylim)

        self.canvas.draw_idle()

    def set_active_channel(self, channel_name):
        self.active_channel = channel_name
        self.refresh()

    def set_data(self, data_dict):
        self.current_data = copy.deepcopy(data_dict)

        for ch in ["sY", "sCb", "sCr"]:
            if ch not in self.current_data:
                self.current_data[ch] = {"x": [], "y": []}

        self._user_xlim = None
        self._user_ylim = None

        self.refresh()

    def close_plot(self):
        self.ax.clear()
        self.figure.clear()
        self.canvas.deleteLater()
        self.annot = None
        self.ax = None
        self.figure = None
        self.canvas = None
        self.lines = {}

    def set_clip_extremes(self, extremes: dict | None, scaling_shift: int = 8) -> None:
        self._clip_extremes = extremes
        self._clip_scaling_shift = scaling_shift

    def set_chroma_linked(self, linked: bool) -> None:
        self._is_chroma_linked = linked
        self.refresh()

    def refresh(self):
        self.ax.clear()
        self.ax.set_facecolor("#111111")
        self.lines.clear()

        min_y = float("inf")
        max_y = 0
        has_data = False

        for channel, data in self.current_data.items():
            if data["x"]:
                has_data = True
                min_y = min(min_y, min(data["y"]))
                max_y = max(max_y, max(data["y"]))

                alpha = 1.0 if channel == self.active_channel else 0.3

                (line,) = self.ax.plot(
                    data["x"],
                    data["y"],
                    color=self.styles[channel]["color"],
                    label=self.styles[channel]["label"],
                    marker=self.styles[channel]["marker"],
                    linestyle="-",
                    markersize=6,
                    linewidth=2,
                    alpha=alpha,
                    picker=12,
                )
                self.lines[channel] = {"line": line, "data": data}

        self.annot = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="black", ec="white", alpha=0.8),
            color="white",
            zorder=10,
        )
        self.annot.set_visible(False)

        self.ax.set_title("Film Grain Strength Interactive Plot", color="white")
        self.ax.set_xlabel("Y Value", color="#cccccc")
        self.ax.set_ylabel("Strength", color="#cccccc")

        self.ax.tick_params(colors="white")
        self.ax.yaxis.set_major_locator(MaxNLocator(integer=True))

        self.ax.grid(True, linestyle="--", color="#444444", alpha=0.5)

        if self._is_chroma_linked and self.active_channel in ("sCb", "sCr"):
            self.ax.text(
                0.5,
                0.95,
                "LINKED TO LUMA (Read-Only)",
                transform=self.ax.transAxes,
                color="#4da6ff",
                fontweight="bold",
                ha="center",
                va="top",
                bbox=dict(
                    facecolor="#1a1a2e",
                    alpha=0.8,
                    edgecolor="#4da6ff",
                    boxstyle="round,pad=0.5",
                ),
            )

        if has_data:
            y_margin = max(5, (max_y - min_y) * 0.15)
            self.ax.legend()
            self.ax.legend()
            self.ax.set_xticks([0, 16, 50, 100, 150, 200, 235, 255])

            self.ax.axvspan(0, 16, color="#ff0000", alpha=0.04, zorder=0)
            self.ax.axvspan(235, 255, color="#ff0000", alpha=0.04, zorder=0)

            self.ax.axvline(16, color="#ff4444", linestyle=":", alpha=0.3)
            self.ax.axvline(235, color="#ff4444", linestyle=":", alpha=0.3)
            self.ax.axhline(
                100, color="#f59e0b", linestyle=":", alpha=0.35, linewidth=0.9
            )
        else:
            self.ax.set_xlim(0, 255)
            self.ax.set_ylim(0, 150)

        self.figure.tight_layout()

        if self._user_xlim is not None and has_data:
            self.ax.set_xlim(self._user_xlim)
            self.ax.set_ylim(self._user_ylim)
        elif has_data:
            self.ax.set_xlim(0, 255)
            self.ax.set_ylim(min_y - y_margin, max_y + y_margin)

        if self._clip_extremes and has_data:
            self._draw_clip_alerts()

        self.canvas.draw()

    def _draw_clip_alerts(self) -> None:
        from .fgs_grain_sim import compute_amplitude_at_point

        ext = self._clip_extremes
        s_shift = self._clip_scaling_shift

        channel_configs = {
            "sY": ("luma_max", "luma_min", 16, 235),
            "sCb": ("cb_max", "cb_min", 16, 235),
            "sCr": ("cr_max", "cr_min", 16, 235),
        }

        for channel, data in self.current_data.items():
            if not data["x"]:
                continue
            config = channel_configs.get(channel)
            if not config:
                continue
            max_key, min_key, l_min, l_max = config
            grain_max = ext.get(max_key, 0)
            grain_min = ext.get(min_key, 0)

            clip_x = []
            clip_y = []
            for px, py in zip(data["x"], data["y"]):
                d_max = compute_amplitude_at_point(grain_max, py, s_shift)
                d_min = compute_amplitude_at_point(grain_min, py, s_shift)

                if (px + d_max) > l_max or (px + d_min) < l_min:
                    clip_x.append(px)
                    clip_y.append(py)

            if clip_x:
                self.ax.scatter(
                    clip_x,
                    clip_y,
                    marker="v",
                    s=80,
                    c="#ff4444",
                    edgecolors="#ff8800",
                    linewidths=1.5,
                    zorder=8,
                    label="_clip" if channel != "sY" else "⚠ clips",
                )

    def get_point_constraints(self, channel, idx):
        x_list = self.current_data[channel]["x"]
        min_x = 16 if idx == 0 else x_list[idx - 1] + 1
        max_x = 235 if idx == len(x_list) - 1 else x_list[idx + 1] - 1
        return min_x, max_x

    def get_point_under_mouse(self, event):
        if not event.inaxes or self.active_channel not in self.current_data:
            return None

        data = self.current_data[self.active_channel]
        if not data["x"]:
            return None

        x_data = data["x"]
        y_data = data["y"]

        min_dist = float("inf")
        found_idx = None

        for i in range(len(x_data)):
            pt_px = self.ax.transData.transform((x_data[i], y_data[i]))
            dist = ((pt_px[0] - event.x) ** 2 + (pt_px[1] - event.y) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                found_idx = i

        if found_idx is not None and min_dist <= 12:
            return found_idx
        return None

    def on_press(self, event):
        self.canvas.setFocus()

        if event.inaxes != self.ax:
            return

        # If linked, block edits to Chroma
        if self._is_chroma_linked and self.active_channel in ("sCb", "sCr"):
            if event.button != 2:  # Allow middle-click pan
                return

        if event.button == 2:
            self._is_panning = True
            self._pan_start_x = event.x
            self._pan_start_y = event.y
            self._pan_start_xlim = self.ax.get_xlim()
            self._pan_start_ylim = self.ax.get_ylim()
            return

        if event.dblclick and event.button == 1:
            idx = self.get_point_under_mouse(event)
            if idx is not None:
                self.drag_point_index = None
                self.open_edit_dialog(self.active_channel, idx)
            return

        if event.button == 1:
            idx = self.get_point_under_mouse(event)
            if idx is not None:
                self.drag_point_index = idx
                ch = self.active_channel
                self._drag_start_x = self.current_data[ch]["x"][idx]
                self._drag_start_y = self.current_data[ch]["y"][idx]
                self._drag_lock_axis = None

        elif event.button == 3:
            ch = self.active_channel
            idx = self.get_point_under_mouse(event)

            x_val = int(round(event.xdata))
            y_val = int(round(event.ydata))

            if idx is not None:
                from PySide6.QtWidgets import QMessageBox

                if len(self.current_data[ch]["x"]) <= 2:
                    QMessageBox.warning(
                        self, "Limit", "You must have at least 2 points."
                    )
                else:
                    self._push_undo()
                    self.delete_point(idx)
            else:
                from PySide6.QtWidgets import QMessageBox

                if len(self.current_data[ch]["x"]) >= 14:
                    QMessageBox.warning(self, "Limit", "You cannot exceed 14 points.")
                else:
                    new_x = max(16, min(235, x_val))
                    new_y = max(0, min(255, y_val))

                    if new_x in self.current_data[ch]["x"]:
                        QMessageBox.warning(
                            self,
                            "Invalid Point",
                            f"A point at X={new_x} already exists.",
                        )
                    else:
                        self._push_undo()
                        self.add_point(new_x, new_y)

    def open_edit_dialog(self, channel, idx):
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QMessageBox,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Point ({channel})")
        dialog.setFixedSize(280, 200)

        curr_x = self.current_data[channel]["x"][idx]
        curr_y = self.current_data[channel]["y"][idx]
        min_x, max_x = self.get_point_constraints(channel, idx)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Edit values for point {idx + 1}"))

        form_layout = QVBoxLayout()

        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel(f"X Value ({min_x} - {max_x}):"))
        x_input = QLineEdit(str(curr_x))
        x_layout.addWidget(x_input)
        form_layout.addLayout(x_layout)

        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Y Strength (0 - 255):"))
        y_input = QLineEdit(str(curr_y))
        y_layout.addWidget(y_input)
        form_layout.addLayout(y_layout)

        layout.addLayout(form_layout)

        def apply_changes():
            try:
                new_x = int(x_input.text())
                new_y = int(y_input.text())

                if not (min_x <= new_x <= max_x):
                    QMessageBox.warning(
                        dialog,
                        "X Error",
                        f"X value must be between {min_x} and {max_x}.",
                    )
                    return
                if not (0 <= new_y <= 255):
                    QMessageBox.warning(
                        dialog, "Y Error", "Y strength must be between 0 and 255."
                    )
                    return

                self._push_undo()
                self.current_data[channel]["x"][idx] = new_x
                self.current_data[channel]["y"][idx] = new_y
                self.refresh()
                self.data_changed.emit()
                dialog.accept()
            except ValueError:
                QMessageBox.warning(dialog, "Error", "Enter only valid integers.")

        btn = QPushButton("Apply")
        btn.clicked.connect(apply_changes)
        layout.addWidget(btn)

        dialog.exec()

    def on_release(self, event):
        if self._is_panning:
            self._is_panning = False
            return

        if event.button == 1 and self.drag_point_index is not None:
            idx = self.drag_point_index
            ch = self.active_channel
            # Only push undo if the point actually moved
            end_x = self.current_data[ch]["x"][idx]
            end_y = self.current_data[ch]["y"][idx]
            if end_x != self._drag_start_x or end_y != self._drag_start_y:
                snapshot = copy.deepcopy(self.current_data)
                snapshot[ch]["x"][idx] = self._drag_start_x
                snapshot[ch]["y"][idx] = self._drag_start_y
                self.undo_push_requested.emit(snapshot)

            self.drag_point_index = None
            self._drag_lock_axis = None
            self.data_changed.emit()

    def on_motion(self, event):
        if self._is_panning and event.inaxes == self.ax:
            bbox = self.ax.get_window_extent()
            dx_pixels = event.x - self._pan_start_x
            dy_pixels = event.y - self._pan_start_y

            cur_xlim = self._pan_start_xlim
            cur_ylim = self._pan_start_ylim

            dx_data = dx_pixels * ((cur_xlim[1] - cur_xlim[0]) / bbox.width)
            dy_data = dy_pixels * ((cur_ylim[1] - cur_ylim[0]) / bbox.height)

            new_xlim = (cur_xlim[0] - dx_data, cur_xlim[1] - dx_data)
            new_ylim = (cur_ylim[0] - dy_data, cur_ylim[1] - dy_data)

            self.ax.set_xlim(new_xlim)
            self.ax.set_ylim(new_ylim)
            self._user_xlim = new_xlim
            self._user_ylim = new_ylim
            self.canvas.draw_idle()
            return

        if self.drag_point_index is None:
            if event.inaxes == self.ax and self.active_channel in self.current_data:
                ch = self.active_channel
                idx = self.get_point_under_mouse(event)
                if idx is not None:
                    x = self.current_data[ch]["x"][idx]
                    y = self.current_data[ch]["y"][idx]
                    self.annot.xy = (x, y)
                    self.annot.set_text(f"{ch}\nValue: {x}\nStrength: {y}")
                    self.annot.set_visible(True)
                    self.canvas.draw_idle()
                else:
                    if self.annot.get_visible():
                        self.annot.set_visible(False)
                        self.canvas.draw_idle()
            else:
                if self.annot.get_visible():
                    self.annot.set_visible(False)
                    self.canvas.draw_idle()
            return

        if event.inaxes != self.ax:
            return

        idx = self.drag_point_index
        ch = self.active_channel
        data = self.current_data[ch]

        raw_x = int(round(event.xdata))
        raw_y = int(round(event.ydata))

        min_x, max_x = self.get_point_constraints(ch, idx)

        if event.key == "shift":
            if self._drag_lock_axis is None:
                dx = abs(raw_x - self._drag_start_x)
                dy = abs(raw_y - self._drag_start_y)
                if dx > dy:
                    self._drag_lock_axis = "x"
                elif dy > dx:
                    self._drag_lock_axis = "y"

            if self._drag_lock_axis == "x":
                raw_y = self._drag_start_y
            elif self._drag_lock_axis == "y":
                raw_x = self._drag_start_x
        else:
            self._drag_lock_axis = None

        new_x = max(min_x, min(max_x, raw_x))
        new_y = max(0, min(255, raw_y))

        data["x"][idx] = new_x
        data["y"][idx] = new_y

        self.lines[ch]["line"].set_data(data["x"], data["y"])

        self.annot.xy = (new_x, new_y)
        self.annot.set_text(f"{ch}\nValue: {new_x}\nStrength: {new_y}")
        self.annot.set_visible(True)

        self.canvas.draw_idle()

    def on_enter(self, event):
        self.canvas.setFocus()

    def on_leave(self, event):
        self._is_panning = False
        if self.annot.get_visible():
            self.annot.set_visible(False)
            self.canvas.draw_idle()

    def add_point(self, x, y):
        data = self.current_data[self.active_channel]

        if x in data["x"]:
            return

        data["x"].append(x)
        data["y"].append(y)

        pairs = sorted(zip(data["x"], data["y"]))
        data["x"] = [p[0] for p in pairs]
        data["y"] = [p[1] for p in pairs]

        self.refresh()
        self.data_changed.emit()

    def delete_point(self, idx):
        data = self.current_data[self.active_channel]

        if len(data["x"]) <= 2:
            return

        data["x"].pop(idx)
        data["y"].pop(idx)

        self.refresh()
        self.data_changed.emit()
