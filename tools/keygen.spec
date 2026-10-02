# -*- mode: python ; coding: utf-8 -*-
"""千牛发码工具（单文件 GUI）打包配置。

用法（在仓库根目录）：
  python -m PyInstaller tools/keygen.spec --noconfirm

产物：dist/千牛发码工具.exe（双击即用，无需 Python）。
私钥不打包进 exe：运行时从 %USERPROFILE%\\.qianniu-license\\private.key 读取。
"""
import os

a = Analysis(
    ["license_keygen.py"],
    pathex=[SPECPATH, os.path.abspath(os.path.join(SPECPATH, ".."))],
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
    a.binaries,
    a.datas,
    [],
    name="千牛发码工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "..", "logo", "40c40691-9747-453a-a1d1-f2c94d393f34.ico"),
)
