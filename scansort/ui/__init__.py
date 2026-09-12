"""UI package providing System Tray and Settings Dialog."""

from scansort.ui.drop_zone import DropZoneWindow, open_drop_zone_window
from scansort.ui.icon import get_tray_icon
from scansort.ui.review import ReviewDialog, open_review_dialog
from scansort.ui.settings import SettingsDialog, open_settings_dialog
from scansort.ui.tray import SystemTrayApp

__all__ = [
    "SettingsDialog",
    "SystemTrayApp",
    "ReviewDialog",
    "DropZoneWindow",
    "get_tray_icon",
    "open_settings_dialog",
    "open_review_dialog",
    "open_drop_zone_window",
]
