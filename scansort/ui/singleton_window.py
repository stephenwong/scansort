"""Shared lifecycle for singleton Tk top-level dialogs."""

import contextlib
import threading
import tkinter as tk


class SingletonToplevel(tk.Toplevel):
    """Tk top-level that owns (or attaches to) a root and guards its mainloop.

    Subclasses provide the registry accessor hooks so each module's existing
    singleton globals and lock remain the single source of truth (and the test
    seam). The base class centralizes root ownership, the redundant-mainloop
    guard, deregistration, and owned-root teardown.
    """

    def __init__(self, master: tk.Misc | None = None) -> None:
        self._owns_root = False
        self._mainloop_running = False
        if master is None:
            root = tk.Tk()
            root.withdraw()
            super().__init__(root)
            self._owns_root = True
        else:
            super().__init__(master)

    @classmethod
    def _instance(cls) -> "SingletonToplevel | None":
        raise NotImplementedError

    @classmethod
    def _set_instance(cls, value: "SingletonToplevel | None") -> None:
        raise NotImplementedError

    @classmethod
    def _lock(cls) -> threading.Lock:
        raise NotImplementedError

    @classmethod
    def focus_existing(cls) -> "SingletonToplevel | None":
        """Focus and return the live registered instance, or None if absent/dead."""
        with cls._lock():
            existing = cls._instance()
            if existing is None:
                return None
            with contextlib.suppress(tk.TclError):
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return existing
            return None

    @classmethod
    def register_or_existing(cls, dialog: "SingletonToplevel") -> "SingletonToplevel":
        """Register *dialog*, or discard it in favour of a racing live instance."""
        winner: SingletonToplevel | None = None
        with cls._lock():
            existing = cls._instance()
            if existing is not None:
                with contextlib.suppress(tk.TclError):
                    if existing.winfo_exists():
                        winner = existing
            if winner is None:
                cls._set_instance(dialog)

        if winner is None:
            return dialog
        # Discard the loser outside the lock: destroy() re-acquires it.
        with contextlib.suppress(tk.TclError):
            dialog.destroy()
        with contextlib.suppress(tk.TclError):
            winner.deiconify()
            winner.lift()
            winner.focus_force()
        return winner

    def mainloop(self, n: int = 0) -> None:
        """Run Tkinter mainloop safely, ignoring redundant concurrent calls."""
        lock = self._lock()
        with lock:
            if self._mainloop_running:
                return
            self._mainloop_running = True
        try:
            super().mainloop(n)
        finally:
            with lock:
                self._mainloop_running = False

    def destroy(self) -> None:
        """Destroy the window, deregister it, and tear down an owned root."""
        with self._lock():
            if self._instance() is self:
                self._set_instance(None)
        with contextlib.suppress(tk.TclError):
            super().destroy()
        if self._owns_root and self.master:
            with contextlib.suppress(tk.TclError):
                self.master.destroy()
