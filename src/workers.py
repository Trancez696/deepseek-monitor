"""后台任务线程。

把耗时操作放到 QThread，避免阻塞 PySide6 主界面。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.api_client import DeepSeekApiClient, DeepSeekApiError
from src.usage_downloader import (
    BrowserNotInstalledError,
    NeedLoginError,
    UsageDownloadError,
    download_usage_export_silent,
    open_login_window,
)
from src.usage_importer import UsageImportError, import_usage_file


class BalanceRefreshWorker(QThread):
    """后台刷新账户余额。"""

    success = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, api_key: str, base_url: str) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url

    def run(self) -> None:
        """执行余额查询。"""
        try:
            self.progress.emit("正在刷新余额...")
            client = DeepSeekApiClient(api_key=self.api_key, base_url=self.base_url)
            result = client.get_balance()
        except DeepSeekApiError as error:
            self.failed.emit(str(error))
            return

        self.success.emit(result)


class UsageSilentSyncWorker(QThread):
    """后台静默下载并解析 Usage 导出文件。"""

    success = Signal(dict)
    failed = Signal(str)
    need_login = Signal(str)
    browser_not_installed = Signal(str)
    progress = Signal(str)

    def run(self) -> None:
        """执行静默同步。"""
        try:
            self.progress.emit("正在后台同步用量...")
            file_path = download_usage_export_silent()
            self.progress.emit("正在解析用量文件...")
            stats = import_usage_file(file_path)
        except NeedLoginError as error:
            self.need_login.emit(str(error))
            return
        except BrowserNotInstalledError as error:
            self.browser_not_installed.emit(str(error))
            return
        except UsageImportError as error:
            self.failed.emit(f"导入解析失败：{error}")
            return
        except UsageDownloadError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            message = str(error)
            if "Browser.close" in message or "Connection closed" in message:
                self.failed.emit("自动同步失败：浏览器同步连接中断，可重试或手动导入")
                return
            self.failed.emit(f"自动同步失败：{message}")
            return

        self.success.emit(stats)


class LoginWindowWorker(QThread):
    """打开可见登录窗口的后台线程。"""

    success = Signal()
    failed = Signal(str)
    browser_not_installed = Signal(str)
    progress = Signal(str)

    def run(self) -> None:
        """打开登录窗口并等待用户登录。"""
        try:
            self.progress.emit("请在打开的窗口中登录 DeepSeek...")
            open_login_window()
        except BrowserNotInstalledError as error:
            self.browser_not_installed.emit(str(error))
            return
        except UsageDownloadError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            self.failed.emit(f"登录窗口打开失败：{error}")
            return

        self.success.emit()
