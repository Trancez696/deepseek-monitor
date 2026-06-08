# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— DeepSeek Monitor

使用 onedir 模式（推荐）：
    python -m PyInstaller DeepSeekMonitor.spec --noconfirm

瘦身打包说明：
    默认不把 Playwright Chromium 打进包里。
    自动同步优先使用系统默认 Edge / Chrome。
    如果没有可控浏览器，用户可额外安装 Playwright Chromium。

推荐使用 scripts/build_exe.ps1 一键打包。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH)

# ---------------------------------------------------------------------------
# 尝试收集 playwright driver 二进制文件（显式兜底）
#
# PyInstaller 的 playwright hook 会自动收集 driver/ 下的文件，但为了确保
# 所有 .exe / .dll / .js 等文件都不被遗漏，这里手动 glob 一遍。
# ---------------------------------------------------------------------------
def _collect_playwright_driver():
    """收集 playwright driver，但跳过 .local-browsers 浏览器本体。"""
    binaries = []
    datas = []
    try:
        import playwright as _pw
    except ImportError:
        return binaries, datas

    pw_root = Path(_pw.__file__).parent
    driver_dir = pw_root / "driver"
    if not driver_dir.is_dir():
        return binaries, datas

    for fpath in driver_dir.rglob("*"):
        if not fpath.is_file():
            continue
        if ".local-browsers" in fpath.parts:
            continue
        # 目标路径：相对于 playwright 包的父目录
        dest = str(fpath.relative_to(pw_root.parent).parent)
        src = str(fpath)
        if fpath.suffix.lower() in (".exe", ".dll", ".node", ".so", ".dylib"):
            binaries.append((src, dest))
        else:
            datas.append((src, dest))

    return binaries, datas


_extra_binaries, _extra_datas = _collect_playwright_driver()

# ---------------------------------------------------------------------------
# 排除不需要打包的模块，减小体积
# ---------------------------------------------------------------------------
excluded_modules = [
    "tkinter", "matplotlib", "numpy", "pandas", "PIL",
    "PyQt5", "PyQt6", "wx", "gi", "curses",
    "notebook", "jupyter", "IPython",
    "sympy", "scipy", "lxml",
    "setuptools", "pkg_resources",
    "altgraph", "pefile",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtVirtualKeyboard", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets",
]

# ---------------------------------------------------------------------------
# 需要一起打包的数据文件
# ---------------------------------------------------------------------------
added_files = [
    (str(PROJECT_ROOT / "assets" / "icon.ico"), "assets"),
    (str(PROJECT_ROOT / "assets" / "icon.png"), "assets"),
    (str(PROJECT_ROOT / "config.example.json"), "."),
]
# 追加 playwright driver 中的非二进制文件
added_files.extend(_extra_datas)

# ---------------------------------------------------------------------------
# 需要确保被 PyInstaller 发现的隐藏导入
# ---------------------------------------------------------------------------
hidden_imports = [
    # PySide6
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",

    # requests
    "requests", "urllib3",

    # keyring（系统凭据管理器）
    "keyring",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",

    # playwright（浏览器自动化）
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    "playwright._impl",
    "playwright._impl._browser_type",
    "playwright._impl._transport",
    "playwright._impl._connection",
    "playwright._impl._helper",

    # SQLite
    "sqlite3",

    # 项目内部模块
    "src", "src.app_data", "src.app", "src.autostart_manager",
    "src.api_client", "src.config_manager",
    "src.database", "src.widgets", "src.styles", "src.workers",
    "src.usage_downloader", "src.usage_importer", "src.tray",
]

# ---------------------------------------------------------------------------
# PyInstaller Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "src")],
    binaries=_extra_binaries,            # playwright driver node.exe / .dll
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(PROJECT_ROOT / "scripts" / "pyi_rth_playwright.py"),
    ],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)


def _drop_playwright_browsers(items):
    """过滤 PyInstaller hook 自动收集的 Playwright 浏览器本体。"""
    filtered = []
    for item in items:
        source = str(item[0]).replace("\\", "/")
        target = str(item[1]).replace("\\", "/") if len(item) > 1 else ""
        if ".local-browsers" in source or ".local-browsers" in target:
            continue
        if "chromium-" in source and "playwright" in source:
            continue
        if "chromium_headless_shell" in source and "playwright" in source:
            continue
        if "ffmpeg-" in source and "playwright" in source:
            continue
        filtered.append(item)
    return filtered


def _drop_unused_qt(items):
    """过滤当前界面不需要的 Qt 大组件。"""
    blocked = [
        "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard",
        "Qt6OpenGL", "QtQuick", "QtQml", "QtPdf", "QtVirtualKeyboard",
        "QtSvg", "qml", "translations/qtwebengine", "opengl32sw.dll",
    ]
    filtered = []
    for item in items:
        source = str(item[0]).replace("\\", "/")
        target = str(item[1]).replace("\\", "/") if len(item) > 1 else ""
        combined = f"{source}/{target}"
        if any(name in combined for name in blocked):
            continue
        filtered.append(item)
    return filtered


a.datas = _drop_playwright_browsers(a.datas)
a.binaries = _drop_playwright_browsers(a.binaries)
a.datas = _drop_unused_qt(a.datas)
a.binaries = _drop_unused_qt(a.binaries)

# ---------------------------------------------------------------------------
# PYZ
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DeepSeek Monitor",
    icon=str(PROJECT_ROOT / "assets" / "icon.ico"),
    console=False,
    debug=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ---------------------------------------------------------------------------
# COLLECT — onedir 模式
#
#   coll 收集所有依赖到一个目录：
#     dist/DeepSeek Monitor/
#       ├── DeepSeek Monitor.exe
#       └── _internal/
#           ├── playwright/driver/  （含 node.exe，不含 Chromium 浏览器本体）
#           ├── PySide6/
#           ├── python312.dll
#           └── ...
#
#   用户数据（browser_profile / exports / usage.db / config.json）
#   不走程序目录，统一存到 %LOCALAPPDATA%\\DeepSeek Monitor\\
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DeepSeek Monitor",
)

# vim: ft=python
