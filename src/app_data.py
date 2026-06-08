"""用户数据目录管理模块。

所有可写用户数据统一放到 %LOCALAPPDATA%\\DeepSeek Monitor\\：

    browser_profile  — Playwright 浏览器登录会话
    auth_state.json   — Playwright 登录状态快照
    exports          — 静默同步下载的 Usage 导出文件
    logs             — 运行日志（预留）

不依赖相对路径，不把用户数据放到程序安装目录。
"""

from __future__ import annotations

import os
from pathlib import Path


_APP_NAME = "DeepSeek Monitor"


def _get_local_appdata() -> Path:
    """返回 Windows LOCALAPPDATA 目录。

    示例：C:\\Users\\<用户名>\\AppData\\Local
    """
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        # 极少情况下的兜底
        home = Path.home()
        local_appdata = str(home / "AppData" / "Local")
    return Path(local_appdata)


def get_app_data_dir() -> Path:
    """返回用户数据根目录。

    %LOCALAPPDATA%\\DeepSeek Monitor\\
    """
    return _get_local_appdata() / _APP_NAME


def get_browser_profile_dir() -> Path:
    """返回 Playwright 浏览器登录会话目录。"""
    return get_app_data_dir() / "browser_profile"


def get_auth_state_path() -> Path:
    """返回 Playwright 登录状态快照文件路径。"""
    return get_app_data_dir() / "auth_state.json"


def get_exports_dir() -> Path:
    """返回静默同步下载的 Usage 导出文件目录。"""
    return get_app_data_dir() / "exports"


def get_logs_dir() -> Path:
    """返回日志文件目录。"""
    return get_app_data_dir() / "logs"


def get_diagnostics_dir() -> Path:
    """返回诊断文件目录（截图、HTML、诊断 JSON）。"""
    return get_app_data_dir() / "diagnostics"


def ensure_app_data_dirs() -> None:
    """创建所有用户数据子目录。"""
    get_browser_profile_dir().mkdir(parents=True, exist_ok=True)
    get_exports_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_diagnostics_dir().mkdir(parents=True, exist_ok=True)
