# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['boson_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Boson Viewer',
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Boson Viewer',
)

app = BUNDLE(
    coll,
    name='Boson Viewer.app',
    icon=None,
    bundle_identifier='com.bosonviewer.app',
    info_plist={
        'NSCameraUsageDescription': 'Boson Viewer needs camera access to stream and record from the thermal camera.',
    },
)
