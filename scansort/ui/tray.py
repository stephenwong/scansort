"""System tray integration for ScanSort using pystray and Pillow."""

import contextlib
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pystray

from scansort.classification.taxonomy import (
    build_taxonomy_tree,
    run_rescan,
    scan_documents_folders,
)
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import HISTORY_CSV_NAME
from scansort.core.fs import open_in_file_manager
from scansort.pipeline.undo import run_undo
from scansort.platform.toasts import show_toast
from scansort.ui.icon import get_tray_icon
from scansort.ui.settings import open_settings_dialog
from scansort.updater.feed import check_for_updates

logger = logging.getLogger(__name__)


class SystemTrayApp:
    """Coordinates the system tray icon, context menu, and ScanSort pipeline lifecycle."""

    def __init__(
        self,
        config: AppConfig,
        watcher: Any = None,
        pipeline: Any = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.config = config
        self.watcher = watcher
        self.pipeline = pipeline
        self.stop_event = stop_event or threading.Event()
        self._lock = threading.Lock()

        self.icon = pystray.Icon(
            name="ScanSort",
            icon=get_tray_icon(paused=self.is_paused()),
            title="ScanSort",
            menu=self._build_menu(),
        )

    def is_paused(self) -> bool:
        """Check whether the drop folder watcher is currently paused."""
        if self.watcher is not None and hasattr(self.watcher, "is_paused"):
            return self.watcher.is_paused()
        return False

    def _build_taxonomy_submenus(self) -> pystray.Menu:
        """Dynamically build nested submenus reflecting destination folder taxonomy."""
        folders = scan_documents_folders(
            docs_root=self.config.documents_root,
            max_depth=self.config.max_folder_depth,
            fallback_folder=self.config.fallback_folder,
        )
        if not folders:
            return pystray.Menu(
                pystray.MenuItem(
                    "No destination folders discovered", None, enabled=False
                )
            )

        tree = build_taxonomy_tree(folders)

        def _build_recursive(
            node: dict, current_rel_path: str = ""
        ) -> list[pystray.MenuItem]:
            items: list[pystray.MenuItem] = []
            for name, children in sorted(node.items()):
                rel_path = f"{current_rel_path}/{name}" if current_rel_path else name
                target_dir = self.config.documents_root / rel_path

                def _make_action(dir_to_open: Path) -> Callable[[], None]:
                    return lambda: open_in_file_manager(dir_to_open)

                if children:
                    sub_items = _build_recursive(children, rel_path)
                    # Include an option at the top to open the folder itself
                    sub_items.insert(
                        0,
                        pystray.MenuItem(
                            f"Open '{name}' folder", _make_action(target_dir)
                        ),
                    )
                    sub_items.insert(1, pystray.Menu.SEPARATOR)
                    items.append(pystray.MenuItem(name, pystray.Menu(*sub_items)))
                else:
                    items.append(pystray.MenuItem(name, _make_action(target_dir)))
            return items

        return pystray.Menu(*_build_recursive(tree))

    def _build_menu(self) -> pystray.Menu:
        """Construct the complete right-click context menu."""
        paused = self.is_paused()
        status_text = (
            "ScanSort: Monitoring Paused" if paused else "ScanSort: Monitoring Active"
        )
        pause_action_text = "Resume Monitoring" if paused else "Pause Monitoring"

        return pystray.Menu(
            pystray.MenuItem(status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_action_text, lambda icon, item: self.toggle_pause()),
            pystray.MenuItem("Undo Last Move", lambda icon, item: self.undo_last()),
            pystray.MenuItem(
                "Rescan / Refresh Taxonomies", lambda icon, item: self.rescan_taxonomy()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open Drop Folder", lambda icon, item: self.open_drop_folder()
            ),
            pystray.MenuItem(
                "Open Documents Folder", lambda icon, item: self.open_docs_folder()
            ),
            pystray.MenuItem(
                "Browse Destination Folders", self._build_taxonomy_submenus()
            ),
            pystray.MenuItem(
                "View Scan History", lambda icon, item: self.view_scan_history()
            ),
            pystray.MenuItem(
                "Open Log Folder", lambda icon, item: self.open_log_folder()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings...", lambda icon, item: self.open_settings()),
            pystray.MenuItem(
                "Check for Updates...", lambda icon, item: self.check_updates()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit ScanSort", lambda icon, item: self.exit_app()),
        )

    def toggle_pause(self) -> None:
        """Toggle the pause state of monitoring."""
        with self._lock:
            if self.is_paused():
                if self.watcher is not None and hasattr(self.watcher, "resume"):
                    self.watcher.resume()
                show_toast("ScanSort", "Monitoring resumed.")
            else:
                if self.watcher is not None and hasattr(self.watcher, "pause"):
                    self.watcher.pause()
                show_toast("ScanSort", "Monitoring paused.")

            is_now_paused = self.is_paused()
            if self.icon is not None:
                self.icon.icon = get_tray_icon(paused=is_now_paused)
                self.icon.title = f"ScanSort{' (Paused)' if is_now_paused else ''}"
                self.icon.menu = self._build_menu()

    def undo_last(self, async_task: bool = True) -> threading.Thread | None:
        """Reverse the most recent filing move and notify the user."""

        def _task():
            success, msg, _ = run_undo(self.config)
            show_toast("ScanSort Undo", msg)

        if not async_task:
            _task()
            return None
        t = threading.Thread(target=_task, daemon=True)
        t.start()
        return t

    def rescan_taxonomy(self, async_task: bool = True) -> threading.Thread | None:
        """Refresh folder taxonomy discovery."""

        def _task():
            folders = run_rescan(self.config)
            if self.pipeline is not None and hasattr(self.pipeline, "folder_mapper"):
                self.pipeline.folder_mapper.refresh()
            with self._lock:
                if self.icon is not None:
                    self.icon.menu = self._build_menu()
            show_toast(
                "ScanSort Taxonomy",
                f"Discovered {len(folders)} destination folders under Documents.",
            )

        if not async_task:
            _task()
            return None
        t = threading.Thread(target=_task, daemon=True)
        t.start()
        return t

    def open_drop_folder(self) -> None:
        """Open the monitored scanner drop directory."""
        open_in_file_manager(self.config.watch_folder)

    def open_docs_folder(self) -> None:
        """Open the root destination Documents directory."""
        open_in_file_manager(self.config.documents_root)

    def view_scan_history(self) -> None:
        """Open the filing audit history CSV (or the folder if file is absent)."""
        app_dir = get_default_app_dir()
        history_csv = app_dir / HISTORY_CSV_NAME
        if history_csv.exists():
            open_in_file_manager(history_csv)
        else:
            open_in_file_manager(app_dir)

    def open_log_folder(self) -> None:
        """Open the application data / log directory in Windows Explorer."""
        open_in_file_manager(get_default_app_dir())

    def open_settings(self) -> None:
        """Display the Tkinter settings dialog with instant hot-reload."""

        def _task():
            dialog = open_settings_dialog(
                config=self.config,
                on_applied=self.on_settings_applied,
            )
            if (
                dialog is not None
                and getattr(dialog, "_owns_root", False)
                and not getattr(dialog, "_mainloop_running", False)
            ):
                with contextlib.suppress(Exception):
                    dialog.mainloop()

        threading.Thread(
            target=_task,
            daemon=True,
        ).start()

    def check_updates(self, async_task: bool = True) -> threading.Thread | None:
        """Check for updates on GitHub Releases."""

        def _task():
            rel, err = check_for_updates(get_default_app_dir())
            if err:
                show_toast("ScanSort Update", f"Update check failed: {err}")
            elif rel:
                show_toast(
                    "ScanSort Update Available",
                    f"Version {rel.version} is available to download.",
                )
            else:
                show_toast(
                    "ScanSort Update",
                    "ScanSort is up to date. No updates available.",
                )

        if not async_task:
            _task()
            return None
        t = threading.Thread(target=_task, daemon=True)
        t.start()
        return t

    def on_settings_applied(self, new_cfg: AppConfig) -> None:
        """Hot-reload configuration changes into the active watcher and pipeline."""
        with self._lock:
            old_watch = self.config.watch_folder
            self.config = new_cfg

            if self.watcher is not None and old_watch != new_cfg.watch_folder:
                self.watcher.switch_folder(new_cfg.watch_folder)

            if self.pipeline is not None:
                self.pipeline.config = new_cfg
                if hasattr(self.pipeline, "update_config"):
                    self.pipeline.update_config(new_cfg)

            if self.icon is not None:
                self.icon.menu = self._build_menu()

    def exit_app(self) -> None:
        """Cleanly terminate the application and its worker threads."""
        self.stop_event.set()
        if self.watcher is not None and hasattr(self.watcher, "stop"):
            self.watcher.stop()
        if self.icon is not None:
            self.icon.stop()

    def start(self) -> None:
        """Launch the system tray icon in detached mode."""
        self.icon.run_detached()

    def stop(self) -> None:
        """Stop the system tray icon."""
        if self.icon is not None:
            self.icon.stop()
