"""Settings modal dialog for ScanSort using Tkinter."""

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from scansort.classification.doctor import (
    ACTION_NONE,
    DoctorFinding,
    apply_doctor_action,
    run_doctor,
)
from scansort.classification.taxonomy import build_taxonomy_tree, scan_documents_folders
from scansort.core.config import (
    AppConfig,
    get_default_app_dir,
    load_config,
    save_config,
)
from scansort.core.constants import OPERATIONS_LOCK_FILENAME, SUPPORTED_GEMINI_MODELS
from scansort.core.fs import interprocess_file_lock
from scansort.platform.autorun import (
    disable_autorun,
    enable_autorun,
    is_autorun_enabled,
)
from scansort.platform.context_menu import (
    disable_context_menu,
    disable_ocr_menu,
    enable_context_menu,
    enable_ocr_menu,
    is_context_menu_enabled,
    is_ocr_menu_enabled,
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

#: Fields the Settings dialog owns; everything else is merged from disk on save
#: so a concurrent CLI mutation is not clobbered by the dialog's stale snapshot.
_DIALOG_MANAGED_FIELDS: tuple[str, ...] = (
    "watch_folder",
    "documents_root",
    "gemini_model",
    "fallback_folder",
    "dry_run",
    "start_on_boot",
    "ocr_enabled",
    "rag_memory_enabled",
)


def open_settings_dialog(
    config: AppConfig | None = None,
    on_applied: Callable[[AppConfig], None] | None = None,
    doctor: bool = False,
) -> "SettingsDialog":
    """Open or focus the singleton settings dialog window.

    Thread-safe via ``_DIALOG_LOCK``; returns the existing open instance if one
    is already active, or instantiates a new one. When ``doctor`` is True, the
    Taxonomy Doctor analysis runs as soon as the dialog is built.
    """
    existing = SettingsDialog.focus_existing()
    if existing is not None:
        if doctor:
            # Marshal onto the dialog's Tk thread; the tray calls this from a
            # worker thread, so a direct widget call would be unsafe.
            with contextlib.suppress(tk.TclError, RuntimeError):
                existing.after(0, existing.run_taxonomy_doctor)
        return existing

    # Construct outside the lock: __init__ performs keyring/registry I/O and a
    # recursive taxonomy scan, which must not block other tray interactions.
    dialog = SettingsDialog(config=config, on_applied=on_applied, doctor=doctor)
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
        doctor: bool = False,
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
        self.ocr_var = tk.BooleanVar(value=self.app_config.ocr_enabled)
        self.ocr_menu_var = tk.BooleanVar(value=is_ocr_menu_enabled())
        self.rag_memory_var = tk.BooleanVar(value=self.app_config.rag_memory_enabled)
        self._doctor_findings: list[DoctorFinding] = []
        self._doctor_root: Path | None = None
        self._dismissed_finding_ids: set[str] = set()

        self._build_ui()
        self.refresh_taxonomy_tree()
        if doctor:
            self.run_taxonomy_doctor()

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

        # 2b. Taxonomy Doctor (folder-health findings)
        doctor_frame = ttk.LabelFrame(
            container, text="Taxonomy Doctor Findings", padding="10 10 10 10"
        )
        doctor_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        doctor_scroll = ttk.Scrollbar(doctor_frame)
        doctor_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.doctor_tree = ttk.Treeview(
            doctor_frame,
            columns=("severity", "finding"),
            show="headings",
            yscrollcommand=doctor_scroll.set,
            selectmode="browse",
        )
        self.doctor_tree.heading("severity", text="Severity", anchor=tk.W)
        self.doctor_tree.heading("finding", text="Finding", anchor=tk.W)
        self.doctor_tree.column("severity", width=80, stretch=False)
        self.doctor_tree.column("finding", width=420)
        self.doctor_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        doctor_scroll.config(command=self.doctor_tree.yview)

        doctor_bar = ttk.Frame(doctor_frame)
        doctor_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        ttk.Button(
            doctor_bar, text="Run Taxonomy Doctor", command=self.run_taxonomy_doctor
        ).pack(side=tk.LEFT)
        ttk.Button(
            doctor_bar,
            text="Approve",
            command=self.approve_selected_doctor_finding,
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            doctor_bar,
            text="Dismiss",
            command=self.dismiss_selected_doctor_finding,
        ).pack(side=tk.RIGHT)

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
            text="Embed searchable OCR text layer in new scans (requires Tesseract)",
            variable=self.ocr_var,
        ).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(
            opts_frame,
            text="Enable 'Make searchable with ScanSort' for PDFs in Explorer",
            variable=self.ocr_menu_var,
        ).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(
            opts_frame,
            text="Use past filings as classification examples (local filing memory)",
            variable=self.rag_memory_var,
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

    def run_taxonomy_doctor(self) -> None:
        """Analyze the current documents tree and populate the findings list."""
        docs_raw = self.docs_var.get().strip()
        docs_path = Path(docs_raw) if docs_raw else None
        if docs_path is None or not docs_path.is_dir():
            self._doctor_findings = []
            self._doctor_root = None
            self._populate_doctor_tree()
            if docs_path is None:
                messagebox.showerror(
                    "Taxonomy Doctor",
                    "Documents Destination Root cannot be empty.",
                    parent=self,
                )
            return

        # Pin the analyzed root so an Approve can never act on a root different
        # from the one the findings were computed against.
        self._doctor_root = docs_path.resolve()
        temp_cfg = self._doctor_config(self._doctor_root)
        try:
            report = run_doctor(temp_cfg)
        except (OSError, ValueError) as e:
            logger.warning("Taxonomy Doctor analysis failed: %s", e)
            self._doctor_findings = []
            self._populate_doctor_tree()
            messagebox.showerror("Taxonomy Doctor", str(e), parent=self)
            return
        self._doctor_findings = [
            finding
            for finding in report.findings
            if finding.finding_id not in self._dismissed_finding_ids
        ]
        self._populate_doctor_tree()

    def _doctor_config(self, docs_root: Path) -> AppConfig:
        """Build a config snapshot rooted at *docs_root* for doctor operations."""
        return self.app_config.model_copy(
            update={
                "documents_root": docs_root,
                "fallback_folder": self.fallback_var.get().strip()
                or self.app_config.fallback_folder,
            }
        )

    def _populate_doctor_tree(self) -> None:
        """Render the current findings into the doctor treeview."""
        for item in self.doctor_tree.get_children():
            self.doctor_tree.delete(item)
        for index, finding in enumerate(self._doctor_findings):
            suffix = "" if finding.action == ACTION_NONE else "  [actionable]"
            self.doctor_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(finding.severity, f"{finding.message}{suffix}"),
            )

    def _selected_doctor_finding(self) -> DoctorFinding | None:
        """Return the selected finding, or None when nothing is selected."""
        selection = self.doctor_tree.selection()
        if not selection:
            return None
        try:
            return self._doctor_findings[int(selection[0])]
        except IndexError, ValueError:
            return None

    def approve_selected_doctor_finding(self) -> None:
        """Apply the selected finding's action after re-validating containment."""
        finding = self._selected_doctor_finding()
        if finding is None:
            messagebox.showinfo(
                "Taxonomy Doctor",
                "Select a finding to approve.",
                parent=self,
            )
            return
        if self._doctor_root is None:
            messagebox.showerror(
                "Taxonomy Doctor",
                "Run the Taxonomy Doctor analysis before approving a finding.",
                parent=self,
            )
            return
        temp_cfg = self._doctor_config(self._doctor_root)
        try:
            message = apply_doctor_action(finding, temp_cfg)
        except (OSError, ValueError) as e:
            messagebox.showerror("Taxonomy Doctor", str(e), parent=self)
            return
        show_toast("ScanSort Taxonomy Doctor", message)
        self.refresh_taxonomy_tree()
        self.run_taxonomy_doctor()

    def dismiss_selected_doctor_finding(self) -> None:
        """Hide the selected finding for this session without changing files."""
        finding = self._selected_doctor_finding()
        if finding is None:
            messagebox.showinfo(
                "Taxonomy Doctor",
                "Select a finding to dismiss.",
                parent=self,
            )
            return
        self._dismissed_finding_ids.add(finding.finding_id)
        self._doctor_findings = [
            f for f in self._doctor_findings if f.finding_id != finding.finding_id
        ]
        self._populate_doctor_tree()

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
            updated_dict["ocr_enabled"] = self.ocr_var.get()
            updated_dict["rag_memory_enabled"] = self.rag_memory_var.get()
            new_cfg = AppConfig(**updated_dict)
            new_cfg.ensure_directories()
        except (ValueError, OSError) as e:
            messagebox.showerror("Configuration Error", str(e), parent=self)
            return None
        return new_cfg

    def _persist_config_with_key_rollback(
        self, new_cfg: AppConfig, new_key: str, prior_key: str | None
    ) -> AppConfig | None:
        """Persist *new_cfg*, rolling back the saved credential on failure.

        Reloads the on-disk config inside the lock and overlays only the fields
        this dialog manages, so a concurrent CLI mutation to any other field is
        not silently reverted by the dialog's stale snapshot. Returns the
        reconciled config (or None on failure).
        """
        try:
            op_lock = get_default_app_dir() / OPERATIONS_LOCK_FILENAME
            with interprocess_file_lock(op_lock):
                try:
                    disk_cfg = load_config()
                except ValueError:
                    disk_cfg = new_cfg
                merged = disk_cfg.model_dump()
                for field in _DIALOG_MANAGED_FIELDS:
                    merged[field] = getattr(new_cfg, field)
                reconciled = AppConfig(**merged)
                save_config(reconciled)
            return reconciled
        except (OSError, ValueError) as e:
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
            return None

    def _apply_system_integrations(self, new_cfg: AppConfig) -> tuple[bool, bool, bool]:
        """Reconcile OS state; returns (autorun_ok, menu_ok, ocr_menu_ok)."""
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
                try:
                    save_config(new_cfg)
                except OSError as e:
                    # F32: never silently diverge config.json from OS state.
                    logger.warning(
                        "Could not persist reconciled start_on_boot setting: %s", e
                    )

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

        ocr_menu_ok = True
        try:
            desired_ocr_menu = self.ocr_menu_var.get()
            if desired_ocr_menu != is_ocr_menu_enabled():
                if desired_ocr_menu:
                    ocr_menu_ok = enable_ocr_menu()
                else:
                    ocr_menu_ok = disable_ocr_menu()
            if not ocr_menu_ok:
                logger.warning("Could not update OCR context menu setting.")
        except OSError as e:
            logger.warning("Could not update OCR context menu setting: %s", e)
            ocr_menu_ok = False
        return autorun_ok, context_menu_ok, ocr_menu_ok

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

        saved_cfg = self._persist_config_with_key_rollback(new_cfg, new_key, prior_key)
        if saved_cfg is None:
            return
        new_cfg = saved_cfg

        autorun_ok, context_menu_ok, ocr_menu_ok = self._apply_system_integrations(
            new_cfg
        )

        self.app_config = new_cfg
        if self.on_applied is not None:
            try:
                self.on_applied(new_cfg)
            except Exception as e:  # noqa: BLE001
                logger.error("Error in on_applied callback: %s", e)

        if context_menu_ok and autorun_ok and ocr_menu_ok:
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
