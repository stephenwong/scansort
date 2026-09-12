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
WIN_BASE_SUBKEY = r"Software\Classes\SystemFileAssociations"

_winreg = None


def _get_winreg():
    """Retrieve the winreg module or test mock seam."""
    return load_winreg(_winreg)


def _build_context_menu_command(executable_path: str | None = None) -> str:
    """Format the full command line invocation for context menu filing."""
    return build_executable_invocation(executable_path, 'file "%1"')


def _delete_subkey_if_exists(reg, parent_path: str, key_name: str) -> None:
    """Delete *key_name* under *parent_path*, ignoring a missing key.

    RegDeleteKey requires the parent handle to carry the DELETE access right,
    which KEY_SET_VALUE does not grant, so both bits are requested.
    """
    try:
        with reg.OpenKey(
            reg.HKEY_CURRENT_USER, parent_path, 0, reg.KEY_SET_VALUE | reg.DELETE
        ) as key:
            reg.DeleteKey(key, key_name)
    except FileNotFoundError:
        pass


def _get_linux_nautilus_script_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "nautilus" / "scripts" / "File with ScanSort"


def is_context_menu_enabled() -> bool:
    """Check whether 'File with ScanSort' context menu integration is active."""
    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            for ext in sorted(SUPPORTED_EXTENSIONS):
                check_key = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{VERB_NAME}\\command"
                with reg.OpenKey(
                    reg.HKEY_CURRENT_USER, check_key, 0, reg.KEY_READ
                ) as key:
                    val, _ = reg.QueryValueEx(key, "")
                    if not str(val).strip():
                        return False
            return True
        except OSError, AttributeError, ImportError:
            return False

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
        try:
            reg = _get_winreg()
            ok = True
            for ext in sorted(SUPPORTED_EXTENSIONS):
                verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{VERB_NAME}"
                cmd_path = f"{verb_path}\\command"
                try:
                    with reg.CreateKey(reg.HKEY_CURRENT_USER, verb_path) as verb_key:
                        reg.SetValueEx(verb_key, "", 0, reg.REG_SZ, VERB_LABEL)
                        if icon_path:
                            reg.SetValueEx(verb_key, "Icon", 0, reg.REG_SZ, icon_path)

                    with reg.CreateKey(reg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
                        reg.SetValueEx(cmd_key, "", 0, reg.REG_SZ, full_cmd)
                except OSError as e:
                    logger.warning("Failed to register context menu for %s: %s", ext, e)
                    ok = False

            if ok:
                logger.info("Registered Windows Explorer context menu for ScanSort.")
            return ok
        except (OSError, AttributeError, ImportError) as e:
            logger.warning("Failed to enable Windows context menu: %s", e)
            return False

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        content = (
            "#!/bin/sh\n"
            "# File selected documents with ScanSort\n"
            'for f in "$@"; do\n'
            '    scansort file "$f"\n'
            "done\n"
        )
        if not write_xdg_file(
            script_file, content, description="Nautilus script", executable=True
        ):
            return False
        logger.info("Created Linux Nautilus script at %s", script_file)
        return True

    logger.info("Context menu integration is only supported on Windows and Linux.")
    return False


def disable_context_menu() -> bool:
    """Unregister 'File with ScanSort' context menu integration."""
    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            ok = True
            for ext in sorted(SUPPORTED_EXTENSIONS):
                verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{VERB_NAME}"
                parent_shell = f"{WIN_BASE_SUBKEY}\\{ext}\\shell"
                try:
                    _delete_subkey_if_exists(reg, verb_path, "command")
                    _delete_subkey_if_exists(reg, parent_shell, VERB_NAME)
                except OSError as e:
                    logger.warning("Failed to remove context menu for %s: %s", ext, e)
                    ok = False

            if ok:
                logger.info("Removed Windows Explorer context menu for ScanSort.")
            return ok
        except (OSError, AttributeError, ImportError) as e:
            logger.warning("Failed to remove Windows context menu: %s", e)
            return False

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        if not remove_xdg_file(script_file, description="Nautilus script"):
            return False
        logger.info("Removed Linux Nautilus script.")
        return True

    return True
