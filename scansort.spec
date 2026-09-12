# -*- mode: python ; coding: utf-8 -*-

import os
import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Synchronize version_info.txt with scansort.__version__
_init_py = Path(SPECPATH) / "scansort" / "__init__.py"
_version_str = "0.0.0"
if _init_py.is_file():
    _m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _init_py.read_text(encoding="utf-8"))
    if _m:
        _version_str = _m.group(1)

_nums = [int(x) for x in _version_str.split(".") if x.isdigit()]
while len(_nums) < 4:
    _nums.append(0)
_ver_tuple = tuple(_nums[:4])

_target_dir = Path(workpath) if "workpath" in globals() else Path(SPECPATH) / "build"
_target_dir.mkdir(parents=True, exist_ok=True)
_version_file = _target_dir / "version_info.txt"
_version_info_content = f"""# UTF-8
# Windows Version Info Resource for PyInstaller
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_ver_tuple},
    prodvers={_ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Stephen Wong'),
            StringStruct('FileDescription', 'ScanSort: Intelligent automated desktop document filer powered by Google Gemini'),
            StringStruct('FileVersion', '{_version_str}.0'),
            StringStruct('InternalName', 'ScanSort'),
            StringStruct('LegalCopyright', 'Copyright (c) Stephen Wong'),
            StringStruct('OriginalFilename', 'ScanSort.exe'),
            StringStruct('ProductName', 'ScanSort'),
            StringStruct('ProductVersion', '{_version_str}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
_version_file.write_text(_version_info_content, encoding="utf-8")

datas = []
datas += collect_data_files("scansort")
# IANA timezone database required by zoneinfo on Windows (Australia/Sydney).
datas += collect_data_files("tzdata")

# Bundle the Tesseract OCR engine alongside the executable so OCR works
# out-of-the-box in release builds (tesseract is an Apache-2.0 system binary).
binaries = []
upx_exclude = []
_tesseract_dir = Path(
    os.environ.get("TESSERACT_DIR", r"C:\Program Files\Tesseract-OCR")
)
if _tesseract_dir.is_dir():
    upx_exclude.append("tesseract/*")
    _tesseract_exe = _tesseract_dir / "tesseract.exe"
    if _tesseract_exe.is_file():
        binaries.append((str(_tesseract_exe), "tesseract"))
    for _dll in _tesseract_dir.glob("*.dll"):
        binaries.append((str(_dll), "tesseract"))
    for _lang in ("eng.traineddata", "osd.traineddata"):
        _data_file = _tesseract_dir / "tessdata" / _lang
        if _data_file.is_file():
            datas.append((str(_data_file), "tesseract/tessdata"))

hiddenimports = [
    "pydantic",
    "pydantic_core",
    "keyring",
    "keyring.backends",
    "watchfiles",
    "google.genai",
    "pypdf",
    "img2pdf",
    "pytesseract",
    "PIL",
    "pystray",
    "pystray._win32",
    "pystray._util",
    "pystray._util.win32",
    "tkinter",
    "tkinter.ttk",
    "tzdata.zoneinfo",
    # Windows toast notifications (optional 'windows' extra) - lazily imported
    # by scansort.platform.toasts, so their winrt extension modules must be named here.
    "windows_toasts",
    "winrt",
    "winrt.windows.data.xml.dom",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.ui.notifications",
]
hiddenimports += collect_submodules("pystray")

a = Analysis(
    ["scansort/__main__.py"],
    pathex=[],
    binaries=binaries,
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
    version=str(_version_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=upx_exclude,
    name="ScanSort",
)
