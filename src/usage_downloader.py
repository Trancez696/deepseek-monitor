"""DeepSeek Usage 导出文件下载模块。

只做两件事：
- headless=True 静默下载 Usage 导出文件。
- 用户触发时，headless=False 打开可见登录窗口保存浏览器会话。

不保存账号密码，不打印 Cookie，不读取 API Key。
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
    get_diagnostics_dir,
    get_exports_dir,
)
from src.sync_diagnostic import (
    BrowserMissingError as SyncBrowserMissingError,
    DownloadTimeoutError as SyncDownloadTimeoutError,
    ExportButtonNotFoundError as SyncExportButtonNotFoundError,
    NeedLoginError as SyncNeedLoginError,
    PageLoadTimeoutError as SyncPageLoadTimeoutError,
    SyncDiagnostic,
    UsageParseError,
    UsageSyncError,
    clear_phase_log,
    diagnose_sync_error,
    log_phase,
    save_diagnostic_info,
)

# 向后兼容：重新导出 workers.py / app.py 使用的旧异常名
class UsageDownloadError(Exception):
    """Usage 下载失败时抛出的基础错误。"""


class NeedLoginError(UsageDownloadError, SyncNeedLoginError):
    """需要用户登录 DeepSeek 后才能继续静默同步。"""


class BrowserNotInstalledError(UsageDownloadError, SyncBrowserMissingError):
    """Playwright Chromium 浏览器内核不可用。"""


class BrowserConnectionLostError(UsageDownloadError):
    """浏览器同步连接中断。"""


BROWSER_PROFILE_DIR = get_browser_profile_dir()
AUTH_STATE_PATH = get_auth_state_path()
EXPORT_DIR = get_exports_dir()
DIAGNOSTICS_DIR = get_diagnostics_dir()
USAGE_URL = "https://platform.deepseek.com/usage"
DOWNLOAD_TIMEOUT_MS = 60_000
PAGE_TIMEOUT_MS = 45_000
LOGIN_TIMEOUT_MS = 10 * 60 * 1000

# PyInstaller 打包后的 Playwright node.exe 路径
if getattr(sys, "frozen", False):
    _MEIPASS = Path(sys._MEIPASS)
    _node_exe = _MEIPASS / "playwright" / "driver" / "node.exe"
    if _node_exe.is_file():
        os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", str(_node_exe))
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
                Path(local_app_data) / "ms-playwright"
            )


# ---------------------------------------------------------------------------
# 公开函数
# ---------------------------------------------------------------------------

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
            return (
                "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，"
                "或在开发环境执行：python -m playwright install chromium"
            )
        return f"浏览器启动失败：{message}"


def download_usage_export_silent(month: str | None = None) -> str:
    """静默下载 DeepSeek Usage 导出文件（原接口，不输出诊断）。"""
    clear_phase_log()
    log_phase("sync_start", f"month={month or 'current'}")

    playwright = _load_playwright()
    log_phase("playwright_import", "OK")
    ensure_app_data_dirs()

    with playwright.sync_playwright() as p:
        browser_type = p.chromium
        browser = None
        context = None
        try:
            browser, context = _launch_silent_context(browser_type)
            log_phase("browser_launch", "OK")
            page = context.pages[0] if context.pages else context.new_page()
            _open_usage_page(page)
            log_phase("open_usage_page", "OK")

            log_phase("check_login_state")
            export_button = _find_export_button(page)
            if export_button is None:
                if _looks_like_login_required(page):
                    log_phase("sync_failed", "NEED_LOGIN")
                    raise NeedLoginError(
                        "需要登录 DeepSeek 后才能自动同步用量"
                    )
                log_phase("sync_failed", "EXPORT_BUTTON_NOT_FOUND")
                raise SyncExportButtonNotFoundError(
                    "在 DeepSeek Usage 页面上找不到导出按钮。"
                )

            log_phase("find_export_button", "found")
            log_phase("click_export_button")
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
                export_button.click()

            log_phase("wait_download", "downloading")
            download = download_info.value
            log_phase("save_download_file", download.suggested_filename or "")
            target_path = EXPORT_DIR / _safe_download_name(
                download.suggested_filename
            )
            download.save_as(target_path)

            log_phase("sync_success")
            return str(target_path)

        except NeedLoginError:
            raise
        except SyncExportButtonNotFoundError:
            raise
        except TimeoutError as error:
            log_phase("sync_failed", "DOWNLOAD_TIMEOUT")
            raise SyncDownloadTimeoutError(
                "下载超时，请稍后重试，或使用手动导入。"
            ) from error
        finally:
            _safe_close(context)
            _safe_close(browser)


def download_with_diagnostics(
    month: str | None = None,
) -> tuple[str | None, SyncDiagnostic]:
    """执行静默同步并捕获诊断信息，不抛出异常。

    Returns:
        (文件路径, SyncDiagnostic) — 失败时文件路径为 None
    """
    clear_phase_log()
    log_phase("sync_start", "diagnostic mode")

    # 浏览器可用性检查
    browser_check = check_playwright_browser_available()
    if browser_check:
        log_phase("sync_failed", "BROWSER_MISSING")
        diag = diagnose_sync_error(BrowserNotInstalledError(browser_check))
        save_diagnostic_info(diag, DIAGNOSTICS_DIR)
        return None, diag

    playwright = _load_playwright()
    ensure_app_data_dirs()
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)

    captured_img: bytes | None = None
    captured_html: str | None = None

    with playwright.sync_playwright() as p:
        browser = None
        context = None
        try:
            browser, context = _launch_silent_context(p.chromium)
            log_phase("browser_launch", "OK")
            page = context.pages[0] if context.pages else context.new_page()

            # 打开页面
            try:
                page.goto(USAGE_URL, wait_until="domcontentloaded",
                          timeout=PAGE_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
                log_phase("open_usage_page", "OK")
            except Exception as exc:
                log_phase("sync_failed", "PAGE_TIMEOUT")
                _safe_capture(page, captured_store := {"img": None, "html": None})
                diag = diagnose_sync_error(
                    SyncPageLoadTimeoutError(str(exc)), phase="open_usage_page"
                )
                save_diagnostic_info(diag, DIAGNOSTICS_DIR,
                                     captured_store["img"], captured_store["html"])
                return None, diag

            log_phase("check_login_state")
            export_button = _find_export_button(page)
            if export_button is None:
                cs = {"img": None, "html": None}
                _safe_capture(page, cs)
                if _looks_like_login_required(page):
                    log_phase("sync_failed", "NEED_LOGIN")
                    diag = SyncDiagnostic(
                        ok=False, code="NEED_LOGIN",
                        title="需要登录 DeepSeek",
                        message="自动同步无法访问 Usage 导出按钮，"
                        "登录状态已过期。",
                        suggestion="请点击「打开登录窗口」，"
                        "完成 DeepSeek 登录后再次刷新。",
                        phase="check_login_state",
                        technical_detail=(
                            f"Export button not found after "
                            f"{PAGE_TIMEOUT_MS / 1000}s. "
                            f"URL: {page.url}"
                        ),
                        can_retry=True, need_login=True, can_manual_import=True,
                    )
                else:
                    log_phase("sync_failed", "EXPORT_BUTTON_NOT_FOUND")
                    diag = diagnose_sync_error(
                        SyncExportButtonNotFoundError(
                            f"Export button not found. URL: {page.url}"
                        ),
                        phase="find_export_button",
                    )
                save_diagnostic_info(diag, DIAGNOSTICS_DIR,
                                     cs["img"], cs["html"])
                return None, diag

            log_phase("find_export_button", "found")
            log_phase("click_export_button")
            try:
                with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as dinfo:
                    export_button.click()
                log_phase("wait_download", "downloading")
                download = dinfo.value
                log_phase("save_download_file", download.suggested_filename or "")
                target_path = EXPORT_DIR / _safe_download_name(
                    download.suggested_filename
                )
                download.save_as(target_path)
                log_phase("sync_success")
                return str(target_path), SyncDiagnostic(
                    ok=True, code="SUCCESS", title="自动同步成功",
                    message="用量数据已成功同步。", suggestion="",
                    can_retry=False, need_login=False, can_manual_import=False,
                )
            except TimeoutError:
                log_phase("sync_failed", "DOWNLOAD_TIMEOUT")
                cs = {"img": None, "html": None}
                _safe_capture(page, cs)
                diag = diagnose_sync_error(
                    SyncDownloadTimeoutError("点击导出后未收到下载文件"),
                    phase="wait_download",
                )
                save_diagnostic_info(diag, DIAGNOSTICS_DIR, cs["img"], cs["html"])
                return None, diag

        except (BrowserNotInstalledError, SyncBrowserMissingError) as exc:
            log_phase("sync_failed", "BROWSER_MISSING")
            diag = diagnose_sync_error(exc)
            save_diagnostic_info(diag, DIAGNOSTICS_DIR)
            return None, diag

        except Exception as exc:
            log_phase("sync_failed", "UNKNOWN_ERROR")
            cs = {"img": None, "html": None}
            try:
                if context and context.pages:
                    _safe_capture(context.pages[0], cs)
            except Exception:
                pass
            diag = diagnose_sync_error(exc, phase="sync")
            save_diagnostic_info(diag, DIAGNOSTICS_DIR, cs["img"], cs["html"])
            return None, diag

        finally:
            _safe_close(context)
            _safe_close(browser)


def _safe_capture(page, store: dict) -> None:
    """尝试截取页面截图和 HTML。不影响主流程。"""
    try:
        store["img"] = page.screenshot(type="png", timeout=10_000)
    except Exception:
        pass
    try:
        store["html"] = page.content()
    except Exception:
        pass


def open_login_window() -> None:
    """打开可见浏览器窗口，让用户手动登录 DeepSeek。"""
    playwright = _load_playwright()
    ensure_app_data_dirs()

    with playwright.sync_playwright() as p:
        browser_type = p.chromium
        context = _launch_persistent_context(browser_type, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(USAGE_URL, wait_until="domcontentloaded",
                      timeout=PAGE_TIMEOUT_MS)
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


# ---------------------------------------------------------------------------
# 命令行诊断模式
# ---------------------------------------------------------------------------

def run_diagnose() -> None:
    """命令行诊断模式。python -m src.usage_downloader --diagnose"""
    print("=" * 56)
    print("  DeepSeek Monitor - 同步诊断工具")
    print("=" * 56)

    # 1. Playwright
    print("\n[1/6] Playwright 模块状态 ... ", end="", flush=True)
    try:
        from playwright import sync_api as _  # noqa
        print("OK")
    except ImportError:
        print("未安装")
        print("  -> 建议：执行 pip install playwright")
        return

    # 2. 浏览器
    print("[2/6] 浏览器可用性 ... ", end="", flush=True)
    check_result = check_playwright_browser_available()
    if check_result:
        print("失败")
        print(f"  -> {check_result}")
        print("  -> 建议：安装 Microsoft Edge 或 Google Chrome")
        return
    print("OK")

    # 3. 路径
    print("[3/6] 用户数据路径")
    print(f"  browser_profile: {BROWSER_PROFILE_DIR}")
    print(f"  exports:         {EXPORT_DIR}")
    print(f"  diagnostics:     {DIAGNOSTICS_DIR}")
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("  -> 目录已就绪")

    # 4-6. 打开页面检测
    print("[4/6] 打开 DeepSeek Usage 页面 ... ", end="", flush=True)
    ensure_app_data_dirs()
    playwright = _load_playwright()
    with playwright.sync_playwright() as p:
        try:
            browser = _launch_channel_browser(p.chromium, headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(USAGE_URL, wait_until="domcontentloaded",
                      timeout=PAGE_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
            print("OK")
            print(f"  当前 URL: {page.url}")
        except Exception as exc:
            print("失败")
            print(f"  -> {exc}")
            print("  -> 建议：检查网络连接和代理设置")
            _safe_close(context) if 'context' in dir() else None
            _safe_close(browser) if 'browser' in dir() else None
            return

        # 5. 登录
        print("[5/6] 检测登录状态 ... ", end="", flush=True)
        if _looks_like_login_required(page):
            print("未登录")
            print("  -> 建议：使用 --login 打开登录窗口完成登录")
        else:
            print("已登录")

        # 6. 导出按钮
        print("[6/6] 查找导出按钮 ... ", end="", flush=True)
        if _looks_like_login_required(page):
            print("跳过（未登录）")
        else:
            button = _find_export_button(page)
            if button:
                print("已找到")
                print(f"  按钮文本: {button.text_content()}")
            else:
                print("未找到")
                print("  -> 可能原因：页面结构变化或加载不完整")

        _safe_close(context)
        _safe_close(browser)

    print("\n" + "=" * 56)
    print("  诊断完成")
    print("=" * 56)


# ===========================================================================
# 内部辅助函数（原有逻辑保持不变）
# ===========================================================================

def _load_playwright():
    """延迟导入 Playwright。"""
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
            return browser_type.launch_persistent_context(
                channel=channel, **options
            )
        except Exception as error:
            errors.append(f"{channel}: {error}")
            continue
    try:
        return browser_type.launch_persistent_context(**options)
    except Exception as error:
        _raise_browser_error(error, errors)


def _launch_silent_context(browser_type):
    """启动静默同步用浏览器和上下文。"""
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


def _launch_channel_browser(browser_type, headless: bool):
    """按偏好顺序启动普通浏览器实例。"""
    errors: list[str] = []
    for channel in _preferred_browser_channels():
        try:
            return browser_type.launch(channel=channel, headless=headless)
        except Exception as error:
            errors.append(f"{channel}: {error}")
            continue
    try:
        return browser_type.launch(headless=headless)
    except Exception as error:
        _raise_browser_error(error, errors)


def _launch_temporary_browser(browser_type):
    """启动临时浏览器用于可用性检查。"""
    errors: list[str] = []
    for channel in _preferred_browser_channels():
        try:
            return browser_type.launch(channel=channel, headless=True)
        except Exception as error:
            errors.append(f"{channel}: {error}")
            continue
    try:
        return browser_type.launch(headless=True)
    except Exception as error:
        if errors:
            raise UsageDownloadError("；".join(errors[-2:])) from error
        raise


def _raise_browser_error(error: Exception, errors: list[str]) -> None:
    """统一处理浏览器启动失败。"""
    message = str(error)
    if "Executable doesn't exist" in message or "playwright install" in message:
        raise BrowserNotInstalledError(
            "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，"
            "或在开发环境执行：python -m playwright install chromium"
        ) from error
    detail = "；".join(errors[-2:]) if errors else message
    raise UsageDownloadError(f"启动浏览器失败：{detail}") from error


def _safe_close(target) -> None:
    if target is None:
        return
    try:
        target.close()
    except Exception:
        pass


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
    """登录成功后保存登录状态。"""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(AUTH_STATE_PATH))


def _open_usage_page(page) -> None:
    """打开 Usage 页面并等待基础加载完成。"""
    try:
        page.goto(USAGE_URL, wait_until="domcontentloaded",
                  timeout=PAGE_TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except Exception as error:
        raise SyncPageLoadTimeoutError(
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
        except Exception:
            continue
    return None


def _looks_like_login_required(page) -> bool:
    """判断当前页面是否需要登录。"""
    url = page.url.lower()
    if "login" in url or "signin" in url or "auth" in url:
        return True
    login_words = ["登录", "Log in", "Sign in", "邮箱", "密码"]
    for word in login_words:
        try:
            if page.locator(f"text={word}").count() > 0:
                return True
        except Exception:
            continue
    return False


def _wait_for_login(page) -> None:
    """等待用户登录到 Usage 页面。"""
    start_time = time.monotonic()
    while (time.monotonic() - start_time) * 1000 < LOGIN_TIMEOUT_MS:
        try:
            if _find_export_button(page) is not None:
                return
        except Exception:
            pass
        try:
            if not _looks_like_login_required(page):
                page.goto(USAGE_URL, wait_until="domcontentloaded",
                          timeout=PAGE_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
                if _find_export_button(page) is not None:
                    return
        except Exception:
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


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    """命令行测试入口。"""
    parser = argparse.ArgumentParser(
        description="DeepSeek Usage 静默下载/登录/诊断"
    )
    parser.add_argument("--silent", action="store_true",
                        help="静默下载 Usage 导出文件")
    parser.add_argument("--login", action="store_true",
                        help="打开可见登录窗口，保存浏览器会话")
    parser.add_argument("--clear-login", action="store_true",
                        help="清除本地浏览器登录状态")
    parser.add_argument("--diagnose", action="store_true",
                        help="运行诊断模式")
    args = parser.parse_args()

    try:
        if args.diagnose:
            run_diagnose()
            return
        if args.clear_login:
            clear_browser_profile()
            print("已清除 DeepSeek 登录状态。")
            return
        if args.login:
            open_login_window()
            print("登录窗口已关闭，浏览器会话已保存。")
            return
        if args.silent:
            fp = download_usage_export_silent()
            print(f"下载成功：{fp}")
            return
        parser.print_help()
    except NeedLoginError as error:
        print(f"需要登录：{error}")
    except UsageDownloadError as error:
        print(f"下载失败：{error}")


if __name__ == "__main__":
    main()
