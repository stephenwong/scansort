"""Settings modal dialog for ScanSort using Tkinter."""

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from scansort.classification.taxonomy import build_taxonomy_tree, scan_documents_folders
from scansort.core.config import AppConfig, load_config, save_config
from scansort.core.constants import SUPPORTED_GEMINI_MODELS
from scansort.platform.autorun import (
    disable_autorun,
    enable_autorun,
    is_autorun_enabled,
)
from scansort.platform.secrets import (
    get_api_key,
    mask_api_key,
    set_api_key,
)
from scansort.platform.toasts import show_toast

logger = logging.getLogger(__name__)

_ACTIVE_DIALOG_INSTANCE: "SettingsDialog | None" = None
_DIALOG_LOCK = threading.Lock()


def open_settings_dialog(
    config: AppConfig | None = None,
    on_applied: Callable[[AppConfig], None] | None = None,
) -> "SettingsDialog":
    """Open or focus the singleton settings dialog window.

    Thread-safe via ``_DIALOG_LOCK``; returns the existing open instance if one
    is already active, or instantiates a new one.
    """
    global _ACTIVE_DIALOG_INSTANCE
    with _DIALOG_LOCK:
        if (
            _ACTIVE_DIALOG_INSTANCE is not None
            and _ACTIVE_DIALOG_INSTANCE.winfo_exists()
        ):
            _ACTIVE_DIALOG_INSTANCE.deiconify()
            _ACTIVE_DIALOG_INSTANCE.lift()
            _ACTIVE_DIALOG_INSTANCE.focus_force()
            return _ACTIVE_DIALOG_INSTANCE

        dialog = SettingsDialog(config=config, on_applied=on_applied)
        _ACTIVE_DIALOG_INSTANCE = dialog
        return dialog


class SettingsDialog(tk.Toplevel):
    """Tkinter modal window for configuring ScanSort paths, models, and options."""

    def __init__(
        self,
        master: tk.Misc | None = None,
        config: AppConfig | None = None,
        on_applied: Callable[[AppConfig], None] | None = None,
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

        self.title("ScanSort Settings")
        self.resizable(True, True)
        self.minsize(580, 620)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.config: AppConfig = config or load_config()
        self.on_applied = on_applied

        self.watch_var = tk.StringVar(value=str(self.config.watch_folder))
        self.docs_var = tk.StringVar(value=str(self.config.documents_root))
        self.api_key_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.model_var = tk.StringVar(value=self.config.gemini_model)
        self.fallback_var = tk.StringVar(value=self.config.fallback_folder)
        self.dry_run_var = tk.BooleanVar(value=self.config.dry_run)
        self.autorun_var = tk.BooleanVar(value=is_autorun_enabled())

        self._build_ui()
        self.refresh_taxonomy_tree()

    def mainloop(self, n: int = 0) -> None:
        """Run Tkinter mainloop safely, ignoring redundant concurrent calls."""
        with _DIALOG_LOCK:
            if self._mainloop_running:
                return
            self._mainloop_running = True
        try:
            super().mainloop(n)
        finally:
            with _DIALOG_LOCK:
                self._mainloop_running = False

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding="16 16 16 16")
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Monitored Drop Folder
        folder_frame = ttk.LabelFrame(
            container, text="Directories", padding="10 10 10 10"
        )
        folder_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(folder_frame, text="Scanner Drop Folder (Watch):").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        watch_entry = ttk.Entry(folder_frame, textvariable=self.watch_var)
        watch_entry.grid(row=1, column=0, sticky=tk.EW, padx=(0, 5), pady=2)
        ttk.Button(
            folder_frame, text="Browse...", command=self._browse_watch_folder
        ).grid(row=1, column=1, pady=2)

        ttk.Label(folder_frame, text="Documents Destination Root:").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 2)
        )
        docs_entry = ttk.Entry(folder_frame, textvariable=self.docs_var)
        docs_entry.grid(row=3, column=0, sticky=tk.EW, padx=(0, 5), pady=2)
        ttk.Button(
            folder_frame, text="Browse...", command=self._browse_docs_folder
        ).grid(row=3, column=1, pady=2)
        folder_frame.columnconfigure(0, weight=1)

        # 2. Taxonomy Hierarchy Explorer
        tree_frame = ttk.LabelFrame(
            container, text="Discovered Taxonomies (Hierarchy)", padding="10 10 10 10"
        )
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            tree_frame, yscrollcommand=tree_scroll.set, selectmode="browse"
        )
        self.tree.heading("#0", text="Folder Structure", anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.tree.yview)

        btn_refresh = ttk.Button(
            tree_frame, text="Refresh Folders", command=self.refresh_taxonomy_tree
        )
        btn_refresh.pack(side=tk.BOTTOM, anchor=tk.E, pady=(6, 0))

        # 3. Gemini API & Classification
        gemini_frame = ttk.LabelFrame(
            container, text="Gemini AI Configuration", padding="10 10 10 10"
        )
        gemini_frame.pack(fill=tk.X, pady=(0, 10))

        current_key = get_api_key()
        masked_display = mask_api_key(current_key)
        key_label_text = f"API Key: (Current in vault: {masked_display})"
        ttk.Label(gemini_frame, text=key_label_text).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=2
        )

        self.key_entry = ttk.Entry(
            gemini_frame, textvariable=self.api_key_var, show="*"
        )
        self.key_entry.grid(row=1, column=0, sticky=tk.EW, padx=(0, 5), pady=2)

        chk_show = ttk.Checkbutton(
            gemini_frame,
            text="Show",
            variable=self.show_key_var,
            command=self._toggle_show_key,
        )
        chk_show.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(
            gemini_frame,
            text="Leave blank to retain current key stored in OS Credential Vault.",
            font=("TkDefaultFont", 8, "italic"),
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 6))

        ttk.Label(gemini_frame, text="Gemini Model:").grid(
            row=3, column=0, sticky=tk.W, pady=(4, 2)
        )
        model_combo = ttk.Combobox(
            gemini_frame,
            textvariable=self.model_var,
            values=list(SUPPORTED_GEMINI_MODELS),
            state="readonly",
        )
        model_combo.grid(row=4, column=0, sticky=tk.W, pady=2)

        ttk.Label(gemini_frame, text="Fallback Folder:").grid(
            row=5, column=0, sticky=tk.W, pady=(6, 2)
        )
        ttk.Entry(gemini_frame, textvariable=self.fallback_var).grid(
            row=6, column=0, sticky=tk.EW, pady=2
        )
        gemini_frame.columnconfigure(0, weight=1)

        # 4. Toggles
        opts_frame = ttk.Frame(container)
        opts_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Checkbutton(
            opts_frame, text="Start ScanSort with Windows", variable=self.autorun_var
        ).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(
            opts_frame,
            text="Dry-Run Mode (simulate filing without moving files)",
            variable=self.dry_run_var,
        ).pack(anchor=tk.W, pady=2)

        # 5. Buttons
        btn_bar = ttk.Frame(container)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        ttk.Button(btn_bar, text="Save & Apply", command=self.on_save).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _toggle_show_key(self) -> None:
        self.key_entry.config(show="" if self.show_key_var.get() else "*")

    def _browse_watch_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title="Select Scanner Drop Folder",
            initialdir=self.watch_var.get(),
            mustexist=True,
        )
        if chosen:
            self.watch_var.set(str(Path(chosen).resolve()))

    def _browse_docs_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title="Select Documents Destination Root",
            initialdir=self.docs_var.get(),
            mustexist=True,
        )
        if chosen:
            self.docs_var.set(str(Path(chosen).resolve()))
            self.refresh_taxonomy_tree()

    def refresh_taxonomy_tree(self) -> None:
        """Scan current documents folder and populate treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        docs_path = Path(self.docs_var.get())
        if not docs_path.is_dir():
            return

        folders = scan_documents_folders(
            docs_root=docs_path,
            max_depth=self.config.max_folder_depth,
            fallback_folder=self.fallback_var.get(),
        )
        tree_dict = build_taxonomy_tree(folders)

        def _insert_nodes(parent_id: str, node: dict) -> None:
            for name, children in sorted(node.items()):
                item_id = self.tree.insert(parent_id, tk.END, text=name, open=True)
                _insert_nodes(item_id, children)

        _insert_nodes("", tree_dict)

    def on_save(self) -> None:
        """Validate inputs, save configuration and credentials, and notify."""
        watch_raw = self.watch_var.get().strip()
        docs_raw = self.docs_var.get().strip()
        model_val = self.model_var.get().strip()
        fallback_val = self.fallback_var.get().strip()

        if not watch_raw:
            messagebox.showerror(
                "Configuration Error",
                "Scanner Drop Folder cannot be empty.",
                parent=self,
            )
            return
        if not docs_raw:
            messagebox.showerror(
                "Configuration Error",
                "Documents Destination Root cannot be empty.",
                parent=self,
            )
            return

        watch_path = Path(watch_raw).resolve()
        docs_path = Path(docs_raw).resolve()

        try:
            updated_dict = self.config.model_dump()
            updated_dict["watch_folder"] = watch_path
            updated_dict["documents_root"] = docs_path
            updated_dict["gemini_model"] = model_val
            updated_dict["fallback_folder"] = fallback_val
            updated_dict["dry_run"] = self.dry_run_var.get()
            updated_dict["start_on_boot"] = self.autorun_var.get()
            new_cfg = AppConfig(**updated_dict)
            new_cfg.ensure_directories()
        except (ValueError, OSError) as e:
            messagebox.showerror("Configuration Error", str(e), parent=self)
            return

        new_key = self.api_key_var.get().strip()
        if new_key:
            try:
                set_api_key(new_key)
            except (ValueError, OSError) as e:
                messagebox.showerror(
                    "API Key Error", f"Failed to save API key: {e}", parent=self
                )
                return

        try:
            save_config(new_cfg)
        except OSError as e:
            messagebox.showerror(
                "Save Error", f"Failed to save config file: {e}", parent=self
            )
            return

        try:
            if self.autorun_var.get():
                enable_autorun()
            else:
                disable_autorun()
        except OSError as e:
            logger.warning("Could not update autorun setting: %s", e)

        self.config = new_cfg
        if self.on_applied is not None:
            try:
                self.on_applied(new_cfg)
            except Exception as e:  # noqa: BLE001
                logger.error("Error in on_applied callback: %s", e)

        show_toast("ScanSort Settings", "Settings saved and applied successfully.")
        self.destroy()

    def destroy(self) -> None:
        global _ACTIVE_DIALOG_INSTANCE
        with _DIALOG_LOCK:
            if _ACTIVE_DIALOG_INSTANCE is self:
                _ACTIVE_DIALOG_INSTANCE = None
        super().destroy()
        if self._owns_root and self.master:
            with contextlib.suppress(tk.TclError):
                self.master.destroy()
