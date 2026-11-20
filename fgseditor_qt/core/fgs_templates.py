from __future__ import annotations
import os
import shutil
import sys
from fgseditor_qt.core.app_paths import get_base_dir, get_user_data_dir
from fgseditor_qt.core.fgs_parser import parse_fgs_events
from fgseditor_qt.math.fgs_math import natural_sort_key


def get_system_dir() -> str:
    base_dir = os.path.normpath(os.path.join(get_base_dir(), "Templates", "system"))
    if not os.path.isdir(base_dir) and hasattr(sys, "_MEIPASS"):
        meipass_dir = os.path.normpath(os.path.join(sys._MEIPASS, "Templates", "system"))
        if os.path.isdir(meipass_dir):
            return meipass_dir
    return base_dir


def get_user_dir() -> str:
    return os.path.normpath(os.path.join(get_user_data_dir(), "Templates", "user"))


def _ensure_dirs():
    for d in (get_system_dir(), get_user_dir()):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def list_templates(folder_type: str) -> list[str]:
    _ensure_dirs()
    target_dir = get_system_dir() if folder_type == "system" else get_user_dir()
    templates = []
    if os.path.isdir(target_dir):
        for fname in os.listdir(target_dir):
            base, ext = os.path.splitext(fname)
            if ext.lower() == ".txt":
                templates.append(base)
    return sorted(templates, key=natural_sort_key)


def load_template_event(folder_type: str, name: str) -> dict | None:
    _ensure_dirs()
    target_dir = get_system_dir() if folder_type == "system" else get_user_dir()
    path = os.path.join(target_dir, f"{name}.txt")
    if not os.path.isfile(path) and os.path.isdir(target_dir):
        for fname in os.listdir(target_dir):
            base, ext = os.path.splitext(fname)
            if base == name and ext.lower() == ".txt":
                path = os.path.join(target_dir, fname)
                break
    if not os.path.isfile(path):
        return None
    
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
        
    _, events = parse_fgs_events(content)
    if not events:
        return None
    return events[0]

def import_user_template(filepath: str) -> str | None:
    _ensure_dirs()
    if not os.path.isfile(filepath):
        return None

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    parse_fgs_events(content)


    basename = os.path.basename(filepath)
    user_dir = get_user_dir()
    dst_path = os.path.join(user_dir, basename)
    if os.path.abspath(filepath) != os.path.abspath(dst_path):
        shutil.copy2(filepath, dst_path)
    return os.path.splitext(basename)[0]
