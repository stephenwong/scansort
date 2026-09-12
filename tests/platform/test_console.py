"""Unit tests for scansort.platform.console module."""

import io
import os
import sys
from unittest.mock import MagicMock, call

from scansort.platform.console import (
    ATTACH_PARENT_PROCESS,
    STD_ERROR_HANDLE,
    STD_OUTPUT_HANDLE,
    attach_parent_console,
)


def _fake_console_api(
    monkeypatch,
    attach_result=1,
    output_cp=437,
    stdout_handle=11,
    stderr_handle=12,
):
    """Fake a frozen windowed Windows build running under a parent console."""
    import scansort.platform.console as console_module

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    fake_ctypes = MagicMock()
    kernel32 = fake_ctypes.WinDLL.return_value
    kernel32.AttachConsole.return_value = attach_result
    kernel32.GetConsoleOutputCP.return_value = output_cp
    kernel32.GetStdHandle.side_effect = [stdout_handle, stderr_handle]
    monkeypatch.setattr(console_module, "ctypes", fake_ctypes)

    fake_msvcrt = MagicMock()
    fake_msvcrt.open_osfhandle.side_effect = [100, 101]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    opened = []

    def fake_fdopen(fd, mode, **kwargs):
        opened.append((fd, mode, kwargs))
        return io.StringIO()

    monkeypatch.setattr(console_module.os, "fdopen", fake_fdopen)
    return kernel32, fake_msvcrt, opened, attach_parent_console


def test_attach_parent_console_noop_off_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    real_out = sys.stdout
    attach_parent_console()
    assert sys.stdout is real_out


def test_attach_parent_console_noop_when_not_frozen(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    real_out = sys.stdout
    attach_parent_console()
    assert sys.stdout is real_out


def test_attach_parent_console_skips_when_stdout_is_terminal(monkeypatch):
    import scansort.platform.console as console_module

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    tty_out = MagicMock()
    tty_out.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", tty_out)
    fake_ctypes = MagicMock()
    monkeypatch.setattr(console_module, "ctypes", fake_ctypes)

    attach_parent_console()
    fake_ctypes.WinDLL.assert_not_called()
    assert sys.stdout is tty_out


def test_attach_parent_console_silent_without_parent_console(monkeypatch):
    kernel32, fake_msvcrt, opened, attach = _fake_console_api(
        monkeypatch, attach_result=0
    )
    real_out = sys.stdout

    assert attach() is None
    kernel32.AttachConsole.assert_called_once_with(ATTACH_PARENT_PROCESS)
    kernel32.GetStdHandle.assert_not_called()
    fake_msvcrt.open_osfhandle.assert_not_called()
    assert opened == []
    assert sys.stdout is real_out


def test_attach_parent_console_binds_stdout_and_stderr(monkeypatch):
    kernel32, fake_msvcrt, opened, attach = _fake_console_api(monkeypatch)
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    kernel32.AttachConsole.assert_called_once_with(ATTACH_PARENT_PROCESS)
    kernel32.GetConsoleOutputCP.assert_called_once_with()
    assert kernel32.GetStdHandle.call_args_list == [
        call(STD_OUTPUT_HANDLE),
        call(STD_ERROR_HANDLE),
    ]
    assert fake_msvcrt.open_osfhandle.call_args_list == [
        call(11, os.O_WRONLY),
        call(12, os.O_WRONLY),
    ]
    assert opened == [
        (100, "w", {"encoding": "cp437", "buffering": 1}),
        (101, "w", {"encoding": "cp437", "buffering": 1}),
    ]
    assert sys.stdout is not original_out
    assert sys.stderr is not original_err


def test_attach_parent_console_skips_missing_stdout_handle(monkeypatch):
    _, fake_msvcrt, opened, attach = _fake_console_api(monkeypatch, stdout_handle=0)
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    assert fake_msvcrt.open_osfhandle.call_args_list == [call(12, os.O_WRONLY)]
    assert opened == [(100, "w", {"encoding": "cp437", "buffering": 1})]
    assert sys.stdout is original_out
    assert sys.stderr is not original_err


def test_attach_parent_console_falls_back_to_utf8_without_codepage(monkeypatch):
    _, _, opened, attach = _fake_console_api(monkeypatch, output_cp=0)

    assert attach() is None
    assert opened == [
        (100, "w", {"encoding": "utf-8", "buffering": 1}),
        (101, "w", {"encoding": "utf-8", "buffering": 1}),
    ]


def test_attach_parent_console_swallows_win32_api_failures(monkeypatch):
    import scansort.platform.console as console_module

    _, _, _, attach = _fake_console_api(monkeypatch)
    console_module.ctypes.WinDLL.side_effect = OSError(5, "access denied")
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    assert sys.stdout is original_out
    assert sys.stderr is original_err


def test_attach_parent_console_swallows_closed_stdout(monkeypatch):
    import io
    import sys as _sys

    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "platform", "win32")
    monkeypatch.setattr(_sys, "stdout", closed)

    from scansort.platform.console import attach_parent_console

    attach_parent_console()  # must not raise


def test_attach_parent_console_closes_fd_when_fdopen_fails(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "platform", "win32")
    monkeypatch.setattr(_sys, "stdout", None)

    opened = []

    class _FakeMsvcrt:
        @staticmethod
        def open_osfhandle(handle, flags):
            opened.append(handle)
            return 42

    fake_kernel32 = MagicMock()
    fake_kernel32.AttachConsole.return_value = 1
    fake_kernel32.GetConsoleOutputCP.return_value = 65001
    fake_kernel32.GetStdHandle.return_value = 12
    fake_win = MagicMock(return_value=fake_kernel32)

    closed = []
    monkeypatch.setattr("ctypes.WinDLL", fake_win, raising=False)
    monkeypatch.setattr("os.fdopen", MagicMock(side_effect=ValueError("bad codec")))
    monkeypatch.setattr("os.close", lambda fd: closed.append(fd))
    monkeypatch.setitem(_sys.modules, "msvcrt", _FakeMsvcrt)

    from scansort.platform.console import attach_parent_console

    attach_parent_console()
    assert closed == [42, 42]
