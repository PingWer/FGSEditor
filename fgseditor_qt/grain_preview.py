from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from . import fgs_parser
from .fgs_math import (
    interpolate_scaling,
    validate_fgs_pipeline,
    build_chroma_deterministic_curve,
)
from .fgs_grain_sim import compute_grain_extremes, compute_amplitude_at_point


class GrainPreviewPlotter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._current_data: dict = {}
        self._p_params: dict = dict(fgs_parser.P_DEFAULTS)
        self._cy_coeffs: list[int] = []
        self._cb_coeffs: list[int] = []
        self._cr_coeffs: list[int] = []
        self._seed: int = 7391
        self._is_unstable: bool = False

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
        seed: int | None = None,
    ) -> None:
        self._current_data = current_data or {}
        if p_params is not None:
            self._p_params = p_params
        if cy_coeffs is not None:
            self._cy_coeffs = cy_coeffs
        if cb_coeffs is not None:
            self._cb_coeffs = cb_coeffs
        if cr_coeffs is not None:
            self._cr_coeffs = cr_coeffs
        if seed is not None:
            self._seed = seed
        self._redraw()

    def is_ar_unstable(self) -> bool:
        return self._is_unstable

    def _redraw(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#111111")

        data = self._current_data
        evt_ctx = {"p_params": self._p_params}
        ar_shift = fgs_parser.get_ar_coeff_shift(evt_ctx)
        ar_lag = fgs_parser.get_ar_coeff_lag(evt_ctx)
        scaling_shift = fgs_parser.get_scaling_shift(evt_ctx)
        gs_shift = fgs_parser.get_grain_scale_shift(evt_ctx)

        sy_data = data.get("sY", {"x": [], "y": []})
        scb_data = data.get("sCb", {"x": [], "y": []})
        scr_data = data.get("sCr", {"x": [], "y": []})

        extremes = compute_grain_extremes(
            seed=self._seed,
            cy_coeffs=self._cy_coeffs,
            cb_coeffs=self._cb_coeffs,
            cr_coeffs=self._cr_coeffs,
            ar_lag=ar_lag,
            ar_shift=ar_shift,
            grain_scale_shift=gs_shift,
        )
        self._last_extremes = extremes  # exposed for plotter clipping alerts

        luma_vals = list(range(0, 256))

        # LUMA
        if sy_data["x"]:
            luma_max_amp: list[float] = []
            luma_min_amp: list[float] = []
            luma_68_pos: list[float] = []
            luma_68_neg: list[float] = []

            for y in luma_vals:
                f_y = interpolate_scaling(sy_data["x"], sy_data["y"], y)
                d_max = compute_amplitude_at_point(
                    extremes["luma_max"], f_y, scaling_shift
                )
                d_min = compute_amplitude_at_point(
                    extremes["luma_min"], f_y, scaling_shift
                )
                luma_max_amp.append(d_max)
                luma_min_amp.append(d_min)
                luma_68_pos.append(d_max * 0.68)
                luma_68_neg.append(d_min * 0.68)

            # Peak max line (positive values only)
            self.ax.plot(
                luma_vals,
                luma_max_amp,
                color="#4ade80",
                linewidth=1.8,
                label="Luma strength",
                alpha=0.95,
                zorder=3,
            )
            # +68% average
            self.ax.plot(
                luma_vals,
                luma_68_pos,
                color="#4ade80",
                linewidth=1.0,
                linestyle="--",
                label="Luma average (68%)",
                alpha=0.7,
                zorder=2,
            )

        # CHROMA
        chroma_scaling_from_luma = fgs_parser.get_chroma_scaling_from_luma(evt_ctx)

        chroma_cfg = [
            (
                "sCb",
                scb_data,
                "cb_max",
                "cb_min",
                "#60a5fa",
                "Cb",
                fgs_parser.get_cb_mult(evt_ctx),
                fgs_parser.get_cb_luma_mult(evt_ctx),
                fgs_parser.get_cb_offset(evt_ctx),
            ),
            (
                "sCr",
                scr_data,
                "cr_max",
                "cr_min",
                "#f87171",
                "Cr",
                fgs_parser.get_cr_mult(evt_ctx),
                fgs_parser.get_cr_luma_mult(evt_ctx),
                fgs_parser.get_cr_offset(evt_ctx),
            ),
        ]

        for (
            _key,
            sc_data,
            key_max,
            key_min,
            color,
            lbl,
            c_mult,
            c_l_mult,
            c_off,
        ) in chroma_cfg:
            if not sc_data.get("x"):
                continue

            ch_vals, ch_min_amp, ch_max_amp = build_chroma_deterministic_curve(
                sC_xs=sc_data["x"],
                sC_ys=sc_data["y"],
                block_min=extremes[key_min],
                block_max=extremes[key_max],
                scaling_shift=scaling_shift,
                mult=c_mult,
                luma_mult=c_l_mult,
                offset=c_off,
                chroma_scaling_from_luma=chroma_scaling_from_luma,
            )

            ch_68_pos = [val * 0.68 for val in ch_max_amp]

            self.ax.plot(
                ch_vals,
                ch_max_amp,
                color=color,
                linewidth=1.5,
                label=f"{lbl} strength",
                alpha=0.7,
            )
            self.ax.plot(
                ch_vals,
                ch_68_pos,
                color=color,
                linewidth=1.0,
                linestyle="--",
                label=f"{lbl} average (68%)",
                alpha=0.6,
            )

        # Forced limited range, no reason to have a full range excursion
        self.ax.axvspan(0, 16, color="#ff0000", alpha=0.05, zorder=0)
        self.ax.axvspan(235, 255, color="#ff0000", alpha=0.05, zorder=0)

        self.ax.axvline(16, color="#ff4444", linestyle=":", alpha=0.3)
        self.ax.axvline(235, color="#ff4444", linestyle=":", alpha=0.3)

        sy_vals = sy_data.get("y", []) if sy_data.get("x") else []

        validation_warnings = []

        for ch_name, coeffs in [
            ("Y", self._cy_coeffs),
            ("Cb", self._cb_coeffs),
            ("Cr", self._cr_coeffs),
        ]:
            if coeffs:
                ch_vals = (
                    sy_vals
                    if ch_name == "Y"
                    else scb_data.get("y", [])
                    if ch_name == "Cb"
                    else scr_data.get("y", [])
                )
                warnings = validate_fgs_pipeline(coeffs, ar_shift, ch_vals)
                validation_warnings.extend(warnings)

        if validation_warnings:
            self._is_unstable = True
            self._info_label.setStyleSheet(
                "color: #ff4444; font-size: 10px; font-weight: bold;"
            )
            self._info_label.setText(f"\u26a0 {validation_warnings[0]}")
        else:
            self._is_unstable = False
            peak_info = f"seed={self._seed}  peak={extremes['luma_max']:+d}/{extremes['luma_min']:+d}"
            self._info_label.setStyleSheet("color: #f59e0b; font-size: 10px;")
            self._info_label.setText(peak_info)

        self.ax.set_xlabel("Luma Value", color="#888888", fontsize=9)
        self.ax.set_ylabel("Amplitude (px \u00b1) [8-bit]", color="#888888", fontsize=9)
        self.ax.set_xlim(0, 255)
        self.ax.tick_params(colors="#888888", labelsize=8)
        self.ax.set_xticks([0, 16, 64, 128, 192, 235, 255])
        self.ax.grid(True, linestyle="--", color="#333333", alpha=0.5)

        handles, labels = self.ax.get_legend_handles_labels()
        if labels:
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
