from . import core
from . import math
from . import tools
from . import ui

import sys

from .core import (
    app_paths,
    settings_manager,
    fgs_parser,
    fgs_save,
    fgs_templates,
    fgs_size_table,
    binary_x265_FGS,
    AFGS_TABLE_and_SEEDS,
)
from .math import (
    fgs_math,
    fgs_grain_sim,
    svt_photon_noise,
    fgs_optimizer,
    time_utils,
)
from .tools import (
    fgs_tools,
    video_probe,
    grav1synth,
)
from .ui.static import single_editor
from .ui.dynamic import dynamic_ui, event_editor_window
from .ui.dialogs import (
    fgs_auto_create_dialog,
    fgs_optimizer_dialog,
    fgs_warning_dialog,
    settings_dialog,
)
from .ui.widgets import (
    grain_preview,
    params_sidebar,
    plotter,
    shortcuts,
)
from .ui.panels import (
    panel_fgs_value,
    panel_grain_size,
    panel_photon_noise,
    panel_templates,
    panel_time,
    tabs_widget,
    utils,
)
from . import panels
from .ui import main_ui

for _mod_name, _mod in list(locals().items()):
    if not _mod_name.startswith('_'):
        sys.modules[f"fgseditor_qt.{_mod_name}"] = _mod

