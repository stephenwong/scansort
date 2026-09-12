"""Shared helpers for formatting ScanSort executable invocations."""

import sys


def build_executable_invocation(executable_path: str | None, args: str) -> str:
    """Format a quoted ScanSort invocation with trailing *args*.

    Uses an explicit executable path when provided, the frozen executable when
    bundled, and ``sys.executable -m scansort`` in development.
    """
    if executable_path:
        base_cmd = f'"{executable_path}"'
    elif getattr(sys, "frozen", False):
        base_cmd = f'"{sys.executable}"'
    else:
        base_cmd = f'"{sys.executable}" -m scansort'
    return f"{base_cmd} {args}"
