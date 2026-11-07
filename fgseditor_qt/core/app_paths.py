from __future__ import annotations

import os
import shutil
import subprocess
import sys

NO_WINDOW_FLAG: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_images_dir() -> str:
    if hasattr(sys, "_MEIPASS"):
        meipass_images = os.path.join(sys._MEIPASS, "images")
        if os.path.isdir(meipass_images):
            return meipass_images
        return sys._MEIPASS
    return os.path.join(get_base_dir(), "images")


def get_image_path(filename: str) -> str:
    img_path = os.path.join(get_images_dir(), filename)
    if os.path.isfile(img_path):
        return img_path
    fallback = os.path.join(get_base_dir(), filename)
    if os.path.isfile(fallback):
        return fallback
    if hasattr(sys, "_MEIPASS"):
        meipass_fallback = os.path.join(sys._MEIPASS, filename)
        if os.path.isfile(meipass_fallback):
            return meipass_fallback
    return img_path


def is_temp_filepath(filepath: str | None) -> bool:
    if not filepath:
        return True
    base = os.path.basename(filepath).lower()
    if base.startswith(".tmp") or base.startswith("tmp_") or "_temp." in base or base.endswith("_temp.tbl"):
        return True
    try:
        import tempfile
        tmp_dir = os.path.abspath(tempfile.gettempdir())
        fp_dir = os.path.abspath(os.path.dirname(filepath))
        if os.path.commonpath([fp_dir, tmp_dir]) == tmp_dir:
            return True
    except Exception:
        pass
    return False


def get_user_data_dir() -> str:
    base = get_base_dir()
    if os.access(base, os.W_OK):
        return base
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        p = os.path.join(appdata, "FGSEditor")
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        p = os.path.join(xdg_config, "fgseditor")
    try:
        os.makedirs(p, exist_ok=True)
        return p
    except OSError:
        import tempfile
        return tempfile.gettempdir()


def find_executable(name: str, setting_key: str | None = None) -> str | None:
    if setting_key:
        from fgseditor_qt.core.settings_manager import get_setting

        user_path = get_setting(setting_key, "").strip().strip('"').strip("'")
        if user_path:
            user_path = os.path.expanduser(os.path.expandvars(user_path))
            if sys.platform == "win32" and not user_path.lower().endswith(".exe") and os.path.isfile(user_path + ".exe"):
                user_path += ".exe"
            if os.path.isfile(user_path):
                if sys.platform != "win32" and not os.access(user_path, os.X_OK):
                    try:
                        os.chmod(user_path, os.stat(user_path).st_mode | 0o755)
                    except OSError:
                        pass
                if os.access(user_path, os.X_OK):
                    return user_path
            which_user = shutil.which(user_path)
            if not which_user and sys.platform != "win32":
                which_user = shutil.which(f"{user_path}.exe")
            if which_user and os.path.isfile(which_user):
                if sys.platform != "win32" and not os.access(which_user, os.X_OK):
                    try:
                        os.chmod(which_user, os.stat(which_user).st_mode | 0o755)
                    except OSError:
                        pass
                if os.access(which_user, os.X_OK):
                    return which_user

    base = get_base_dir()
    if sys.platform == "win32":
        candidates = [f"{name}.exe", name]
    else:
        candidates = [name, f"{name}.exe"]

    for cand in candidates:
        cand_path = os.path.join(base, cand)
        if os.path.isfile(cand_path):
            if sys.platform != "win32" and not os.access(cand_path, os.X_OK):
                try:
                    os.chmod(cand_path, os.stat(cand_path).st_mode | 0o755)
                except OSError:
                    pass
            if os.access(cand_path, os.X_OK):
                return cand_path

    found = shutil.which(name)
    if not found and sys.platform != "win32":
        found = shutil.which(f"{name}.exe")
    if found and os.path.isfile(found):
        if sys.platform != "win32" and not os.access(found, os.X_OK):
            try:
                os.chmod(found, os.stat(found).st_mode | 0o755)
            except OSError:
                pass
        if os.access(found, os.X_OK):
            return found

    return None

