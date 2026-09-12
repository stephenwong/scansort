"""Windows Explorer and Linux file manager context menu integration."""

import logging
import os
import sys
from pathlib import Path

from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.platform._commands import build_executable_invocation
from scansort.platform._linux import (
    remove_xdg_file,
    write_xdg_file,
    xdg_file_has_markers,
)
from scansort.platform._winreg_seam import load_winreg

logger = logging.getLogger(__name__)

VERB_NAME = "ScanSort"
VERB_LABEL = "File with ScanSort"
OCR_VERB_NAME = "ScanSortOCR"
OCR_VERB_LABEL = "Make searchable with ScanSort"
OCR_EXTENSIONS: tuple[str, ...] = (".pdf",)
WIN_BASE_SUBKEY = r"Software\Classes\SystemFileAssociations"

_DELETE_ACCESS = 0x00010000

_winreg = None


def _get_winreg():
    """Retrieve the winreg module or test mock seam."""
    return load_winreg(_winreg)


def _build_context_menu_command(executable_path: str | None = None) -> str:
    """Format the full command line invocation for context menu filing."""
    return build_executable_invocation(executable_path, 'file "%1"')


def _build_ocr_menu_command(executable_path: str | None = None) -> str:
    """Format the full command line invocation for context menu OCR backfill."""
    return build_executable_invocation(executable_path, 'ocr-backfill "%1"')


def _delete_subkey_if_exists(reg, parent_path: str, key_name: str) -> None:
    """Delete *key_name* under *parent_path*, ignoring a missing key.

    RegDeleteKey requires the parent handle to carry the DELETE access right,
    which KEY_SET_VALUE does not grant, so both bits are requested.
    """
    try:
        with reg.OpenKey(
            reg.HKEY_CURRENT_USER, parent_path, 0, reg.KEY_SET_VALUE | _DELETE_ACCESS
        ) as key:
            reg.DeleteKey(key, key_name)
    except FileNotFoundError:
        pass


def _is_win_verb_enabled(verb_name: str, extensions: tuple[str, ...]) -> bool:
    """Return True when every *extensions* entry has a non-empty verb command."""
    try:
        reg = _get_winreg()
        for ext in sorted(extensions):
            check_key = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{verb_name}\\command"
            with reg.OpenKey(reg.HKEY_CURRENT_USER, check_key, 0, reg.KEY_READ) as key:
                val, _ = reg.QueryValueEx(key, "")
                if not str(val).strip():
                    return False
        return True
    except OSError, ImportError:
        return False


def _enable_win_verb(
    verb_name: str,
    label: str,
    command: str,
    icon_path: str,
    extensions: tuple[str, ...],
) -> bool:
    """Register a Windows Explorer verb for every extension, isolating failures."""
    try:
        reg = _get_winreg()
        ok = True
        for ext in sorted(extensions):
            verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{verb_name}"
            cmd_path = f"{verb_path}\\command"
            try:
                with reg.CreateKey(reg.HKEY_CURRENT_USER, verb_path) as verb_key:
                    reg.SetValueEx(verb_key, "", 0, reg.REG_SZ, label)
                    if icon_path:
                        reg.SetValueEx(verb_key, "Icon", 0, reg.REG_SZ, icon_path)

                with reg.CreateKey(reg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
                    reg.SetValueEx(cmd_key, "", 0, reg.REG_SZ, command)
            except OSError as e:
                logger.warning("Failed to register context menu for %s: %s", ext, e)
                ok = False
        return ok
    except (OSError, ImportError) as e:
        logger.warning("Failed to enable Windows context menu: %s", e)
        return False


def _disable_win_verb(verb_name: str, extensions: tuple[str, ...]) -> bool:
    """Remove a Windows Explorer verb for every extension, isolating failures."""
    try:
        reg = _get_winreg()
        ok = True
        for ext in sorted(extensions):
            verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{verb_name}"
            parent_shell = f"{WIN_BASE_SUBKEY}\\{ext}\\shell"
            try:
                _delete_subkey_if_exists(reg, verb_path, "command")
                _delete_subkey_if_exists(reg, parent_shell, verb_name)
            except OSError as e:
                logger.warning("Failed to remove context menu for %s: %s", ext, e)
                ok = False
        return ok
    except (OSError, ImportError) as e:
        logger.warning("Failed to remove Windows context menu: %s", e)
        return False


def _linux_script_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "nautilus" / "scripts"


def _get_linux_nautilus_script_path() -> Path:
    return _linux_script_dir() / "File with ScanSort"


def _get_linux_ocr_nautilus_script_path() -> Path:
    return _linux_script_dir() / "Make searchable with ScanSort"


def _enable_linux_script(script_file: Path, content: str) -> bool:
    if not write_xdg_file(
        script_file, content, description="Nautilus script", executable=True
    ):
        return False
    logger.info("Created Linux Nautilus script at %s", script_file)
    return True


def is_context_menu_enabled() -> bool:
    """Check whether 'File with ScanSort' context menu integration is active."""
    if sys.platform == "win32":
        return _is_win_verb_enabled(VERB_NAME, tuple(SUPPORTED_EXTENSIONS))

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        return xdg_file_has_markers(script_file, "scansort file")

    return False


def enable_context_menu(executable_path: str | None = None) -> bool:
    """Register 'File with ScanSort' in the Windows Explorer context menu (or Linux scripts).

    Args:
        executable_path: Explicit path to the ScanSort executable.

    Returns:
        True if successfully registered, False otherwise.
    """
    full_cmd = _build_context_menu_command(executable_path)
    icon_path = (
        executable_path
        if executable_path
        else (sys.executable if getattr(sys, "frozen", False) else "")
    )

    if sys.platform == "win32":
        ok = _enable_win_verb(
            VERB_NAME,
            VERB_LABEL,
            full_cmd,
            icon_path,
            tuple(SUPPORTED_EXTENSIONS),
        )
        if ok:
            logger.info("Registered Windows Explorer context menu for ScanSort.")
        return ok

    if sys.platform.startswith("linux"):
        content = (
            "#!/bin/sh\n"
            "# File selected documents with ScanSort\n"
            'for f in "$@"; do\n'
            '    scansort file "$f"\n'
            "done\n"
        )
        return _enable_linux_script(_get_linux_nautilus_script_path(), content)

    logger.info("Context menu integration is only supported on Windows and Linux.")
    return False


def disable_context_menu() -> bool:
    """Unregister 'File with ScanSort' context menu integration."""
    if sys.platform == "win32":
        ok = _disable_win_verb(VERB_NAME, tuple(SUPPORTED_EXTENSIONS))
        if ok:
            logger.info("Removed Windows Explorer context menu for ScanSort.")
        return ok

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        if not remove_xdg_file(script_file, description="Nautilus script"):
            return False
        logger.info("Removed Linux Nautilus script.")
        return True

    return True


def is_ocr_menu_enabled() -> bool:
    """Check whether 'Make searchable with ScanSort' context menu integration is active."""
    if sys.platform == "win32":
        return _is_win_verb_enabled(OCR_VERB_NAME, OCR_EXTENSIONS)

    if sys.platform.startswith("linux"):
        script_file = _get_linux_ocr_nautilus_script_path()
        return xdg_file_has_markers(script_file, "scansort ocr-backfill")

    return False


def enable_ocr_menu(executable_path: str | None = None) -> bool:
    """Register 'Make searchable with ScanSort' for PDFs (Windows) or Linux scripts."""
    full_cmd = _build_ocr_menu_command(executable_path)
    icon_path = (
        executable_path
        if executable_path
        else (sys.executable if getattr(sys, "frozen", False) else "")
    )

    if sys.platform == "win32":
        ok = _enable_win_verb(
            OCR_VERB_NAME, OCR_VERB_LABEL, full_cmd, icon_path, OCR_EXTENSIONS
        )
        if ok:
            logger.info("Registered Windows Explorer OCR context menu for ScanSort.")
        return ok

    if sys.platform.startswith("linux"):
        content = (
            "#!/bin/sh\n"
            "# Make selected PDFs searchable with ScanSort\n"
            'for f in "$@"; do\n'
            '    scansort ocr-backfill "$f"\n'
            "done\n"
        )
        return _enable_linux_script(_get_linux_ocr_nautilus_script_path(), content)

    logger.info("Context menu integration is only supported on Windows and Linux.")
    return False


def disable_ocr_menu() -> bool:
    """Unregister 'Make searchable with ScanSort' context menu integration."""
    if sys.platform == "win32":
        ok = _disable_win_verb(OCR_VERB_NAME, OCR_EXTENSIONS)
        if ok:
            logger.info("Removed Windows Explorer OCR context menu for ScanSort.")
        return ok

    if sys.platform.startswith("linux"):
        script_file = _get_linux_ocr_nautilus_script_path()
        if not remove_xdg_file(script_file, description="Nautilus script"):
            return False
        logger.info("Removed Linux OCR Nautilus script.")
        return True

    return True
