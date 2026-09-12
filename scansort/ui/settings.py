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
from scansort.platform.context_menu import (
    disable_context_menu,
    enable_context_menu,
    is_context_menu_enabled,
)
from scansort.platform.secrets import (
    delete_api_key,
    get_api_key,
    mask_api_key,
    set_api_key,
)
from scansort.platform.toasts import show_toast
from scansort.ui.singleton_window import SingletonToplevel

logger = logging.getLogger(__name__)

_ACTIVE_DIALOG_INSTANCE: "SettingsDialog | None" = None
_DIALOG_LOCK = threading.Lock()

_FOOTNOTE_FONT = ("TkDefaultFont", 8, "italic")


def open_settings_dialog(
    config: AppConfig | None = None,
    on_applied: Callable[[AppConfig], None] | None = None,
) -> "SettingsDialog":
    """Open or focus the singleton settings dialog window.

    Thread-safe via ``_DIALOG_LOCK``; returns the existing open instance if one
    is already active, or instantiates a new one.
    """
    existing = SettingsDialog.focus_existing()
    if existing is not None:
        return existing

    # Construct outside the lock: __init__ performs keyring/registry I/O and a
    # recursive taxonomy scan, which must not block other tray interactions.
    dialog = SettingsDialog(config=config, on_applied=on_applied)
    return SettingsDialog.register_or_existing(dialog)


class SettingsDialog(SingletonToplevel):
    """Tkinter modal window for configuring ScanSort paths, models, and options."""

    @classmethod
    def _instance(cls) -> "SettingsDialog | None":
        return _ACTIVE_DIALOG_INSTANCE

    @classmethod
    def _set_instance(cls, value: "SettingsDialog | None") -> None:
        global _ACTIVE_DIALOG_INSTANCE
        _ACTIVE_DIALOG_INSTANCE = value

    @classmethod
    def _lock(cls) -> threading.Lock:
        return _DIALOG_LOCK

    def __init__(
        self,
        master: tk.Misc | None = None,
        config: AppConfig | None = None,
        on_applied: Callable[[AppConfig], None] | None = None,
    ) -> None:
        super().__init__(master)

        self.title("ScanSort Settings")
        self.resizable(True, True)
        self.minsize(580, 620)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.app_config: AppConfig = config or load_config()
        self.on_applied = on_applied

        self.watch_var = tk.StringVar(value=str(self.app_config.watch_folder))
        self.docs_var = tk.StringVar(value=str(self.app_config.documents_root))
        self.api_key_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.model_var = tk.StringVar(value=self.app_config.gemini_model)
        self.fallback_var = tk.StringVar(value=self.app_config.fallback_folder)
        self.dry_run_var = tk.BooleanVar(value=self.app_config.dry_run)
        self.autorun_var = tk.BooleanVar(value=is_autorun_enabled())
        self.context_menu_var = tk.BooleanVar(value=is_context_menu_enabled())

        self._build_ui()
        self.refresh_taxonomy_tree()

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
            font=_FOOTNOTE_FONT,
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
            text="Enable 'File with ScanSort' in Explorer context menu",
            variable=self.context_menu_var,
        ).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(
            opts_frame,
            text="Dry-Run Mode (simulate filing without moving files)",
            variable=self.dry_run_var,
        ).pack(anchor=tk.W, pady=2)
        ttk.Button(
            opts_frame,
            text="Open Quick File / Drop Zone...",
            command=self._open_drop_zone,
        ).pack(anchor=tk.W, pady=(6, 2))

        # 5. Buttons
        btn_bar = ttk.Frame(container)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        ttk.Button(btn_bar, text="Save & Apply", command=self.on_save).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _toggle_show_key(self) -> None:
        self.key_entry.config(show="" if self.show_key_var.get() else "*")

    def _browse_folder(
        self,
        var: tk.StringVar,
        title: str,
        on_choose: Callable[[], None] | None = None,
    ) -> None:
        """Prompt for a directory and store its resolved path in *var*."""
        chosen = filedialog.askdirectory(
            parent=self,
            title=title,
            initialdir=var.get(),
            mustexist=True,
        )
        if chosen:
            var.set(str(Path(chosen).resolve()))
            if on_choose is not None:
                on_choose()

    def _browse_watch_folder(self) -> None:
        self._browse_folder(self.watch_var, "Select Scanner Drop Folder")

    def _browse_docs_folder(self) -> None:
        self._browse_folder(
            self.docs_var,
            "Select Documents Destination Root",
            on_choose=self.refresh_taxonomy_tree,
        )

    def refresh_taxonomy_tree(self) -> None:
        """Scan current documents folder and populate treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        docs_path = Path(self.docs_var.get())
        if not docs_path.is_dir():
            return

        folders = scan_documents_folders(
            docs_root=docs_path,
            max_depth=self.app_config.max_folder_depth,
            fallback_folder=self.fallback_var.get(),
        )
        tree_dict = build_taxonomy_tree(folders)

        def _insert_nodes(parent_id: str, node: dict) -> None:
            for name, children in sorted(node.items()):
                item_id = self.tree.insert(parent_id, tk.END, text=name, open=True)
                _insert_nodes(item_id, children)

        _insert_nodes("", tree_dict)

    def _resolve_new_config(self) -> AppConfig | None:
        """Validate dialog inputs and build the updated config, or None on error."""
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
            return None
        if not docs_raw:
            messagebox.showerror(
                "Configuration Error",
                "Documents Destination Root cannot be empty.",
                parent=self,
            )
            return None

        watch_path = Path(watch_raw).resolve()
        docs_path = Path(docs_raw).resolve()
        try:
            updated_dict = self.app_config.model_dump()
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
            return None
        return new_cfg

    def _persist_config_with_key_rollback(
        self, new_cfg: AppConfig, new_key: str, prior_key: str | None
    ) -> bool:
        """Persist *new_cfg*, rolling back the saved credential on failure."""
        try:
            save_config(new_cfg)
            return True
        except OSError as e:
            # Roll back the credential so the vault does not disagree with the
            # config that failed to persist.
            if new_key:
                with contextlib.suppress(OSError, ValueError):
                    if prior_key:
                        set_api_key(prior_key)
                    else:
                        delete_api_key()
            messagebox.showerror(
                "Save Error", f"Failed to save config file: {e}", parent=self
            )
            return False

    def _apply_system_integrations(self, new_cfg: AppConfig) -> tuple[bool, bool]:
        """Reconcile autorun and context-menu OS state; returns (autorun_ok, menu_ok)."""
        autorun_ok = True
        try:
            if self.autorun_var.get():
                autorun_ok = enable_autorun()
            else:
                autorun_ok = disable_autorun()
        except OSError as e:
            logger.warning("Could not update autorun setting: %s", e)
            autorun_ok = False
        if not autorun_ok:
            # Reconcile the persisted flag with the real OS state.
            actual_autorun = is_autorun_enabled()
            if new_cfg.start_on_boot != actual_autorun:
                new_cfg.start_on_boot = actual_autorun
                with contextlib.suppress(OSError):
                    save_config(new_cfg)

        try:
            if self.context_menu_var.get():
                context_menu_ok = enable_context_menu()
            else:
                context_menu_ok = disable_context_menu()
            if not context_menu_ok:
                logger.warning("Could not update context menu setting.")
        except OSError as e:
            logger.warning("Could not update context menu setting: %s", e)
            context_menu_ok = False
        return autorun_ok, context_menu_ok

    def on_save(self) -> None:
        """Validate inputs, save configuration and credentials, and notify."""
        new_cfg = self._resolve_new_config()
        if new_cfg is None:
            return

        new_key = self.api_key_var.get().strip()
        prior_key: str | None = None
        if new_key:
            prior_key = get_api_key()
            try:
                set_api_key(new_key)
            except (ValueError, OSError) as e:
                messagebox.showerror(
                    "API Key Error", f"Failed to save API key: {e}", parent=self
                )
                return

        if not self._persist_config_with_key_rollback(new_cfg, new_key, prior_key):
            return

        autorun_ok, context_menu_ok = self._apply_system_integrations(new_cfg)

        self.app_config = new_cfg
        if self.on_applied is not None:
            try:
                self.on_applied(new_cfg)
            except Exception as e:  # noqa: BLE001
                logger.error("Error in on_applied callback: %s", e)

        if context_menu_ok and autorun_ok:
            show_toast("ScanSort Settings", "Settings saved and applied successfully.")
        else:
            show_toast(
                "ScanSort Settings",
                "Settings saved, but some system integrations could not be updated.",
            )
        self.destroy()

    def _open_drop_zone(self) -> None:
        from scansort.ui.drop_zone import open_drop_zone_window

        open_drop_zone_window(master=self, config=self.app_config)
