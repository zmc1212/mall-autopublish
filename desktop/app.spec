# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

spec_dir = Path(SPECPATH).resolve()
root = spec_dir.parent

datas = [
    (str(root / "templates"), "templates"),
    (str(root / "web_fill"), "web_fill"),
    (str(root / "千牛字段映射.json"), "."),
    (str(root / "千牛自动上架.py"), "."),
    (str(root / "千牛网页执行.py"), "."),
    (str(root / "job_session.py"), "."),
    (str(root / "workspace.py"), "."),
]
ui_dist = root / "desktop" / "ui" / "dist"
if (ui_dist / "index.html").is_file():
    datas.append((str(ui_dist), "web"))

binaries = []
hiddenimports = collect_submodules("desktop") + collect_submodules("web_fill") + [
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "openpyxl",
    "PIL",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "千牛自动上架",
    "千牛网页执行",
    "商品解析",
    "job_session",
    "workspace",
]
for pkg in ("webview", "uvicorn", "fastapi", "starlette"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(root / "run_desktop.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="千牛自动上架",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="千牛自动上架",
)
