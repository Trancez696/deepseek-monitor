"""DeepSeek Usage 导出文件下载模块。

只做两件事：
- headless=True 静默下载 Usage 导出文件。
- 用户触发时，headless=False 打开可见登录窗口保存浏览器会话。

不保存账号密码，不打印 Cookie，不读取 API Key。

浏览器内核位置：
- 优先使用系统默认浏览器对应的 Edge/Chrome。
- 如果默认浏览器不是 Chromium 系浏览器，再尝试系统 Edge/Chrome。
- 如果系统没有可控浏览器，再使用 Playwright Chromium。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from src.app_data import (
    ensure_app_data_dirs,
    get_auth_state_path,
    get_browser_profile_dir,
    get_exports_dir,
)

# ---------------------------------------------------------------------------
# PyInstaller 打包后的 Playwright node.exe 路径（与运行时 hook 互为兜底）
#
# 只设置 PLAYWRIGHT_NODEJS_PATH。
# 同时把 PLAYWRIGHT_BROWSERS_PATH 指向用户缓存，避免 PyInstaller frozen
# 环境默认寻找包内 .local-browsers，导致必须把 Chromium 打进 exe。
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _MEIPASS = Path(sys._MEIPASS)
    _node_exe = _MEIPASS / "playwright" / "driver" / "node.exe"
    if _node_exe.is_file():
        os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", str(_node_exe))
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(local_app_data) / "ms-playwright")

# ---------------------------------------------------------------------------

BROWSER_PROFILE_DIR = get_browser_profile_dir()
AUTH_STATE_PATH = get_auth_state_path()
EXPORT_DIR = get_exports_dir()
USAGE_URL = "https://platform.deepseek.com/usage"
DOWNLOAD_TIMEOUT_MS = 60_000
PAGE_TIMEOUT_MS = 45_000
LOGIN_TIMEOUT_MS = 10 * 60 * 1000


class UsageDownloadError(Exception):
    """Usage 下载失败时抛出的基础错误。"""


class NeedLoginError(UsageDownloadError):
    """需要用户登录 DeepSeek 后才能继续静默同步。"""


class BrowserNotInstalledError(UsageDownloadError):
    """Playwright Chromium 浏览器内核不可用。"""


def check_playwright_browser_available() -> str | None:
    """检查 Playwright 可控浏览器是否可用。返回 None 表示可用。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright 模块未安装，无法使用自动同步功能"

    try:
        with sync_playwright() as playwright:
            browser = _launch_temporary_browser(playwright.chromium)
            _safe_close(browser)
            return None
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            return "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，或执行：python -m playwright install chromium"
        return f"浏览器启动失败：{message}"


def download_usage_export_silent(month: str | None = None) -> str:
    """静默下载 DeepSeek Usage 导出文件。

    使用 headless=True。未登录时抛 NeedLoginError。
    成功后返回下载文件路径。
    """
    playwright = _load_playwright()
    ensure_app_data_dirs()

    with playwright.sync_playwright() as p:
        browser_type = p.chromium
        browser = None
        context = None
        try:
            browser, context = _launch_silent_context(browser_type)
            page = context.pages[0] if context.pages else context.new_page()
            _open_usage_page(page)

            export_button = _find_export_button(page)
            if export_button is None:
                if _looks_like_login_required(page):
                    raise NeedLoginError("需要登录 DeepSeek 后才能自动同步用量")
                raise UsageDownloadError(
                    "找不到 Usage 页面导出按钮，可能是页面结构变化或网络加载失败。"
                )

            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
                export_button.click()

            download = download_info.value
            target_path = EXPORT_DIR / _safe_download_name(download.suggested_filename)
            download.save_as(target_path)
            return str(target_path)
        except NeedLoginError:
            raise
        except TimeoutError as error:
            raise UsageDownloadError("下载超时，请稍后重试，或使用手动导入。") from error
        finally:
            _safe_close(context)
            _safe_close(browser)


def open_login_window() -> None:
    """打开可见浏览器窗口，让用户手动登录 DeepSeek。

    登录成功后浏览器会话保存到 %LOCALAPPDATA%\\DeepSeek Monitor\\browser_profile\\。
    程序不保存账号密码。
    """
    playwright = _load_playwright()
    ensure_app_data_dirs()

    with playwright.sync_playwright() as p:
        browser_type = p.chromium
        context = _launch_persistent_context(browser_type, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.bring_to_front()
            _wait_for_login(page)
            _save_auth_state(context)
        finally:
            _safe_close(context)


def clear_browser_profile() -> None:
    """清除浏览器登录状态。"""
    if BROWSER_PROFILE_DIR.exists():
        shutil.rmtree(BROWSER_PROFILE_DIR)
    if AUTH_STATE_PATH.exists():
        AUTH_STATE_PATH.unlink()


def _load_playwright():
    """延迟导入 Playwright，便于给出清楚错误提示。"""
    try:
        from playwright import sync_api
    except ImportError as error:
        raise UsageDownloadError(
            "未安装 Playwright，请先执行：pip install playwright"
        ) from error

    return sync_api


def _launch_persistent_context(browser_type, headless: bool):
    """启动持久化浏览器上下文。"""
    options = {
        "user_data_dir": str(BROWSER_PROFILE_DIR),
        "accept_downloads": True,
        "downloads_path": str(EXPORT_DIR),
        "headless": headless,
        "viewport": {"width": 1280, "height": 900},
    }

    errors: list[str] = []
    for channel in _preferred_browser_channels():
        try:
            return browser_type.launch_persistent_context(channel=channel, **options)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{channel}: {error}")
            continue

    try:
        return browser_type.launch_persistent_context(**options)
    except Exception as error:  # noqa: BLE001
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise BrowserNotInstalledError(
                "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，"
                "或在开发环境执行：python -m playwright install chromium"
            ) from error
        detail = "；".join(errors[-2:]) if errors else message
        raise UsageDownloadError(f"启动浏览器失败：{detail}") from error


def _launch_silent_context(browser_type):
    """启动静默同步用浏览器和上下文，优先加载已保存登录状态。"""
    browser = _launch_channel_browser(browser_type, headless=True)
    options = {
        "accept_downloads": True,
        "viewport": {"width": 1280, "height": 900},
    }
    if AUTH_STATE_PATH.exists():
        options["storage_state"] = str(AUTH_STATE_PATH)

    try:
        context = browser.new_context(**options)
    except Exception:
        _safe_close(browser)
        raise

    return browser, context


def _safe_close(target) -> None:
    """关闭 Playwright 对象，忽略驱动已断开的收尾异常。"""
    if target is None:
        return

    try:
        target.close()
    except Exception:  # noqa: BLE001
        pass


def _launch_channel_browser(browser_type, headless: bool):
    """按偏好顺序启动普通浏览器实例。"""
    errors: list[str] = []
    for channel in _preferred_browser_channels():
        try:
            return browser_type.launch(channel=channel, headless=headless)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{channel}: {error}")
            continue

    try:
        return browser_type.launch(headless=headless)
    except Exception as error:
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise BrowserNotInstalledError(
                "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，"
                "或在开发环境执行：python -m playwright install chromium"
            ) from error
        detail = "；".join(errors[-2:]) if errors else message
        raise UsageDownloadError(f"启动浏览器失败：{detail}") from error


def _launch_temporary_browser(browser_type):
    """按偏好顺序启动一个临时浏览器，用于可用性检查。"""
    errors: list[str] = []
    for channel in _preferred_browser_channels():
        try:
            return browser_type.launch(channel=channel, headless=True)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{channel}: {error}")
            continue

    try:
        return browser_type.launch(headless=True)
    except Exception as error:
        if errors:
            raise UsageDownloadError("；".join(errors[-2:])) from error
        raise


def _preferred_browser_channels() -> list[str]:
    """根据 Windows 默认浏览器返回 Playwright channel 优先级。"""
    default_channel = _detect_windows_default_browser_channel()
    channels: list[str] = []

    if default_channel:
        channels.append(default_channel)

    for channel in ("msedge", "chrome"):
        if channel not in channels:
            channels.append(channel)

    return channels


def _detect_windows_default_browser_channel() -> str | None:
    """识别 Windows 默认浏览器是否是 Edge 或 Chrome。"""
    if os.name != "nt":
        return None

    try:
        import winreg

        key_path = (
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\https\UserChoice"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return None

    prog_id = str(prog_id).lower()
    if "microsoftedge" in prog_id or "mseedge" in prog_id or "msedge" in prog_id:
        return "msedge"
    if "chrome" in prog_id:
        return "chrome"

    return None


def _save_auth_state(context) -> None:
    """登录成功后保存 Cookie/localStorage 登录状态。"""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(AUTH_STATE_PATH))


def _open_usage_page(page) -> None:
    """打开 Usage 页面并等待基础加载完成。"""
    try:
        page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except Exception as error:  # noqa: BLE001
        raise UsageDownloadError(
            "访问 DeepSeek Usage 页面超时或网络失败。"
        ) from error


def _find_export_button(page):
    """查找 Usage 页面上的导出按钮。"""
    candidates = [
        page.get_by_role("button", name="导出"),
        page.get_by_role("button", name="Export"),
        page.locator("button:has-text('导出')"),
        page.locator("button:has-text('Export')"),
        page.locator("text=导出"),
        page.locator("text=Export"),
    ]

    for locator in candidates:
        try:
            if locator.count() > 0:
                first = locator.first
                first.wait_for(state="visible", timeout=5_000)
                return first
        except Exception:  # noqa: BLE001
            continue

    return None


def _looks_like_login_required(page) -> bool:
    """粗略判断当前页面是否需要登录。"""
    url = page.url.lower()
    if "login" in url or "signin" in url or "auth" in url:
        return True

    login_words = ["登录", "Log in", "Sign in", "邮箱", "密码"]
    for word in login_words:
        try:
            if page.locator(f"text={word}").count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue

    return False


def _wait_for_login(page) -> None:
    """等待用户登录到 Usage 页面。

    不反复刷新页面，以免打断用户输入。
    """
    start_time = time.monotonic()
    while (time.monotonic() - start_time) * 1000 < LOGIN_TIMEOUT_MS:
        try:
            if _find_export_button(page) is not None:
                return
        except Exception:  # noqa: BLE001
            pass

        try:
            if not _looks_like_login_required(page):
                page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
                if _find_export_button(page) is not None:
                    return
        except Exception:  # noqa: BLE001
            pass

        page.wait_for_timeout(2_000)

    raise UsageDownloadError(
        "登录等待超时。请重新点击「打开登录窗口」后登录。"
    )


def _safe_download_name(suggested_name: str) -> str:
    """生成不覆盖旧文件的下载文件名。"""
    name = suggested_name or "deepseek_usage_export.zip"
    stem = Path(name).stem
    suffix = Path(name).suffix or ".zip"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{timestamp}{suffix}"


def main() -> None:
    """命令行测试入口。"""
    parser = argparse.ArgumentParser(
        description="DeepSeek Usage 静默下载/登录测试"
    )
    parser.add_argument(
        "--silent", action="store_true",
        help="headless=True 静默下载 Usage 导出文件",
    )
    parser.add_argument(
        "--login", action="store_true",
        help="打开可见登录窗口，保存浏览器会话",
    )
    parser.add_argument(
        "--clear-login", action="store_true",
        help="清除本地浏览器登录状态",
    )
    args = parser.parse_args()

    try:
        if args.clear_login:
            clear_browser_profile()
            print("已清除 DeepSeek 登录状态。")
            return

        if args.login:
            open_login_window()
            print("登录窗口已关闭，浏览器会话已保存。")
            return

        if args.silent:
            file_path = download_usage_export_silent()
            print(f"下载成功：{file_path}")
            return

        parser.print_help()
    except NeedLoginError as error:
        print(f"需要登录：{error}")
    except UsageDownloadError as error:
        print(f"下载失败：{error}")


if __name__ == "__main__":
    main()
