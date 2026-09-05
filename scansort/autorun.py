"""Windows and cross-platform boot auto-start manager."""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY_NAME = "ScanSort"
WIN_REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_winreg():
    """Retrieve the winreg module or test mock seam."""
    import winreg

    return getattr(sys.modules.get("scansort.autorun"), "_winreg", winreg)


def _build_autorun_command(executable_path: str | None = None) -> str:
    """Format the full command line invocation for background watch mode."""
    if executable_path:
        base_cmd = f'"{executable_path}"'
    elif getattr(sys, "frozen", False):
        base_cmd = f'"{sys.executable}"'
    else:
        base_cmd = f'"{sys.executable}" -m scansort'
    return f"{base_cmd} watch --minimized"


def _get_linux_autostart_path() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "autostart" / "scansort.desktop"


def is_autorun_enabled() -> bool:
    """Check whether ScanSort is set to auto-start on user login."""
    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            with reg.OpenKey(
                reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_READ
            ) as key:
                reg.QueryValueEx(key, RUN_KEY_NAME)
                return True
        except (OSError, FileNotFoundError, AttributeError, ImportError):
            return False

    if sys.platform.startswith("linux"):
        desktop_file = _get_linux_autostart_path()
        return desktop_file.exists()

    return False


def enable_autorun(executable_path: str | None = None) -> bool:
    """Configure ScanSort to start automatically on user login.

    Args:
        executable_path: Path to the executable. If None, defaults to current sys.executable.

    Returns:
        True if successfully enabled, False otherwise.
    """
    full_cmd = _build_autorun_command(executable_path)

    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            with reg.OpenKey(
                reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_SET_VALUE
            ) as key:
                reg.SetValueEx(key, RUN_KEY_NAME, 0, reg.REG_SZ, full_cmd)
                logger.info("Enabled Windows autorun registry key for %s", full_cmd)
                return True
        except (OSError, AttributeError, ImportError) as e:
            logger.warning("Failed to enable Windows autorun registry key: %s", e)
            return False

    if sys.platform.startswith("linux"):
        # Linux autostart desktop entry
        desktop_file = _get_linux_autostart_path()
        try:
            desktop_file.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=ScanSort\n"
                f"Exec={full_cmd}\n"
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

    logger.info("Auto-start on boot is only supported on Windows and Linux.")
    return False


def disable_autorun() -> bool:
    """Disable ScanSort from starting automatically on user login."""
    if sys.platform == "win32":
        try:
            reg = _get_winreg()
            with reg.OpenKey(
                reg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, reg.KEY_SET_VALUE
            ) as key:
                reg.DeleteValue(key, RUN_KEY_NAME)
                logger.info("Removed Windows autorun registry key.")
                return True
        except FileNotFoundError:
            return True
        except (OSError, AttributeError, ImportError) as e:
            logger.debug("Autorun key was not present or could not be removed: %s", e)
            return False

    if sys.platform.startswith("linux"):
        desktop_file = _get_linux_autostart_path()
        if not desktop_file.exists():
            return True
        try:
            desktop_file.unlink()
            logger.info("Removed Linux autostart file.")
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            logger.warning("Failed to remove Linux autostart file: %s", e)
            return False

    return True
