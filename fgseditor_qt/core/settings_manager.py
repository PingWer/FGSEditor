import os
import json
from fgseditor_qt.core.app_paths import get_base_dir, get_user_data_dir


def get_settings_file() -> str:
    base_file = os.path.join(get_base_dir(), "settings.json")
    if os.path.exists(base_file) and os.access(base_file, os.W_OK):
        return base_file
    if os.access(get_base_dir(), os.W_OK):
        return base_file
    return os.path.join(get_user_data_dir(), "settings.json")


DEFAULT_SETTINGS = {
    "preferred_backend": "regrain",
    "regrain_path": "",
    "grav1synth_path": "",
    "av_denoise_path": "",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "default_fps": "23.976",
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
    "last_video_dir": "",
    "last_fgs_dir": "",
    "last_template_dir": "",
    "geometry_main_window": "",
    "geometry_dynamic_timeline": "",
    "geometry_event_editor": "",
}

_current_settings = {}


def load_settings():
    global _current_settings
    _current_settings = dict(DEFAULT_SETTINGS)

    base_file = os.path.join(get_base_dir(), "settings.json")
    if os.path.exists(base_file):
        try:
            with open(base_file, "r", encoding="utf-8") as f:
                _current_settings.update(json.load(f))
        except Exception:
            pass

    target_file = get_settings_file()
    if target_file != base_file and os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                _current_settings.update(json.load(f))
        except Exception:
            pass



def save_settings():
    try:
        target_file = get_settings_file()
        os.makedirs(os.path.dirname(os.path.abspath(target_file)), exist_ok=True)
        tmp_file = target_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_current_settings, f, indent=4)
        os.replace(tmp_file, target_file)
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


def get_dialog_dir(key: str) -> str:
    path = get_setting(key, "")
    if path and os.path.isdir(path):
        return path
    return get_base_dir()


def update_dialog_dir(key: str, file_path: str | None) -> None:
    if file_path:
        try:
            parent = os.path.dirname(os.path.abspath(file_path))
            if os.path.isdir(parent):
                set_setting(key, parent)
        except Exception:
            pass


def restore_window_geometry(window, setting_key: str) -> bool:
    geom_hex = get_setting(setting_key)
    if not geom_hex:
        return False
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QGuiApplication

        ba = QByteArray.fromHex(geom_hex.encode("ascii"))
        if ba.isEmpty():
            return False

        restored = window.restoreGeometry(ba)
        if not restored:
            return False

        screens = QGuiApplication.screens()
        window_rect = window.geometry()
        is_visible = False
        for screen in screens:
            avail = screen.availableGeometry()
            if avail.intersects(window_rect):
                inter = avail.intersected(window_rect)
                if inter.width() >= 60 and inter.height() >= 60:
                    is_visible = True
                    break

        if not is_visible and screens:
            primary = QGuiApplication.primaryScreen() or screens[0]
            avail = primary.availableGeometry()
            w = min(window_rect.width(), avail.width())
            h = min(window_rect.height(), avail.height())
            window.resize(w, h)
            x = avail.x() + max(0, (avail.width() - w) // 2)
            y = avail.y() + max(0, (avail.height() - h) // 2)
            window.move(x, y)

        return True
    except Exception:
        return False


def save_window_geometry(window, setting_key: str) -> None:
    try:
        if window.isMinimized():
            return
        geom_hex = window.saveGeometry().toHex().data().decode("ascii")
        set_setting(setting_key, geom_hex)
    except Exception:
        pass


load_settings()

