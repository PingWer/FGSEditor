# FGSEditor

**FGSEditor** is a powerful open-source graphical tool designed to view, edit, optimize, and create **Film Grain Synthesis (FGS)** tables for AV1 and HEVC video. It allows you to inspect and modify FGS tables, generate them with [`regrain`](https://github.com/Rabbit-Company/regrain) or [`grav1synth`](https://github.com/rust-av/grav1synth), create manually new tables from scratch or built-in presets, optimize existing tables mathematically, and apply grain tables directly to video files.

The editor provides dedicated workflows for both **Static FGS** (single-event tables) and **Dynamic FGS** (multi-event timelines).

> [!TIP]
> 📖 **Official Documentation & FGS Guide**: Looking for an in-depth guide on Film Grain Synthesis theory, AFGS1 mathematical models, table syntax, and step-by-step editor usage? Visit the comprehensive [**FGSEditor Wiki**](https://github.com/PingWer/FGSEditor/wiki).

---

## 🚀 Features

- **Static & Dynamic FGS Editing**:
  - Full editing support for both single-event tables and multi-event dynamic timelines.
  - Insert, delete, split, duplicate, and reorder events with millisecond and frame-level precision.
  - Strict preservation of event boundaries and custom gaps.
- **Independent Luma & Chroma Tuning**:
  - Full control over Luma ($sY, cY$) and Chroma ($sCb, sCr, cCb, cCr$) value-strength points and autoregressive coefficients.
  - Interactive plot visualization with real-time spline interpolation.
- **Automatic FGS Optimization**:
  - Intelligent mathematical optimizer to simplify curve points and reduce bitstream payload overhead while preserving perceptual grain fidelity.
  - Works on entire tables or individual events with configurable quality thresholds.
- **FGS Generation & Presets**:
  - Built-in presets for various film stocks (35mm, 16mm, fine grain, coarse grain, digital sensor noise, photon shot noise).
  - Manual and automatic FGS creation dialogs.
- **Save & Apply Directly to Video**:
  - Apply in-memory grain tables directly to target ivf/MKV videos using `regrain` or `grav1synth`.
  - Stream-copy remuxing via FFmpeg to retain original audio, subtitles, attachments, chapters, and metadata.
- **Export Formats**:
  - Standard AV1 FGS text table (`.txt`, `.tbl`).
  - Binary grain payload for x265 / encoders (`.bin`).
  - High-resolution plot export (`.png`).

---

## 🛠️ External Dependencies

FGSEditor delegates low-level video processing and grain injection to external tools. While FGSEditor can view, edit, and create FGS tables standalone, installing the following tools is recommended to unlock video application and probing capabilities:

| Tool | Status | Purpose |
| :--- | :---: | :--- |
| [**`regrain`**](https://github.com/Rabbit-Company/regrain) | **Recommended** | Fast, modern CLI for applying, inspecting, and stripping FGS tables with native Matroska (`.mkv`) support and progress reporting. |
| [**`grav1synth`**](https://github.com/rust-av/grav1synth) | Alternative | Legacy AV1 grain injector and inspector. |
| [**`ffmpeg`** / **`ffprobe`**](https://ffmpeg.org/) | **Required for Video** | Video metadata extraction (FPS, duration, resolution) and lossless stream remuxing (preserving audio, subtitles, chapters, and attachments during Save & Apply). |
| [**`av-denoise`**](https://github.com/ChillFish8/av-denoise) | Optional | GPU-accelerated video denoiser |

> [!NOTE]
> Supported versions for each third-party tool are specified directly within the release notes of each version on the [GitHub Releases](../../releases) page.

### How FGSEditor Finds External Tools
You can configure the paths to these tools in **Settings** (click the **⚙** gear button on the home screen or open *Settings → Preferences*).
If no path is specified, FGSEditor automatically searches for them in:
1. The user-configured path in Settings.
2. The folder next to the FGSEditor executable.
3. Your system `PATH`.

---

## 📥 Installation & Usage

### Pre-compiled Binaries
You can download pre-compiled packages directly from the GitHub [Releases](../../releases) page:
1. Go to the [Releases](../../releases) tab.
2. Download the latest archive for your operating system (**Windows** or **Linux**).
3. Extract the archive and run `FGSEditor.exe` (Windows) or `./FGSEditor` (Linux).
4. *(Optional)* Place `regrain` (or `grav1synth`) and `ffmpeg`/`ffprobe` in the same directory or configure their paths in Settings.

### Build from Source

#### Prerequisites
- Python **3.12** or newer.
- Virtual environment recommended.

```bash
# Clone the repository
git clone https://github.com/PingWer/FGSEditor.git
cd FGSEditor

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux:
source .venv/bin/activate

# Install dependencies and project in editable mode
pip install -e .
```

#### Run FGSEditor
```bash
python -m fgseditor_qt.fgsview_loader
# Or simply:
fgseditor
```

#### Package Executable Locally
- **Windows** (generates onefile executable in `dist/`):
  ```cmd
  build.bat
  ```
- **Linux** (generates binary in `dist/`):
  ```bash
  chmod +x build.sh
  ./build.sh
  ```

---

## 📖 Documentation
A full Wiki with parameter references, mathematical background, and usage guides is available on the [GitHub Wiki](../../wiki).

---

## 📋 Roadmap & TODO

- [x] Add the ability to insert new events into a dynamic FGS.
- [x] Implement automatic FGS optimization.
- [x] Add built-in presets for various types of grain/events.
- [x] Add Linux support
- [x] Add the ability to automatically generate FGS tables from a video.
- [ ] Add the possibility to preview in realtime the FGS on a video.

---

## 📜 Licenses & Copyright
FGSEditor is licensed under the **AGPL-3.0** License.
All third-party licenses, trademarks, and copyright notices are detailed in [`NOTICE.md`](NOTICE.md), which can also be inspected directly within the application under **Licenses & Copyright**.

---

## 🤝 Contributing
Contributions, issue reports, and pull requests are warmly welcome!
Join the community and discussion in the [AV1 Weeb Discord Server](https://discord.gg/bZPrC2cmP6).
