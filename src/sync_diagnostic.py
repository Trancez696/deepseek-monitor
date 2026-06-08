"""自动同步诊断模块。

统一管理同步失败时的诊断信息、异常映射和诊断文件保存。
所有用户可见提示使用中文，不泄露 Cookie / API Key。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 细粒度异常类型
# ---------------------------------------------------------------------------
class UsageSyncError(Exception):
    """同步相关的基础异常。"""


class NeedLoginError(UsageSyncError):
    """需要用户登录 DeepSeek。"""


class BrowserMissingError(UsageSyncError):
    """浏览器内核缺失（Chrome/Edge/Playwright Chromium 都未找到）。"""


class PageLoadTimeoutError(UsageSyncError):
    """DeepSeek Usage 页面加载超时。"""


class ExportButtonNotFoundError(UsageSyncError):
    """页面上找不到导出按钮（结构变化或未登录）。"""


class DownloadTimeoutError(UsageSyncError):
    """点击导出后未收到下载文件。"""


class DownloadFileInvalidError(UsageSyncError):
    """下载的文件不存在或为空。"""


class UsageParseError(UsageSyncError):
    """ZIP/CSV 解析失败。"""


class UsageNoDataError(UsageSyncError):
    """Usage 页面显示暂无数据。"""


class PermissionError_OS(UsageSyncError):
    """文件/权限写入失败。"""


class BrowserConnectionLostError(UsageSyncError):
    """浏览器同步连接中断。"""


# ---------------------------------------------------------------------------
# 诊断数据结构
# ---------------------------------------------------------------------------
SYNC_PHASES = [
    "sync_start",
    "playwright_import",
    "browser_launch",
    "open_usage_page",
    "check_login_state",
    "find_export_button",
    "click_export_button",
    "wait_download",
    "save_download_file",
    "parse_usage_file",
    "update_ui",
    "sync_success",
    "sync_failed",
]


@dataclass
class SyncDiagnostic:
    """一次自动同步的诊断结果。"""

    ok: bool
    code: str
    title: str
    message: str
    suggestion: str
    phase: str = ""
    technical_detail: str = ""
    can_retry: bool = True
    need_login: bool = False
    can_manual_import: bool = True
    screenshot_path: str | None = None
    html_path: str | None = None
    downloaded_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转为字典，用于保存诊断 JSON，不包含敏感信息。"""
        return {
            "ok": self.ok,
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
            "phase": self.phase,
            "technical_detail": self.technical_detail,
            "can_retry": self.can_retry,
            "need_login": self.need_login,
            "can_manual_import": self.can_manual_import,
            "screenshot_path": self.screenshot_path,
            "html_path": self.html_path,
            "downloaded_file": self.downloaded_file,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }


# ---------------------------------------------------------------------------
# 同步阶段日志（线程安全单次记录）
# ---------------------------------------------------------------------------
_sync_phase_log: list[str] = []


def clear_phase_log() -> None:
    """清除阶段日志。每次同步开始时调用。"""
    _sync_phase_log.clear()


def log_phase(phase: str, detail: str = "") -> None:
    """记录一个同步阶段。"""
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {phase}" + (f": {detail}" if detail else "")
    _sync_phase_log.append(entry)


def get_phase_log() -> list[str]:
    """返回当前同步的阶段日志副本。"""
    return list(_sync_phase_log)


# ---------------------------------------------------------------------------
# 异常→诊断 映射
# ---------------------------------------------------------------------------
def diagnose_sync_error(error: Exception, phase: str = "") -> SyncDiagnostic:
    """把一个异常映射为结构化的 SyncDiagnostic。

    这是 UI 层获取诊断信息的唯一入口，不直接判断底层异常类型。
    """
    # 浏览器缺失
    if isinstance(error, BrowserMissingError):
        return SyncDiagnostic(
            ok=False,
            code="BROWSER_MISSING",
            title="自动同步组件未安装",
            message="自动同步所需的浏览器内核缺失。"
            "请安装 Microsoft Edge / Google Chrome，或使用最新版安装包。",
            suggestion="安装 Microsoft Edge 或 Google Chrome，"
            "或从官网下载最新版打包程序。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 需要登录
    if isinstance(error, NeedLoginError):
        return SyncDiagnostic(
            ok=False,
            code="NEED_LOGIN",
            title="需要登录 DeepSeek",
            message="自动同步无法继续，因为 DeepSeek 登录状态已过期或未登录。",
            suggestion="请点击「打开登录窗口」，"
            "在弹出浏览器中完成 DeepSeek 登录后再点击刷新。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=True,
            can_manual_import=True,
        )

    # 页面加载超时
    if isinstance(error, PageLoadTimeoutError):
        return SyncDiagnostic(
            ok=False,
            code="PAGE_TIMEOUT",
            title="DeepSeek Usage 页面加载超时",
            message="自动同步无法打开 DeepSeek Usage 页面。"
            "可能是网络连接不稳定或代理配置问题。",
            suggestion="请检查网络连接和代理设置，然后重试。"
            "也可以手动从 DeepSeek Usage 页面导出 ZIP/CSV 后导入。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 找不到导出按钮
    if isinstance(error, ExportButtonNotFoundError):
        return SyncDiagnostic(
            ok=False,
            code="EXPORT_BUTTON_NOT_FOUND",
            title="DeepSeek Usage 页面结构可能已变化",
            message="自动同步无法在 Usage 页面找到导出按钮。"
            "可能是 DeepSeek 更新了页面布局，或者网络加载不完整。",
            suggestion="请尝试手动从 DeepSeek Usage 页面导出 ZIP/CSV 后导入。"
            "如果问题持续，请更新软件版本。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 下载超时
    if isinstance(error, DownloadTimeoutError):
        return SyncDiagnostic(
            ok=False,
            code="DOWNLOAD_TIMEOUT",
            title="导出文件下载超时",
            message="点击导出按钮后，程序未能在规定时间内收到下载文件。"
            "可能是网络较慢或页面响应异常。",
            suggestion="请稍后重试，或手动从 DeepSeek Usage 页面导出 ZIP/CSV 后导入。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 下载文件无效
    if isinstance(error, DownloadFileInvalidError):
        return SyncDiagnostic(
            ok=False,
            code="DOWNLOAD_FILE_INVALID",
            title="下载的用量文件无效",
            message="自动同步下载的文件不存在或内容为空。",
            suggestion="请尝试重新同步。"
            "如果仍然失败，请手动导出后导入。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 解析失败
    if isinstance(error, UsageParseError):
        return SyncDiagnostic(
            ok=False,
            code="PARSE_FAILED",
            title="用量文件解析失败",
            message="下载的 Usage 文件无法被识别为有效的 DeepSeek 用量数据。",
            suggestion="请确认下载的文件为 DeepSeek Usage 页面官方导出的 ZIP/CSV 格式。"
            "也可以手动导出后导入。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 暂无数据
    if isinstance(error, UsageNoDataError):
        return SyncDiagnostic(
            ok=False,
            code="NO_USAGE_DATA",
            title="当前月份没有用量数据",
            message="DeepSeek Usage 页面显示当前月份暂无消费记录。",
            suggestion="如果确认有 API 调用记录，请检查 DeepSeek Usage 页面"
            "是否选择了正确的月份。",
            phase=phase,
            technical_detail=str(error),
            can_retry=False,
            need_login=False,
            can_manual_import=False,
        )

    # 权限问题
    if isinstance(error, PermissionError_OS):
        return SyncDiagnostic(
            ok=False,
            code="PERMISSION_ERROR",
            title="文件操作权限不足",
            message="无法保存下载文件或诊断数据。",
            suggestion="请检查 %LOCALAPPDATA%\\DeepSeek Monitor\\"
            "目录的读写权限，或使用系统盘以外的路径。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=False,
        )

    # 浏览器连接中断
    if isinstance(error, BrowserConnectionLostError):
        return SyncDiagnostic(
            ok=False,
            code="BROWSER_CONNECTION_LOST",
            title="浏览器同步连接中断",
            message="自动同步过程中浏览器意外断开连接。"
            "可能是网络波动或浏览器进程被系统关闭。",
            suggestion="请检查系统资源占用情况，然后重试。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 通用 UsageDownloadError
    if isinstance(error, UsageSyncError):
        return SyncDiagnostic(
            ok=False,
            code="SYNC_FAILED",
            title="自动同步失败",
            message=str(error) or "自动同步过程中出现错误。",
            suggestion="可以稍后重试，或手动从 DeepSeek Usage 页面导出 ZIP/CSV 后导入。"
            "如果问题持续，请查看日志获取更多信息。",
            phase=phase,
            technical_detail=str(error),
            can_retry=True,
            need_login=False,
            can_manual_import=True,
        )

    # 兜底：未知异常
    return SyncDiagnostic(
        ok=False,
        code="UNKNOWN_ERROR",
        title="自动同步失败，原因未知",
        message="自动同步过程中出现未预期的错误。",
        suggestion="请查看日志文件获取详细信息，或使用手动导入功能。"
        "如果问题持续，请向开发者反馈。",
        phase=phase,
        technical_detail=f"{type(error).__name__}: {error}",
        can_retry=True,
        need_login=False,
        can_manual_import=True,
    )


# ---------------------------------------------------------------------------
# 保存诊断文件
# ---------------------------------------------------------------------------
def save_diagnostic_info(
    diagnostic: SyncDiagnostic,
    diagnostics_dir: Path,
    screenshot_bytes: bytes | None = None,
    html_content: str | None = None,
) -> SyncDiagnostic:
    """保存诊断信息到文件，返回更新后的 diagnostic（含文件路径）。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 保存截图
    if screenshot_bytes:
        try:
            screenshot_path = diagnostics_dir / f"sync_failed_{timestamp}.png"
            screenshot_path.write_bytes(screenshot_bytes)
            diagnostic.screenshot_path = str(screenshot_path)
        except OSError:
            pass

    # 保存 HTML（可能包含页面内容，不包含 Cookie/密码）
    if html_content:
        try:
            html_path = diagnostics_dir / f"sync_failed_{timestamp}.html"
            html_path.write_text(html_content, encoding="utf-8")
            diagnostic.html_path = str(html_path)
        except OSError:
            pass

    # 保存诊断 JSON
    try:
        json_path = diagnostics_dir / f"sync_failed_{timestamp}.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(diagnostic.to_dict(), f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return diagnostic
