# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


repo_root = Path(SPECPATH).resolve().parent
backend_root = repo_root / "backend"

datas = [
    (str(repo_root / "frontend" / "dist"), "frontend/dist"),
    (str(repo_root / "backend" / "alembic.ini"), "backend"),
    (str(repo_root / "backend" / "game_aliases.json"), "backend"),
    (str(repo_root / "docs" / "mwlogo.png"), "docs"),
    (str(repo_root / "README.md"), "."),
    (str(repo_root / "LICENSE"), "."),
]
alembic_datas = Tree(
    str(repo_root / "backend" / "alembic"),
    prefix="backend/alembic",
    excludes=["__pycache__", "*.pyc"],
)

hidden_imports = [
    "app.main",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "pystray._win32",
    "webview",
    "webview.platforms.edgechromium",
    "PIL.Image",
    "PIL.ImageDraw",
    "clr",
]

excluded_modules = [
    "playwright",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "tkinter",
    "_tkinter",
    "gi",
    "gtk",
    "cefpython3",
    "webview.platforms.qt",
    "webview.platforms.gtk",
    "webview.platforms.cef",
    "webview.platforms.cocoa",
    "webview.platforms.android",
]

a = Analysis(
    [str(repo_root / "backend" / "desktop_app.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
a.datas += alembic_datas
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ModWatcherAgent",
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
    contents_directory="_internal",
    icon=str(repo_root / "docs" / "mwlogo.png"),
    version=str(repo_root / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ModWatcherAgent",
)
