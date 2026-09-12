"""Shared lazy-import seam for the Windows registry module."""

from types import ModuleType


def load_winreg(seam: ModuleType | None):
    """Return the injected test seam, or lazily import the real ``winreg`` module."""
    if seam is not None:
        return seam
    import winreg

    return winreg
