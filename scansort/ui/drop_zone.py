"""Quick File & Drop Zone modal dialog for ScanSort using Tkinter."""

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from scansort.core.config import AppConfig, load_config
from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.pipeline.coordinator import ScanSortPipeline
from scansort.platform.toasts import show_toast

logger = logging.getLogger(__name__)

_ACTIVE_DROP_ZONE_INSTANCE: "DropZoneWindow | None" = None
_DROP_ZONE_LOCK = threading.Lock()


def open_drop_zone_window(
    master: tk.Misc | None = None,
    config: AppConfig | None = None,
    pipeline: Any = None,
    on_filed: Callable[[Path], None] | None = None,
) -> "DropZoneWindow":
    """Open or focus the singleton Drop Zone window."""
    global _ACTIVE_DROP_ZONE_INSTANCE
    with _DROP_ZONE_LOCK:
        existing = _ACTIVE_DROP_ZONE_INSTANCE
        alive = False
        if existing is not None:
            with contextlib.suppress(tk.TclError):
                alive = existing.winfo_exists()
        if alive:
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return existing

        dialog = DropZoneWindow(
            master=master,
            config=config,
            pipeline=pipeline,
            on_filed=on_filed,
        )
        _ACTIVE_DROP_ZONE_INSTANCE = dialog
        return dialog


class DropZoneWindow(tk.Toplevel):
    """Tkinter window providing a quick-filing drop target and file picker."""

    def __init__(
        self,
        master: tk.Misc | None = None,
        config: AppConfig | None = None,
        pipeline: Any = None,
        on_filed: Callable[[Path], None] | None = None,
    ) -> None:
        self._owns_root = False
        self._mainloop_running = False
        if master is None:
            root = tk.Tk()
            root.withdraw()
            super().__init__(root)
            self._owns_root = True
        else:
            super().__init__(master)

        self.title("ScanSort Quick File & Drop Zone")
        self.resizable(True, True)
        self.minsize(440, 320)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.app_config: AppConfig = config or load_config()
        self.pipeline = pipeline or ScanSortPipeline(config=self.app_config)
        self.on_filed = on_filed

        self._processing = False
        self.copy_var = tk.BooleanVar(value=False)
        self.topmost_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready to file documents.")

        self._build_ui()

    def mainloop(self, n: int = 0) -> None:
        """Run Tkinter mainloop safely, ignoring redundant concurrent calls."""
        with _DROP_ZONE_LOCK:
            if self._mainloop_running:
                return
            self._mainloop_running = True
        try:
            super().mainloop(n)
        finally:
            with _DROP_ZONE_LOCK:
                self._mainloop_running = False

    def destroy(self) -> None:
        """Destroy the window and release the singleton registration."""
        global _ACTIVE_DROP_ZONE_INSTANCE
        with contextlib.suppress(tk.TclError):
            super().destroy()
        with _DROP_ZONE_LOCK:
            if _ACTIVE_DROP_ZONE_INSTANCE is self:
                _ACTIVE_DROP_ZONE_INSTANCE = None

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding="16 16 16 16")
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Drop Target Box
        target_frame = ttk.LabelFrame(
            container, text="Filing Drop Zone", padding="16 16 16 16"
        )
        target_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        lbl_instruct = ttk.Label(
            target_frame,
            text="Select digital PDFs or image scans to file into Documents:",
            wraplength=380,
            justify=tk.CENTER,
            font=("TkDefaultFont", 10),
        )
        lbl_instruct.pack(pady=(4, 12))

        btn_bar = ttk.Frame(target_frame)
        btn_bar.pack(pady=6)

        btn_browse = ttk.Button(
            btn_bar, text="Browse Document(s)...", command=self.browse_files
        )
        btn_browse.pack(side=tk.LEFT, padx=6)

        btn_paste = ttk.Button(
            btn_bar, text="Paste Clipboard Path", command=self.paste_from_clipboard
        )
        btn_paste.pack(side=tk.LEFT, padx=6)

        # 2. Options
        opts_frame = ttk.Frame(container)
        opts_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Checkbutton(
            opts_frame,
            text="Preserve original file (copy into taxonomy)",
            variable=self.copy_var,
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Checkbutton(
            opts_frame,
            text="Always on top",
            variable=self.topmost_var,
            command=self._toggle_topmost,
        ).pack(side=tk.LEFT)

        # 3. Status Bar & Progress
        status_frame = ttk.LabelFrame(
            container, text="Activity Status", padding="8 8 8 8"
        )
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.lbl_status = ttk.Label(
            status_frame, textvariable=self.status_var, font=("TkDefaultFont", 9)
        )
        self.lbl_status.pack(fill=tk.X, pady=(0, 4))

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X)

    def _toggle_topmost(self) -> None:
        self.attributes("-topmost", self.topmost_var.get())

    def browse_files(self) -> None:
        """Open native file dialog to select documents to file."""
        chosen = filedialog.askopenfilenames(
            parent=self,
            title="Select Documents to File",
            filetypes=[
                (
                    "Supported Documents",
                    "*.pdf *.jpg *.jpeg *.png *.tiff *.tif",
                ),
                ("All Files", "*.*"),
            ],
        )
        if chosen:
            paths = [Path(p) for p in chosen]
            self.file_documents(paths)

    def paste_from_clipboard(self) -> None:
        """Read a file path from the clipboard and file it."""
        try:
            raw = self.clipboard_get().strip().strip("\"'")
            candidate = Path(raw)
            if candidate.exists():
                self.file_documents([candidate])
            else:
                self.status_var.set(f"Clipboard path not found: {raw}")
        except Exception as e:  # noqa: BLE001
            self.status_var.set(f"Could not read clipboard: {e}")

    def file_documents(self, file_paths: list[Path]) -> None:
        """Process documents asynchronously on a background thread."""
        if self._processing:
            self.status_var.set("Already processing documents; please wait...")
            return
        self._processing = True
        copy_mode = self.copy_var.get()
        self.progress.start(10)
        self.status_var.set(f"Processing {len(file_paths)} document(s)...")

        def _worker():
            try:
                self._process_paths_sync(file_paths, copy_mode)
            finally:
                with contextlib.suppress(Exception):
                    self.after(0, self._on_worker_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_worker_done(self) -> None:
        """Reset the busy guard and stop the progress bar on the Tk thread."""
        self._processing = False
        with contextlib.suppress(Exception):
            self.progress.stop()

    def _set_status(self, text: str) -> None:
        """Update the status label, marshalling off-thread calls into the Tk event loop."""
        if threading.current_thread() is threading.main_thread():
            self.status_var.set(text)
            return
        with contextlib.suppress(Exception):
            self.after(0, lambda: self.status_var.set(text))

    def _process_paths_sync(
        self, file_paths: list[Path], copy_mode: bool = False
    ) -> None:
        """Process document paths synchronously.

        Args:
            file_paths: Resolvable document paths to file.
            copy_mode: Read from the UI thread by file_documents; preserve original
                sources when True.
        """
        success_count = 0
        error_count = 0
        last_dest: Path | None = None

        for path in file_paths:
            resolved = path.resolve()
            if not resolved.is_file():
                logger.warning("Drop Zone file not found: %s", path)
                error_count += 1
                continue

            if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
                logger.warning(
                    "Unsupported file type in Drop Zone: %s", resolved.suffix
                )
                error_count += 1
                continue

            try:
                dest = self.pipeline.process_file(resolved, preserve_source=copy_mode)
            except Exception as e:  # noqa: BLE001
                logger.error("Error filing %s: %s", resolved.name, e)
                error_count += 1
                continue

            if dest is not None:
                success_count += 1
                last_dest = dest
            else:
                error_count += 1

        # Notify once per batch: rebuilds are expensive (history parse + tree
        # scan), so per-file callbacks would make an N-file batch O(N^2).
        if last_dest is not None and self.on_filed:
            try:
                self.on_filed(last_dest)
            except Exception as e:  # noqa: BLE001
                logger.error("on_filed callback failed for %s: %s", last_dest, e)

        if error_count == 0:
            status = f"Filed {success_count} document(s) successfully."
        else:
            status = f"Filed {success_count} document(s) with {error_count} error(s)."

        self._set_status(status)
        show_toast("ScanSort Drop Zone", status)
