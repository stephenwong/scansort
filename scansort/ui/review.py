"""Interactive review and self-learning modal dialog for ScanSort using Tkinter."""

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from scansort.classification.taxonomy import scan_documents_folders
from scansort.core.config import AppConfig, load_config
from scansort.core.fs import open_in_file_manager
from scansort.pipeline.review import (
    ReviewItem,
    dismiss_review_item,
    file_reviewed_item,
    get_review_queue,
)
from scansort.platform.toasts import show_toast

logger = logging.getLogger(__name__)

_ACTIVE_REVIEW_DIALOG: "ReviewDialog | None" = None
_DIALOG_LOCK = threading.Lock()


def open_review_dialog(
    config: AppConfig | None = None,
    on_filed: Callable[[Path], None] | None = None,
) -> "ReviewDialog":
    """Open or focus the singleton review dialog window.

    Thread-safe via ``_DIALOG_LOCK``; returns the existing open instance if one
    is already active, or instantiates a new one.
    """
    global _ACTIVE_REVIEW_DIALOG
    with _DIALOG_LOCK:
        if _ACTIVE_REVIEW_DIALOG is not None and _ACTIVE_REVIEW_DIALOG.winfo_exists():
            _ACTIVE_REVIEW_DIALOG.deiconify()
            _ACTIVE_REVIEW_DIALOG.lift()
            _ACTIVE_REVIEW_DIALOG.focus_force()
            return _ACTIVE_REVIEW_DIALOG

        dialog = ReviewDialog(config=config, on_filed=on_filed)
        _ACTIVE_REVIEW_DIALOG = dialog
        return dialog


class ReviewDialog(tk.Toplevel):
    """Tkinter modal window for reviewing and manually filing unfiled scans."""

    def __init__(
        self,
        master: tk.Misc | None = None,
        config: AppConfig | None = None,
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

        self.title("ScanSort — Review Unfiled Documents")
        self.resizable(True, True)
        self.minsize(640, 560)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.config: AppConfig = config or load_config()
        self.on_filed = on_filed

        self.queue: list[ReviewItem] = get_review_queue(
            self.config.documents_root, self.config.fallback_folder
        )
        self._current_index = 0

        self.header_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.diagnosis_var = tk.StringVar()
        self.reasoning_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.hint_var = tk.BooleanVar(value=True)
        self.hint_kw_var = tk.StringVar()
        self.preview_filename_var = tk.StringVar()

        self._build_ui()
        self._load_current_item()

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

    def destroy(self) -> None:
        """Clean up singleton reference and master root if owned."""
        global _ACTIVE_REVIEW_DIALOG
        with _DIALOG_LOCK:
            if _ACTIVE_REVIEW_DIALOG is self:
                _ACTIVE_REVIEW_DIALOG = None
        super().destroy()
        if self._owns_root:
            with contextlib.suppress(tk.TclError):
                self.master.destroy()

    def _build_ui(self) -> None:
        self.container = ttk.Frame(self, padding="14 14 14 14")
        self.container.pack(fill=tk.BOTH, expand=True)

        if not self.queue:
            empty_frame = ttk.Frame(self.container, padding="40 40 40 40")
            empty_frame.pack(fill=tk.BOTH, expand=True)
            ttk.Label(
                empty_frame,
                text="No documents currently require review.",
                font=("TkDefaultFont", 12, "bold"),
            ).pack(pady=(0, 10))
            ttk.Label(
                empty_frame,
                text=f"All scans in '{self.config.fallback_folder}' have been organized.",
            ).pack(pady=(0, 20))
            ttk.Button(empty_frame, text="Close", command=self.destroy).pack()
            return

        # Top Navigation Bar
        nav_frame = ttk.Frame(self.container)
        nav_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_prev = ttk.Button(
            nav_frame, text="◀ Previous", command=self._prev_item
        )
        self.btn_prev.pack(side=tk.LEFT)

        self.lbl_counter = ttk.Label(
            nav_frame,
            textvariable=self.header_var,
            font=("TkDefaultFont", 10, "bold"),
        )
        self.lbl_counter.pack(side=tk.LEFT, padx=10)

        self.btn_next = ttk.Button(nav_frame, text="Next ▶", command=self._next_item)
        self.btn_next.pack(side=tk.LEFT)

        btn_open = ttk.Button(
            nav_frame,
            text="Open in Viewer",
            command=self._open_in_viewer,
        )
        btn_open.pack(side=tk.RIGHT)

        # 1. AI Diagnosis Card
        diag_frame = ttk.LabelFrame(
            self.container, text="AI Diagnosis & Context", padding="10 10 10 10"
        )
        diag_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            diag_frame,
            textvariable=self.diagnosis_var,
            font=("TkDefaultFont", 9, "bold"),
            foreground="#B05000",
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(diag_frame, textvariable=self.summary_var, wraplength=580).pack(
            anchor=tk.W, pady=(0, 4)
        )

        reason_lbl = ttk.Label(
            diag_frame,
            textvariable=self.reasoning_var,
            font=("TkDefaultFont", 8, "italic"),
            wraplength=580,
        )
        reason_lbl.pack(anchor=tk.W, pady=(0, 6))

        self.sugg_btn = ttk.Button(
            diag_frame,
            text="Use Suggestion",
            command=self._use_suggestion,
        )
        self.sugg_btn.pack(anchor=tk.W)

        # 2. Destination & Naming Card
        file_frame = ttk.LabelFrame(
            self.container, text="Filing Destination & Naming", padding="10 10 10 10"
        )
        file_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(file_frame, text="Target Folder:").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        folders = scan_documents_folders(
            docs_root=self.config.documents_root,
            max_depth=self.config.max_folder_depth,
            fallback_folder=self.config.fallback_folder,
        )
        self.folder_combo = ttk.Combobox(
            file_frame,
            textvariable=self.folder_var,
            values=sorted(folders),
        )
        self.folder_combo.grid(row=0, column=1, sticky=tk.EW, padx=(6, 0), pady=2)

        ttk.Label(file_frame, text="Document Date (YYMMDD):").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        date_entry = ttk.Entry(file_frame, textvariable=self.date_var)
        date_entry.grid(row=1, column=1, sticky=tk.EW, padx=(6, 0), pady=2)

        ttk.Label(file_frame, text="Description:").grid(
            row=2, column=0, sticky=tk.W, pady=2
        )
        desc_entry = ttk.Entry(file_frame, textvariable=self.desc_var)
        desc_entry.grid(row=2, column=1, sticky=tk.EW, padx=(6, 0), pady=2)

        file_frame.columnconfigure(1, weight=1)

        # 3. Self-Learning Keyword Hints Card
        hint_frame = ttk.LabelFrame(
            self.container, text="Self-Learning Keyword Rules", padding="10 10 10 10"
        )
        hint_frame.pack(fill=tk.X, pady=(0, 10))

        chk_hint = ttk.Checkbutton(
            hint_frame,
            text="Remember keyword hint for future scans to this folder:",
            variable=self.hint_var,
        )
        chk_hint.pack(anchor=tk.W, pady=(0, 4))

        self.hint_entry = ttk.Entry(hint_frame, textvariable=self.hint_kw_var)
        self.hint_entry.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(
            hint_frame,
            text="Future scans matching this keyword will be filed automatically with high confidence.",
            font=("TkDefaultFont", 8, "italic"),
        ).pack(anchor=tk.W)

        # Action Buttons Footer
        act_frame = ttk.Frame(self.container)
        act_frame.pack(fill=tk.X, pady=(6, 0))

        btn_dismiss = ttk.Button(
            act_frame,
            text="Dismiss / Delete",
            command=self._dismiss_current_item,
        )
        btn_dismiss.pack(side=tk.LEFT)

        btn_skip = ttk.Button(act_frame, text="Skip for Now", command=self._next_item)
        btn_skip.pack(side=tk.LEFT, padx=6)

        btn_file = ttk.Button(
            act_frame,
            text="File Document",
            command=self._file_current_item,
        )
        btn_file.pack(side=tk.RIGHT)

    def _load_current_item(self) -> None:
        """Update form fields to match current queue item."""
        if not self.queue:
            if hasattr(self, "container"):
                self.container.destroy()
            self._build_ui()
            return

        item = self.queue[self._current_index]
        self.header_var.set(
            f"Item {self._current_index + 1} of {len(self.queue)}: {item.filename}"
        )
        self.btn_prev.config(
            state=tk.NORMAL if self._current_index > 0 else tk.DISABLED
        )
        self.btn_next.config(
            state=tk.NORMAL
            if self._current_index < len(self.queue) - 1
            else tk.DISABLED
        )

        conf_pct = f"{int(item.confidence * 100)}%" if item.confidence else "Uncertain"
        self.diagnosis_var.set(f"Type: {item.document_type} | Confidence: {conf_pct}")
        self.summary_var.set(f"Summary: {item.summary or 'No summary available.'}")
        self.reasoning_var.set(
            f"Reasoning: {item.folder_reasoning or item.routing_rationale or 'No reasoning recorded.'}"
        )

        if item.suggested_folder:
            self.sugg_btn.config(
                text=f"Use AI Suggestion: {item.suggested_folder}",
                state=tk.NORMAL,
            )
            self.folder_var.set(item.suggested_folder)
        else:
            self.sugg_btn.config(text="No AI Suggestion", state=tk.DISABLED)
            self.folder_var.set("")

        self.date_var.set(item.document_date)
        self.desc_var.set(item.description)

        default_kw = item.description.replace("_", " ").lower()
        self.hint_kw_var.set(default_kw)
        self.hint_var.set(True)

    def _use_suggestion(self) -> None:
        if not self.queue:
            return
        item = self.queue[self._current_index]
        if item.suggested_folder:
            self.folder_var.set(item.suggested_folder)

    def _prev_item(self) -> None:
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current_item()

    def _next_item(self) -> None:
        if self._current_index < len(self.queue) - 1:
            self._current_index += 1
            self._load_current_item()

    def _open_in_viewer(self) -> None:
        if not self.queue:
            return
        item = self.queue[self._current_index]
        open_in_file_manager(item.file_path)

    def _file_current_item(self) -> None:
        if not self.queue:
            return
        item = self.queue[self._current_index]
        target_folder = self.folder_var.get().strip()
        if not target_folder:
            messagebox.showwarning(
                "Missing Folder",
                "Please select or specify a destination folder.",
                parent=self,
            )
            return

        date_val = self.date_var.get().strip()
        desc_val = self.desc_var.get().strip()
        hint_kw = self.hint_kw_var.get().strip() if self.hint_var.get() else None

        try:
            dest = file_reviewed_item(
                item=item,
                target_folder=target_folder,
                document_date=date_val,
                description=desc_val,
                config=self.config,
                keyword_hint=hint_kw,
            )
            show_toast("ScanSort", f"Filed '{dest.name}' into '{target_folder}'.")
            if self.on_filed:
                try:
                    self.on_filed(dest)
                except Exception as e:
                    logger.exception("Error in on_filed callback for '%s': %s", dest, e)

            # Remove filed item and advance
            self.queue.pop(self._current_index)
            if self._current_index >= len(self.queue) and self._current_index > 0:
                self._current_index -= 1
            self._load_current_item()

        except (OSError, ValueError) as e:
            messagebox.showerror(
                "Filing Error",
                f"Could not file document: {e}",
                parent=self,
            )

    def _dismiss_current_item(self, confirm: bool = True) -> None:
        if not self.queue:
            return
        item = self.queue[self._current_index]
        if confirm and not messagebox.askyesno(
            "Confirm Dismissal",
            f"Are you sure you want to permanently delete {item.filename}?",
            parent=self,
        ):
            return

        try:
            dismiss_review_item(item)
            self.queue.pop(self._current_index)
            if self._current_index >= len(self.queue) and self._current_index > 0:
                self._current_index -= 1
            self._load_current_item()
        except OSError as e:
            messagebox.showerror(
                "Dismiss Error",
                f"Could not dismiss document: {e}",
                parent=self,
            )
