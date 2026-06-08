"""本地配置读写模块。

API Key 优先使用 Windows Credential Manager（keyring）。
其他程序设置保存到 %LOCALAPPDATA%\\DeepSeek Monitor\\config.json。

.github 控制：
- config.json 已加入 .gitignore
- config.example.json 只放示例结构
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.app_data import get_app_data_dir


def _get_readonly_root() -> Path:
    """返回只读资源目录（config.example.json 所在）。

    开发环境：项目根目录
    PyInstaller 打包：_MEIPASS 临时目录
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _get_readonly_root()
CONFIG_FILE = get_app_data_dir() / "config.json"
EXAMPLE_CONFIG_FILE = PROJECT_ROOT / "config.example.json"
SERVICE_NAME = "DeepSeekMonitor"
API_KEY_USERNAME = "deepseek_api_key"


@dataclass
class AppConfig:
    """程序配置。

    api_key:
        兼容旧配置字段。新版本优先使用系统凭据保存 API Key。
    api_base_url:
        DeepSeek API 基础地址，通常不用改。
    autostart_enabled:
        是否启用 Windows 开机自启。
    start_minimized_to_tray:
        启动后是否直接进入系统托盘。
    refresh_interval_minutes:
        余额刷新间隔（分钟）。
    always_on_top:
        是否窗口置顶。
    balance_warning_yellow:
        余额偏低提醒阈值（¥）。
    balance_warning_red:
        余额严重不足提醒阈值（¥）。
    auto_refresh_on_startup:
        启动后是否自动刷新。
    scheduled_refresh_enabled:
        是否启用定时刷新。
    silent_usage_sync_enabled:
        刷新时是否自动静默同步 DeepSeek Usage。
    hide_taskbar_icon:
        是否隐藏 Windows 任务栏图标，仅显示系统托盘图标。
    """

    api_key: str = ""
    api_base_url: str = "https://api.deepseek.com"
    auto_start: bool = False
    autostart_enabled: bool = False
    start_minimized_to_tray: bool = False
    refresh_interval_minutes: int = 10
    always_on_top: bool = False
    balance_warning_yellow: float = 5.0
    balance_warning_red: float = 1.0
    auto_refresh_on_startup: bool = True
    scheduled_refresh_enabled: bool = True
    silent_usage_sync_enabled: bool = True
    hide_taskbar_icon: bool = False


class ConfigManager:
    """负责读取和保存 config.json。"""

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file

    def load(self) -> AppConfig:
        """读取配置文件。

        如果 config.json 不存在，就返回默认配置。
        自动迁移旧的明文 API Key 到 keyring。
        """
        if not self.config_file.exists():
            return AppConfig()

        try:
            with self.config_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return AppConfig()

        config = self._config_from_dict(data)
        # 自动迁移：旧版本的明文 API Key → keyring
        if config.api_key and self._set_api_key_to_keyring(config.api_key):
            config.api_key = ""
            self.save(config)
        return config

    def save(self, config: AppConfig) -> None:
        """保存配置到 config.json。"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with self.config_file.open("w", encoding="utf-8") as file:
            json.dump(asdict(config), file, ensure_ascii=False, indent=2)

    def get_api_key(self) -> str | None:
        """读取 API Key，优先从系统凭据读取。"""
        api_key = self._get_api_key_from_keyring()
        if api_key:
            return api_key

        config = self.load()
        return config.api_key or None

    def set_api_key(self, api_key: str) -> None:
        """保存 API Key，优先写入系统凭据。"""
        clean_key = api_key.strip()
        if not clean_key:
            return

        if self._set_api_key_to_keyring(clean_key):
            config = self.load()
            if config.api_key:
                config.api_key = ""
                self.save(config)
            return

        config = self.load()
        config.api_key = clean_key
        self.save(config)

    def clear_api_key(self) -> None:
        """清除保存的 API Key。"""
        self._clear_api_key_from_keyring()
        config = self.load()
        if config.api_key:
            config.api_key = ""
            self.save(config)

    def has_api_key(self) -> bool:
        """判断是否已保存 API Key。"""
        return bool(self.get_api_key())

    def get_masked_api_key(self) -> str:
        """返回脱敏后的 API Key。"""
        api_key = self.get_api_key()
        if not api_key:
            return "未设置"
        return mask_api_key(api_key)

    def _config_from_dict(self, data: dict[str, Any]) -> AppConfig:
        """把字典转换成 AppConfig，并为缺失字段填默认值。

        兼容旧配置字段名：
        - balance_warning_threshold → balance_warning_yellow
        - balance_critical_threshold → balance_warning_red
        """
        return AppConfig(
            api_key=str(data.get("api_key", "")),
            api_base_url=str(data.get(
                "api_base_url", "https://api.deepseek.com"
            )),
            auto_start=bool(data.get("auto_start", False)),
            autostart_enabled=bool(data.get(
                "autostart_enabled",
                data.get("auto_start", False),
            )),
            start_minimized_to_tray=bool(data.get(
                "start_minimized_to_tray", False
            )),
            refresh_interval_minutes=int(data.get(
                "refresh_interval_minutes", 10
            )),
            always_on_top=bool(data.get("always_on_top", False)),
            balance_warning_yellow=float(data.get(
                "balance_warning_yellow",
                data.get("balance_warning_threshold", 5.0),
            )),
            balance_warning_red=float(data.get(
                "balance_warning_red",
                data.get("balance_critical_threshold", 1.0),
            )),
            auto_refresh_on_startup=bool(data.get(
                "auto_refresh_on_startup", True
            )),
            scheduled_refresh_enabled=bool(data.get(
                "scheduled_refresh_enabled", True
            )),
            silent_usage_sync_enabled=bool(data.get(
                "silent_usage_sync_enabled", True
            )),
            hide_taskbar_icon=bool(data.get("hide_taskbar_icon", False)),
        )

    # -- keyring helpers ------------------------------------------------

    def _get_api_key_from_keyring(self) -> str | None:
        """从系统凭据读取 API Key。"""
        try:
            import keyring
            return keyring.get_password(SERVICE_NAME, API_KEY_USERNAME)
        except Exception:
            return None

    def _set_api_key_to_keyring(self, api_key: str) -> bool:
        """尝试把 API Key 写入系统凭据。"""
        try:
            import keyring
            keyring.set_password(SERVICE_NAME, API_KEY_USERNAME, api_key)
            return True
        except Exception:
            return False

    def _clear_api_key_from_keyring(self) -> None:
        """从系统凭据删除 API Key。"""
        try:
            import keyring
            keyring.delete_password(SERVICE_NAME, API_KEY_USERNAME)
        except Exception:
            return


def main() -> None:
    """命令行测试入口。

    查看当前配置：
        python -m src.config_manager

    保存 API Key：
        python -m src.config_manager --set-api-key sk-xxxx
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="读取或保存 DeepSeek Monitor 配置"
    )
    parser.add_argument(
        "--set-api-key", help="保存 DeepSeek API Key"
    )
    args = parser.parse_args()

    manager = ConfigManager()

    if args.set_api_key:
        manager.set_api_key(args.set_api_key)
        print("API Key 已保存。")
        return

    config = manager.load()
    masked_key = manager.get_masked_api_key()

    print(f"配置文件路径：{CONFIG_FILE}")
    print(f"API Key：{masked_key}")
    print(f"API 地址：{config.api_base_url}")
    print(f"开机自启：{config.auto_start}")
    print(f"开机自启（新字段）：{config.autostart_enabled}")
    print(f"启动最小化到托盘：{config.start_minimized_to_tray}")
    print(f"启动自动刷新：{config.auto_refresh_on_startup}")
    print(f"定时刷新：{config.scheduled_refresh_enabled}")
    print(f"刷新间隔：{config.refresh_interval_minutes} 分钟")
    print(f"静默同步用量：{config.silent_usage_sync_enabled}")
    print(f"隐藏任务栏图标：{config.hide_taskbar_icon}")


def mask_api_key(api_key: str) -> str:
    """隐藏 API Key 中间部分，避免命令行输出泄露完整密钥。"""
    if not api_key:
        return "未设置"

    if len(api_key) <= 10:
        return "***"

    return f"{api_key[:3]}************{api_key[-4:]}"


if __name__ == "__main__":
    main()
