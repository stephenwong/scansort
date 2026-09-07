"""UI package providing System Tray and Settings Dialog."""

from scansort.ui.icon import get_tray_icon
from scansort.ui.settings import SettingsDialog, open_settings_dialog
from scansort.ui.tray import SystemTrayApp

__all__ = [
    "SettingsDialog",
    "SystemTrayApp",
    "get_tray_icon",
    "open_settings_dialog",
]
