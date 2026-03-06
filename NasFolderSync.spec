# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['rumps'],
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
    name='NasFolderSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NasFolderSync',
)

app = BUNDLE(
    coll,
    name='NasFolderSync.app',
    icon=None,
    bundle_identifier='com.user.unassync',
    info_plist={
        'LSUIElement': True,          # menu bar only, no Dock icon
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '13.0',
        'NSAppleEventsUsageDescription': 'NasFolderSync needs access to run rclone.',
    },
)
