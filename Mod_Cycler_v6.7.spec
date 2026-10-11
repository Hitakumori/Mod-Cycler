# -*- mode: python ; coding: utf-8 -*-
import os
import sys

PYTHON_ROOT = sys.base_prefix
TKINTER_DIR = os.path.join(PYTHON_ROOT, 'Lib', 'tkinter')
TKINTER_DATA = [
    (os.path.join(root, file_name), os.path.relpath(root, os.path.join(PYTHON_ROOT, 'Lib')))
    for root, _, file_names in os.walk(TKINTER_DIR)
    for file_name in file_names
]

a = Analysis(
    ['Mod_Cycler_v6_7.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        # Explicitly include Tcl/Tk and the Python tkinter package, including
        # when building inside a virtual environment.
        *TKINTER_DATA,
        (os.path.join(PYTHON_ROOT, 'tcl', 'tcl8.6'), '_tcl_data'),
        (os.path.join(PYTHON_ROOT, 'tcl', 'tk8.6'), '_tk_data'),
    ],
    hiddenimports=['tkinter', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tcl_runtime_hook.py'],
    excludes=['numpy', 'tkcolorpicker'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Mod_Cycler_v6.7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version.txt',
    icon=['icon.ico'],
)
