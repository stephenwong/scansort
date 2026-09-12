"""Windows Explorer and Linux file manager context menu integration."""

import logging
import os
import stat
import sys
from pathlib import Path

from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)

VERB_NAME = "ScanSort"
VERB_LABEL = "File with ScanSort"
WIN_BASE_SUBKEY = r"Software\Classes\SystemFileAssociations"

_winreg = None


def _get_winreg():
    """Retrieve the winreg module or test mock seam."""
    if _winreg is not None:
        return _winreg
    import winreg

    return winreg


def _build_context_menu_command(executable_path: str | None = None) -> str:
    """Format the full command line invocation for context menu filing."""
    if executable_path:
        base_cmd = f'"{executable_path}"'
    elif getattr(sys, "frozen", False):
        base_cmd = f'"{sys.executable}"'
    else:
        base_cmd = f'"{sys.executable}" -m scansort'
    return f'{base_cmd} file "%1"'


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
        except OSError, FileNotFoundError, AttributeError, ImportError:
            return False

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        if not script_file.exists():
            return False
        try:
            content = script_file.read_text(encoding="utf-8")
            return "scansort file" in content
        except OSError:
            return False

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
            for ext in sorted(SUPPORTED_EXTENSIONS):
                verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{VERB_NAME}"
                cmd_path = f"{verb_path}\\command"

                with reg.CreateKey(reg.HKEY_CURRENT_USER, verb_path) as verb_key:
                    reg.SetValueEx(verb_key, "", 0, reg.REG_SZ, VERB_LABEL)
                    if icon_path:
                        reg.SetValueEx(verb_key, "Icon", 0, reg.REG_SZ, icon_path)

                with reg.CreateKey(reg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
                    reg.SetValueEx(cmd_key, "", 0, reg.REG_SZ, full_cmd)

            logger.info("Registered Windows Explorer context menu for ScanSort.")
            return True
        except (OSError, AttributeError, ImportError) as e:
            logger.warning("Failed to enable Windows context menu: %s", e)
            return False

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        try:
            script_file.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "#!/bin/sh\n"
                "# File selected documents with ScanSort\n"
                'for f in "$@"; do\n'
                '    scansort file "$f"\n'
                "done\n"
            )
            atomic_write(script_file, content)
            current_mode = script_file.stat().st_mode
            script_file.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            logger.info("Created Linux Nautilus script at %s", script_file)
            return True
        except OSError as e:
            logger.warning("Failed to create Linux Nautilus script: %s", e)
            return False

    logger.info("Context menu integration is only supported on Windows and Linux.")
    return False


def disable_context_menu() -> bool:
    """Unregister 'File with ScanSort' context menu integration."""
    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            for ext in sorted(SUPPORTED_EXTENSIONS):
                verb_path = f"{WIN_BASE_SUBKEY}\\{ext}\\shell\\{VERB_NAME}"

                try:
                    with reg.OpenKey(
                        reg.HKEY_CURRENT_USER, verb_path, 0, reg.KEY_SET_VALUE
                    ) as key:
                        reg.DeleteKey(key, "command")
                except FileNotFoundError:
                    pass

                try:
                    parent_shell = f"{WIN_BASE_SUBKEY}\\{ext}\\shell"
                    with reg.OpenKey(
                        reg.HKEY_CURRENT_USER, parent_shell, 0, reg.KEY_SET_VALUE
                    ) as key:
                        reg.DeleteKey(key, VERB_NAME)
                except FileNotFoundError:
                    pass

            logger.info("Removed Windows Explorer context menu for ScanSort.")
            return True
        except (OSError, AttributeError, ImportError) as e:
            logger.warning("Failed to remove Windows context menu: %s", e)
            return False

    if sys.platform.startswith("linux"):
        script_file = _get_linux_nautilus_script_path()
        try:
            script_file.unlink(missing_ok=True)
            logger.info("Removed Linux Nautilus script.")
            return True
        except OSError as e:
            logger.warning("Failed to remove Linux Nautilus script: %s", e)
            return False

    return True
