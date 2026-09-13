"""Filing-memory inspection dialog for ScanSort using Tkinter."""

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from scansort.core.config import AppConfig, get_default_app_dir, load_config
from scansort.ui.singleton_window import SingletonToplevel

logger = logging.getLogger(__name__)

_ACTIVE_MEMORY_DIALOG: "MemoryDialog | None" = None
_MEMORY_LOCK = threading.Lock()


def open_memory_dialog(
    config: AppConfig | None = None,
    on_changed: Callable[[], None] | None = None,
) -> "MemoryDialog":
    """Open or focus the singleton filing-memory dialog."""
    existing = MemoryDialog.focus_existing()
    if existing is not None:
        return existing
    dialog = MemoryDialog(config=config, on_changed=on_changed)
    return MemoryDialog.register_or_existing(dialog)


class MemoryDialog(SingletonToplevel):
    """Tkinter window listing learned filing examples with forget/clear/rebuild."""

    @classmethod
    def _instance(cls) -> "MemoryDialog | None":
        return _ACTIVE_MEMORY_DIALOG

    @classmethod
    def _set_instance(cls, value: "MemoryDialog | None") -> None:
        global _ACTIVE_MEMORY_DIALOG
        _ACTIVE_MEMORY_DIALOG = value

    @classmethod
    def _lock(cls) -> threading.Lock:
        return _MEMORY_LOCK

    def __init__(
        self,
        master: tk.Misc | None = None,
        config: AppConfig | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("ScanSort — Filing Memory")
        self.resizable(True, True)
        self.minsize(640, 400)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        try:
            self.app_config: AppConfig = config or load_config()
        except ValueError:
            self.app_config = AppConfig()
        self.on_changed = on_changed
        self._rows: list[dict] = []
        self._build_ui()
        self.refresh_examples()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding="14 14 14 14")
        container.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        scroll = ttk.Scrollbar(tree_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("folder", "summary", "learned", "status"),
            show="headings",
            yscrollcommand=scroll.set,
            selectmode="browse",
        )
        self.tree.heading("folder", text="Folder", anchor=tk.W)
        self.tree.heading("summary", text="Summary", anchor=tk.W)
        self.tree.heading("learned", text="Learned", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.W)
        self.tree.column("folder", width=180)
        self.tree.column("summary", width=260)
        self.tree.column("learned", width=120, stretch=False)
        self.tree.column("status", width=90, stretch=False)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.tree.yview)

        bar = ttk.Frame(container)
        bar.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(bar, text="Forget Selected", command=self.forget_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(bar, text="Clear All...", command=self.clear_all).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(
            bar, text="Rebuild from History", command=self.rebuild_from_history
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _notify_changed(self) -> None:
        if self.on_changed is not None:
            try:
                self.on_changed()
            except Exception as e:  # noqa: BLE001 - callback must not break dialog
                logger.exception("Error in on_changed callback: %s", e)

    def refresh_examples(self) -> None:
        """Reload learned examples into the treeview best-effort."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows = []
        try:
            from scansort.classification.memory import (
                MemoryStore,
                memory_db_path_for,
            )

            store = MemoryStore(memory_db_path_for(get_default_app_dir()))
            rows = store.list_examples(limit=200)
        except Exception as e:  # noqa: BLE001 - dialog must never crash
            logger.warning("Could not load filing memory: %s", e)
            return
        self._rows = rows
        for index, row in enumerate(rows):
            learned = str(row.get("timestamp", ""))[:16].replace("T", " ")
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    row.get("folder", ""),
                    row.get("summary", ""),
                    learned,
                    row.get("status", ""),
                ),
            )

    def _selected_folder(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return str(self._rows[int(selection[0])].get("folder", "") or "") or None
        except IndexError, ValueError:
            return None

    def forget_selected(self) -> None:
        """Forget learned examples for the selected folder."""
        folder = self._selected_folder()
        if not folder:
            messagebox.showinfo(
                "Filing Memory", "Select a learned example to forget.", parent=self
            )
            return
        try:
            from scansort.classification.memory import (
                MemoryStore,
                memory_db_path_for,
            )

            removed = MemoryStore(
                memory_db_path_for(get_default_app_dir())
            ).forget_folder(folder)
        except Exception as e:  # noqa: BLE001 - best-effort with user feedback
            messagebox.showerror(
                "Filing Memory", f"Could not forget folder: {e}", parent=self
            )
            return
        if removed == 0:
            messagebox.showinfo(
                "Filing Memory",
                f"No learned examples found for '{folder}'.",
                parent=self,
            )
        self.refresh_examples()
        self._notify_changed()

    def clear_all(self) -> None:
        """Clear all learned examples after an honest confirm."""
        if not messagebox.askyesno(
            "Clear Filing Memory",
            "Forget all learned examples? ScanSort will re-learn from your "
            "filing history on the next scan unless memory is turned off.",
            parent=self,
        ):
            return
        try:
            from scansort.classification.memory import (
                MemoryStore,
                memory_db_path_for,
            )

            removed = MemoryStore(memory_db_path_for(get_default_app_dir())).clear()
        except Exception as e:  # noqa: BLE001 - best-effort with user feedback
            messagebox.showerror(
                "Filing Memory", f"Could not clear memory: {e}", parent=self
            )
            return
        if not removed:
            messagebox.showinfo("Filing Memory", "Nothing to clear.", parent=self)
        self.refresh_examples()
        self._notify_changed()

    def rebuild_from_history(self) -> None:
        """Rebuild filing memory from history and refresh the view."""
        try:
            from scansort.classification.memory import (
                memory_db_path_for,
                memory_lock_path_for,
                rebuild_memory,
            )
            from scansort.core.constants import HISTORY_JSONL_NAME

            app_dir = get_default_app_dir()
            learned = rebuild_memory(
                memory_db_path_for(app_dir),
                app_dir / HISTORY_JSONL_NAME,
                memory_lock_path_for(app_dir),
            )
        except Exception as e:  # noqa: BLE001 - best-effort with user feedback
            messagebox.showerror(
                "Filing Memory", f"Could not rebuild memory: {e}", parent=self
            )
            return
        if learned == 0:
            messagebox.showinfo(
                "Filing Memory",
                "No filing history to learn from yet.",
                parent=self,
            )
        self.refresh_examples()
        self._notify_changed()
