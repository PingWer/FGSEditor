from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .fgs_math import (
    build_chroma_amplitude_curve,
    compute_ar_norm_factor,
    compute_ar_gain,
    get_base_noise_energy,
    get_psychovisual_factor,
    interpolate_scaling,
    P_DEFAULTS,
)

# Fixed reference amplitude for % mode normalisation
_REF = 255.0 / 256.0


class GrainPreviewPlotter(QWidget):
    """Read-only secondary chart: compensated effective grain amplitude."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._pct_mode = False
        self._current_data: dict = {}
        self._p_params: dict = dict(P_DEFAULTS)
        self._grain_size: int = 1
        self._cy_coeffs: list[int] = []
        self._cb_coeffs: list[int] = []
        self._cr_coeffs: list[int] = []
        self._noise_setting: float = 100.0  # percentage (100% = 24.0 RMS)
        self._autobalance: bool = True  # UI flag

        self.figure = Figure(figsize=(8, 2.5), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor("#1e1e1e")
        self.ax.set_facecolor("#111111")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: #1e1e1e;")

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(4, 2, 4, 0)

        title_lbl = QLabel("Effective Grain Amplitude")
        title_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold;")
        top_bar.addWidget(title_lbl, stretch=1)

        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #f59e0b; font-size: 10px;")
        top_bar.addWidget(self._info_label, stretch=0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top_bar)
        layout.addWidget(self.canvas, stretch=1)

    def update_preview(
        self,
        current_data: dict,
        p_params: dict | None = None,
        grain_size: int | None = None,
        cy_coeffs: list[int] | None = None,
        cb_coeffs: list[int] | None = None,
        cr_coeffs: list[int] | None = None,
        noise_setting: float | None = None,
        autobalance: bool | None = None,
    ) -> None:
        """Recompute and redraw. noise_setting is 0-500+ %."""
        self._current_data = current_data or {}
        if p_params is not None:
            self._p_params = p_params
        if grain_size is not None:
            self._grain_size = grain_size
        if cy_coeffs is not None:
            self._cy_coeffs = cy_coeffs
        if cb_coeffs is not None:
            self._cb_coeffs = cb_coeffs
        if cr_coeffs is not None:
            self._cr_coeffs = cr_coeffs
        if noise_setting is not None:
            self._noise_setting = noise_setting
        if autobalance is not None:
            self._autobalance = autobalance
        self._redraw()

    def is_ar_unstable(self) -> bool:
        """True when the AR filter would be unstable (norm_factor ≤ 0)."""
        ar_shift = self._p_params.get("ar_coeff_shift", 8)
        return compute_ar_norm_factor(self._cy_coeffs, ar_shift) <= 0.0

    def _on_mode_toggle(self, checked: bool) -> None:
        self._pct_mode = checked
        self._toggle_btn.setText("% Mode" if checked else "Raw px")
        self._redraw()

    def _redraw(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#111111")

        data = self._current_data
        p = self._p_params
        ar_shift = p.get("ar_coeff_shift", 8)
        scaling_divisor = 2 ** p.get("scaling_shift", 8)

        sy_data = data.get("sY", {"x": [], "y": []})
        scb_data = data.get("sCb", {"x": [], "y": []})
        scr_data = data.get("sCr", {"x": [], "y": []})

        norm_factor = compute_ar_norm_factor(self._cy_coeffs, ar_shift)
        is_unstable = norm_factor <= 0.0

        base_energy = get_base_noise_energy(self._noise_setting)
        ar_gain = compute_ar_gain(self._cy_coeffs, ar_shift)

        if self._autobalance:
            total_luma_energy = base_energy * get_psychovisual_factor(1)
        else:
            total_luma_energy = base_energy * ar_gain

        luma_vals = list(range(0, 256))
        luma_amp: list[float] = []
        for y in luma_vals:
            f_y = interpolate_scaling(sy_data["x"], sy_data["y"], y)
            luma_amp.append((total_luma_energy * f_y) / scaling_divisor)

        luma_pct = [a / _REF * 100.0 for a in luma_amp]

        cb_gain = compute_ar_gain(self._cb_coeffs, ar_shift)
        cr_gain = compute_ar_gain(self._cr_coeffs, ar_shift)

        if self._autobalance:
            total_cb_energy = base_energy * get_psychovisual_factor(1)
            total_cr_energy = base_energy * get_psychovisual_factor(1)
        else:
            total_cb_energy = base_energy * cb_gain
            total_cr_energy = base_energy * cr_gain

        chroma_curves = build_chroma_amplitude_curve(
            sy_data["x"],
            sy_data["y"],
            scb_data["x"],
            scb_data["y"],
            scr_data["x"],
            scr_data["y"],
            self._grain_size,
            self._noise_setting,
            self._cb_coeffs,
            self._cr_coeffs,
            p,
        )

        for ch in ["sCb", "sCr"]:
            c_vals, _, f_raw = chroma_curves[ch]
            energy = total_cb_energy if ch == "sCb" else total_cr_energy
            new_amp = [(energy * f) / scaling_divisor for f in f_raw]
            chroma_curves[ch] = (c_vals, new_amp, f_raw)

        y_label = "Amplitude (%)" if self._pct_mode else "Amplitude (px \u00b1)"

        if sy_data["x"]:
            y_sy = luma_pct if self._pct_mode else luma_amp
            self.ax.plot(
                luma_vals,
                y_sy,
                color="#4ade80",
                linewidth=1.8,
                label="Luma (sY)",
                alpha=0.95,
                zorder=3,
            )

        chroma_styles = {
            "sCb": ("#60a5fa", "Chroma Cb"),
            "sCr": ("#f87171", "Chroma Cr"),
        }
        for ch, (color, lbl) in chroma_styles.items():
            ch_vals, ch_amp, _ = chroma_curves[ch]
            ch_pct = [a / _REF * 100.0 for a in ch_amp]
            ch_y = ch_pct if self._pct_mode else ch_amp
            self.ax.plot(
                ch_vals,
                ch_y,
                color=color,
                linewidth=1.5,
                linestyle="--",
                label=lbl,
                alpha=0.7,
            )

        if self._pct_mode:
            self.ax.axhline(
                100, color="#f59e0b", linestyle=":", alpha=0.5, linewidth=0.9
            )

        self.ax.axvline(16, color="#555555", linestyle=":", alpha=0.4)
        self.ax.axvline(235, color="#555555", linestyle=":", alpha=0.4)

        if is_unstable:
            sum_cy = sum(self._cy_coeffs) if self._cy_coeffs else 0
            self._info_label.setStyleSheet(
                "color: #ff4444; font-size: 10px; font-weight: bold;"
            )
            self._info_label.setText(
                f"\u26a0 UNSTABLE AR: \u03a3cY={sum_cy:+d}/2^{ar_shift}  norm\u22640"
            )
        else:
            ab_badge = "\u2696 AB ON" if self._autobalance else "\u26a0 AB OFF"
            ab_color = "#4ade80" if self._autobalance else "#f59e0b"
            self._info_label.setStyleSheet(f"color: {ab_color}; font-size: 10px;")
            self._info_label.setText(ab_badge)

        self.ax.set_xlabel("Luma Value", color="#888888", fontsize=9)
        self.ax.set_ylabel(y_label, color="#888888", fontsize=9)
        self.ax.set_xlim(0, 255)
        self.ax.tick_params(colors="#888888", labelsize=8)
        self.ax.set_xticks([0, 16, 64, 128, 192, 235, 255])
        self.ax.grid(True, linestyle="--", color="#333333", alpha=0.5)
        self.ax.legend(
            loc="upper right",
            fontsize=8,
            framealpha=0.4,
            facecolor="#222222",
            edgecolor="#555555",
            labelcolor="#cccccc",
        )
        self.figure.tight_layout(pad=0.5)
        self.canvas.draw()
