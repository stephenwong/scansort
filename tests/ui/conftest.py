"""Shared fixtures for UI tests.

Tkinter dialogs are process-modal: a single unmocked ``messagebox`` or
``filedialog`` call blocks the test run until a human clicks it. This autouse
fixture replaces every blocking dialog entry point with a non-interactive
default so tests can run unattended; individual tests may still override a
specific function with ``patch`` to assert behaviour.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_blocking_tk_dialogs():
    """Neutralize messagebox/filedialog so no UI test can require a click."""
    with (
        patch("tkinter.messagebox.showinfo", return_value=None),
        patch("tkinter.messagebox.showwarning", return_value=None),
        patch("tkinter.messagebox.showerror", return_value=None),
        patch("tkinter.messagebox.askyesno", return_value=False),
        patch("tkinter.messagebox.askokcancel", return_value=False),
        patch("tkinter.messagebox.askquestion", return_value="no"),
        patch("tkinter.messagebox.askretrycancel", return_value=False),
        patch("tkinter.messagebox.askyesnocancel", return_value=None),
        patch("tkinter.filedialog.askopenfilename", return_value=""),
        patch("tkinter.filedialog.askopenfilenames", return_value=()),
        patch("tkinter.filedialog.askdirectory", return_value=""),
        patch("tkinter.filedialog.asksaveasfilename", return_value=""),
    ):
        yield
