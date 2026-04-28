from __future__ import annotations
import os
import shutil
from .app_paths import get_base_dir
from .fgs_parser import parse_fgs_events
from .fgs_math import natural_sort_key

def get_system_dir() -> str:
    return os.path.normpath(os.path.join(get_base_dir(), "Templates", "system"))

def get_user_dir() -> str:
    return os.path.normpath(os.path.join(get_base_dir(), "Templates", "user"))

def _ensure_dirs():
    os.makedirs(get_system_dir(), exist_ok=True)
    os.makedirs(get_user_dir(), exist_ok=True)

def list_templates(folder_type: str) -> list[str]:
    _ensure_dirs()
    target_dir = get_system_dir() if folder_type == "system" else get_user_dir()
    templates = []
    if os.path.isdir(target_dir):
        for fname in os.listdir(target_dir):
            base, ext = os.path.splitext(fname)
            if ext == ".txt":
                templates.append(base)
    return sorted(templates, key=natural_sort_key)

def load_template_event(folder_type: str, name: str) -> dict | None:
    _ensure_dirs()
    target_dir = get_system_dir() if folder_type == "system" else get_user_dir()
    path = os.path.join(target_dir, f"{name}.txt")
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
    basename = os.path.basename(filepath)
    user_dir = get_user_dir()
    dst_path = os.path.join(user_dir, basename)
    if os.path.abspath(filepath) != os.path.abspath(dst_path):
        shutil.copy2(filepath, dst_path)
    return os.path.splitext(basename)[0]
