import os
import json
from .app_paths import get_base_dir

SETTINGS_FILE = os.path.join(get_base_dir(), "settings.json")

DEFAULT_SETTINGS = {
    "grav1synth_path": "",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "default_fps": "24",
    "default_time_format": "Frames",
    "show_unsafe_warnings": True,
    "fallback_export_frames": 150000,
    "plotter_color_luma": "#00ff00",
    "plotter_color_cb": "#0088ff",
    "plotter_color_cr": "#ff3333",
    "plotter_zoom_sensitivity": 1.2,
    "autosave_interval_minutes": 5,
    "timeline_max_workers": os.cpu_count() or 1,
    "fgs_grain_cache_size": 128,
    "undo_stack_size": 100,
}

_current_settings = {}

def load_settings():
    global _current_settings
    _current_settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                _current_settings.update(loaded)
        except Exception:
            pass

def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_current_settings, f, indent=4)
    except Exception:
        pass

def get_setting(key, default=None):
    if not _current_settings:
        load_settings()
    return _current_settings.get(key, default)

def set_setting(key, value):
    if not _current_settings:
        load_settings()
    _current_settings[key] = value
    save_settings()

# Initialize immediately
load_settings()
