"""Windows and cross-platform boot auto-start manager."""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY_NAME = "ScanSort"
WIN_REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_linux_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / "scansort.desktop"


def is_autorun_enabled() -> bool:
    """Check whether ScanSort is set to auto-start on user login."""
    if sys.platform == "win32":
        try:
            import winreg
            reg = getattr(sys.modules.get("scansort.autorun"), "_winreg", winreg)
            with reg.OpenKey(reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_READ) as key:
                reg.QueryValueEx(key, RUN_KEY_NAME)
                return True
        except (OSError, FileNotFoundError, AttributeError):
            return False

    desktop_file = _get_linux_autostart_path()
    return desktop_file.exists()


def enable_autorun(executable_path: str | None = None) -> bool:
    """Configure ScanSort to start automatically on user login.

    Args:
        executable_path: Path to the executable. If None, defaults to current sys.executable.

    Returns:
        True if successfully enabled, False otherwise.
    """
    cmd = executable_path or sys.executable

    if sys.platform == "win32":
        try:
            import winreg
            reg = getattr(sys.modules.get("scansort.autorun"), "_winreg", winreg)
            with reg.OpenKey(reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, RUN_KEY_NAME, 0, reg.REG_SZ, f'"{cmd}" --minimized')
                logger.info("Enabled Windows autorun registry key for %s", cmd)
                return True
        except (OSError, AttributeError) as e:
            logger.warning("Failed to enable Windows autorun registry key: %s", e)
            return False

    # Linux autostart desktop entry
    desktop_file = _get_linux_autostart_path()
    try:
        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=ScanSort\n"
            f"Exec={cmd} watch --minimized\n"
            "Hidden=false\n"
            "NoDisplay=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        desktop_file.write_text(content, encoding="utf-8")
        logger.info("Created Linux autostart file at %s", desktop_file)
        return True
    except OSError as e:
        logger.warning("Failed to create Linux autostart file: %s", e)
        return False


def disable_autorun() -> bool:
    """Disable ScanSort from starting automatically on user login."""
    if sys.platform == "win32":
        try:
            import winreg
            reg = getattr(sys.modules.get("scansort.autorun"), "_winreg", winreg)
            with reg.OpenKey(reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_SET_VALUE) as key:
                reg.DeleteValue(key, RUN_KEY_NAME)
                logger.info("Removed Windows autorun registry key.")
                return True
        except (OSError, FileNotFoundError, AttributeError) as e:
            logger.debug("Autorun key was not present or could not be removed: %s", e)
            return False

    desktop_file = _get_linux_autostart_path()
    if desktop_file.exists():
        try:
            desktop_file.unlink()
            logger.info("Removed Linux autostart file.")
            return True
        except OSError as e:
            logger.warning("Failed to remove Linux autostart file: %s", e)
            return False

    return True
