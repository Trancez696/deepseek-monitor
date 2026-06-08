"""Windows 开机自启管理模块。

使用当前用户 HKCU Run 注册表项，不需要管理员权限。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from src.app_data import get_logs_dir


class AutoStartError(Exception):
    """开机自启设置失败。"""


class AutoStartManager:
    """管理 Windows 当前用户开机自启。"""

    APP_NAME = "DeepSeek Monitor"
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def get_startup_command() -> str:
        """返回当前程序用于开机自启的启动命令。"""
        if getattr(sys, "frozen", False):
            exe_path = Path(sys.executable)
            return f'"{exe_path}" --startup'

        project_root = Path(__file__).resolve().parent.parent
        main_path = project_root / "main.py"
        python_path = Path(sys.executable)
        return f'"{python_path}" "{main_path}" --startup'

    @staticmethod
    def enable() -> None:
        """写入 HKCU Run 注册表。"""
        if os.name != "nt":
            raise AutoStartError("当前系统不支持 Windows 开机自启。")

        command = AutoStartManager.get_startup_command()
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    AutoStartManager.APP_NAME,
                    0,
                    winreg.REG_SZ,
                    command,
                )
        except OSError as error:
            AutoStartManager._write_log(f"Autostart enable failed: {error}")
            raise AutoStartError(f"写入开机自启失败：{error}") from error

        AutoStartManager._write_log("Autostart enabled")
        AutoStartManager._write_log(f"Autostart command: {command}")

    @staticmethod
    def disable() -> None:
        """删除 HKCU Run 注册表项。"""
        if os.name != "nt":
            raise AutoStartError("当前系统不支持 Windows 开机自启。")

        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg.DeleteValue(key, AutoStartManager.APP_NAME)
                except FileNotFoundError:
                    pass
        except OSError as error:
            AutoStartManager._write_log(f"Autostart disable failed: {error}")
            raise AutoStartError(f"删除开机自启失败：{error}") from error

        AutoStartManager._write_log("Autostart disabled")

    @staticmethod
    def is_enabled() -> bool:
        """检查当前注册表中是否已经启用开机自启。"""
        return AutoStartManager.get_registered_command() is not None

    @staticmethod
    def get_registered_command() -> str | None:
        """返回当前注册表中保存的启动命令。"""
        if os.name != "nt":
            return None

        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.RUN_KEY,
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, AutoStartManager.APP_NAME)
                return str(value)
        except FileNotFoundError:
            return None
        except OSError:
            return None

    @staticmethod
    def _write_log(message: str) -> None:
        """写入开机自启日志，不包含敏感信息。"""
        try:
            logs_dir = get_logs_dir()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / "app.log"
            line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
            with log_file.open("a", encoding="utf-8") as file:
                file.write(line)
        except OSError:
            return
