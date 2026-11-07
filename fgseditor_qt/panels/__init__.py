import sys
from fgseditor_qt.ui import panels as _ui_panels

__path__ = _ui_panels.__path__
from fgseditor_qt.ui.panels import *

for _name in dir(_ui_panels):
    if not _name.startswith("_"):
        _attr = getattr(_ui_panels, _name)
        if hasattr(_attr, "__file__"):
            sys.modules[f"fgseditor_qt.panels.{_name}"] = _attr
