"""后台任务线程。

把耗时操作放到 QThread，避免阻塞 PySide6 主界面。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.api_client import DeepSeekApiClient, DeepSeekApiError
from src.sync_diagnostic import SyncDiagnostic, diagnose_sync_error
from src.usage_downloader import (
    BrowserNotInstalledError,
    download_with_diagnostics,
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
    diagnostic = Signal(object)  # SyncDiagnostic
    progress = Signal(str)

    def run(self) -> None:
        """执行静默同步。"""
        self.progress.emit("正在后台同步用量...")

        file_path, diag = download_with_diagnostics()
        self.diagnostic.emit(diag)

        if not diag.ok:
            if diag.need_login:
                self.need_login.emit(diag.suggestion)
                return
            if diag.code == "BROWSER_MISSING":
                self.browser_not_installed.emit(diag.message)
                return
            self.failed.emit(diag.message)
            return

        # 下载成功，解析文件
        if not file_path:
            self.failed.emit("同步未返回文件路径")
            return

        self.progress.emit("正在解析用量文件...")
        try:
            stats = import_usage_file(file_path)
        except UsageImportError as error:
            diag = diagnose_sync_error(error, phase="parse_usage_file")
            self.diagnostic.emit(diag)
            self.failed.emit(f"导入解析失败：{error}")
            return
        except Exception as error:
            self.failed.emit(f"解析失败：{error}")
            return

        self.success.emit(stats)


class LoginWindowWorker(QThread):
    """打开可见登录窗口的后台线程。"""

    success = Signal()
    failed = Signal(str)
    browser_not_installed = Signal(str)
    diagnostic = Signal(object)
    progress = Signal(str)

    def run(self) -> None:
        """打开登录窗口并等待用户登录。"""
        try:
            self.progress.emit("请在打开的窗口中登录 DeepSeek...")
            open_login_window()
        except BrowserNotInstalledError as error:
            diag = diagnose_sync_error(error)
            self.diagnostic.emit(diag)
            self.browser_not_installed.emit(str(error))
            return
        except UsageDownloadError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:
            self.failed.emit(f"登录窗口打开失败：{error}")
            return
        self.success.emit()
