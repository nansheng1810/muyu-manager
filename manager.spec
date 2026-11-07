# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：客户端目录（onedir）、无控制台窗口、内置 web 资源。

产出 dist/牧鱼/ 整个文件夹即为客户端，双击其中的 exe 运行。
运行数据写入 %LOCALAPPDATA%\\AstrBot舰队管理器\\data（源码模式写入项目根 data/），
升级时只替换 _internal 与 exe 即可保留数据。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

hidden = (
    collect_submodules("server")
    + [
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
    ]
)

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "web"), "web")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="牧鱼",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ROOT / "web" / "assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="牧鱼",
    contents_directory="_internal",
)
