# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = []
datas += collect_data_files("scansort")
# IANA timezone database required by zoneinfo on Windows (Australia/Sydney).
datas += collect_data_files("tzdata")

hiddenimports = [
    "pydantic",
    "pydantic_core",
    "keyring",
    "keyring.backends",
    "watchfiles",
    "google.genai",
    "pypdf",
    "img2pdf",
    "PIL",
    "tzdata.zoneinfo",
    # Windows toast notifications (optional 'windows' extra) - lazily imported
    # by scansort.toasts, so their winrt extension modules must be named here.
    "windows_toasts",
    "winrt",
    "winrt.windows.data.xml.dom",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.ui.notifications",
]

a = Analysis(
    ["scansort/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScanSort",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ScanSort",
)
