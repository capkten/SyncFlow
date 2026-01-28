# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 收集 backend 下的所有子模块，确保不会遗漏
hidden_imports = collect_submodules('backend')
hidden_imports.extend([
    'engineio.async_drivers.threading',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.lifespan.on',
    'websockets.legacy',
    'websockets.legacy.server',
    'websockets.legacy.client',
    'watchdog.observers.read_directory_changes',
    'sqlalchemy.sql.default_comparator',
    'sqlalchemy.ext.baked',
    'bcrypt',
    'passlib.handlers.bcrypt',
    'clr_loader',
    'pythonnet'
])

a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('backend', 'backend'),
        ('icon.ico', '.')
    ],
    hiddenimports=hidden_imports,
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
    name='TongbuSync',
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
    icon='icon.ico'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TongbuSync',
)
