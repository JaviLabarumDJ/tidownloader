# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ('src/tidownloader/web/templates', 'tidownloader/web/templates'),
    ('src/tidownloader/web/static', 'tidownloader/web/static'),
]
datas += collect_data_files('tidalapi')
datas += collect_data_files('mutagen')

hiddenimports = [
    'jinja2',
    'flask',
    'requests',
    'urllib3',
    'mutagen',
    'Crypto',
    'Crypto.Cipher',
    'Crypto.Cipher.AES',
    'tidalapi',
    'sqlite3',
    'm3u8',
    'rich',
]
hiddenimports += collect_submodules('tidownloader')
hiddenimports += collect_submodules('tidalapi')

# --- 1. tidownloader (CLI) ---
cli_a = Analysis(
    ['src/tidownloader/__main__.py'],
    pathex=['src'],
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
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    [],
    name='tidownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- 2. tidownloader-web (Web Dashboard) ---
web_a = Analysis(
    ['src/tidownloader/web/__main__.py'],
    pathex=['src'],
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
web_pyz = PYZ(web_a.pure, web_a.zipped_data, cipher=block_cipher)
web_exe = EXE(
    web_pyz,
    web_a.scripts,
    web_a.binaries,
    web_a.zipfiles,
    web_a.datas,
    [],
    name='tidownloader-web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
