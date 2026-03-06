# -*- mode: python ; coding: utf-8 -*-
import re

# Read version from sync.py (single source of truth)
with open('sync.py') as f:
    _version_match = re.search(r"APP_VERSION\s*=\s*'([^']+)'", f.read())
    VERSION = _version_match.group(1) if _version_match else '0.0.0'

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
    name='FolderSync',
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
    name='FolderSync',
)

app = BUNDLE(
    coll,
    name='FolderSync.app',
    icon='FolderSync.icns',
    bundle_identifier='com.ranthebuilder.foldersync',
    info_plist={
        'LSUIElement': True,          # menu bar only, no Dock icon
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': VERSION,
        'LSMinimumSystemVersion': '13.0',
        'NSAppleEventsUsageDescription': 'FolderSync needs access to run rclone.',
    },
)
