"""DeepSeek Monitor 程序入口。

从这里启动 PySide6 桌面窗口。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

from src.app import run_app

_MUTEX_HANDLE = None
_ERROR_ALREADY_EXISTS = 183


def parse_args() -> argparse.Namespace:
    """解析命令行启动参数。"""
    parser = argparse.ArgumentParser(description="DeepSeek Monitor")
    parser.add_argument("--startup", action="store_true", help="以开机自启模式启动")
    return parser.parse_args()


def _acquire_single_instance() -> bool:
    """创建 Windows 命名 mutex，避免多个实例同时运行。"""
    global _MUTEX_HANDLE

    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, "Local\\DeepSeekMonitorSingleInstance")
    if not _MUTEX_HANDLE:
        return True

    return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


def _show_already_running_message(startup: bool) -> None:
    """第二个实例启动时给出提示。"""
    if startup or os.name != "nt":
        return

    ctypes.windll.user32.MessageBoxW(
        None,
        "DeepSeek Monitor 已经在运行。\n请通过系统托盘图标打开窗口。",
        "DeepSeek Monitor",
        0x40,
    )


def main() -> None:
    """程序主函数。"""
    args = parse_args()
    if not _acquire_single_instance():
        _show_already_running_message(args.startup)
        return

    run_app(startup=args.startup)


if __name__ == "__main__":
    main()
