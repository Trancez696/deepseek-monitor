"""PySide6 主界面模块。

第四步先实现一个可运行的静态窗口。
后续步骤再接入 API、配置和 SQLite 数据库。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.tray import TrayManager

from src.app_data import get_diagnostics_dir, get_logs_dir
from src.api_client import BalanceResult
from src.autostart_manager import AutoStartError, AutoStartManager
from src.config_manager import ConfigManager
from src.database import UsageDatabase
from src.styles import APP_STYLE
from src.sync_diagnostic import SyncDiagnostic, get_phase_log
from src.usage_downloader import (
    BrowserConnectionLostError,
    BrowserNotInstalledError,
    check_playwright_browser_available,
    clear_browser_profile,
)
from src.usage_importer import UsageImportError, import_usage_file
from src.widgets import GlassCard, ModelUsageCard, StatCard, UsageBarChart, format_money
from src.workers import BalanceRefreshWorker, LoginWindowWorker, UsageSilentSyncWorker


LOW_BALANCE_WARNING = 5.0
CRITICAL_BALANCE_WARNING = 1.0


class SettingsDialog(QDialog):
    """设置窗口，保存 API Key 并预留常用选项。"""

    clear_usage_requested = Signal()
    clear_login_requested = Signal()
    clear_api_key_requested = Signal()

    def __init__(
        self,
        masked_api_key: str = "未设置",
        refresh_interval_minutes: int = 10,
        always_on_top: bool = False,
        warning_threshold: float = LOW_BALANCE_WARNING,
        auto_refresh_on_startup: bool = True,
        scheduled_refresh_enabled: bool = True,
        silent_usage_sync_enabled: bool = True,
        hide_taskbar_icon: bool = False,
        autostart_enabled: bool = False,
        start_minimized_to_tray: bool = False,
        startup_command: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        tip_label = QLabel("DeepSeek API Key")
        self.masked_api_key_label = QLabel(f"当前：{masked_api_key}")
        self.masked_api_key_label.setObjectName("mutedLabel")
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("留空则不修改 API Key")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

        refresh_label = QLabel("余额刷新间隔")
        self.refresh_interval_combo = QComboBox()
        self.refresh_interval_combo.addItems(["5分钟", "10分钟", "30分钟", "60分钟"])
        interval_text = f"{refresh_interval_minutes}分钟"
        if interval_text in [self.refresh_interval_combo.itemText(i) for i in range(self.refresh_interval_combo.count())]:
            self.refresh_interval_combo.setCurrentText(interval_text)

        self.always_on_top_checkbox = QCheckBox("窗口置顶")
        self.always_on_top_checkbox.setChecked(always_on_top)
        self.auto_refresh_checkbox = QCheckBox("启动后自动刷新")
        self.auto_refresh_checkbox.setChecked(auto_refresh_on_startup)
        self.scheduled_refresh_checkbox = QCheckBox("启用定时刷新")
        self.scheduled_refresh_checkbox.setChecked(scheduled_refresh_enabled)
        self.silent_usage_sync_checkbox = QCheckBox("刷新时自动静默同步 DeepSeek Usage")
        self.silent_usage_sync_checkbox.setChecked(silent_usage_sync_enabled)
        self.autostart_checkbox = QCheckBox("开机自启")
        self.autostart_checkbox.setChecked(autostart_enabled)
        command_tip = startup_command or "当前系统不支持开机自启"
        self.autostart_checkbox.setToolTip(f"当前启动命令：{command_tip}")
        self.start_minimized_checkbox = QCheckBox("启动后最小化到托盘")
        self.start_minimized_checkbox.setChecked(start_minimized_to_tray)
        self.hide_taskbar_checkbox = QCheckBox("隐藏任务栏图标，仅显示托盘图标")
        self.hide_taskbar_checkbox.setChecked(hide_taskbar_icon)

        warning_label = QLabel("余额预警阈值")
        self.warning_threshold_input = QDoubleSpinBox()
        self.warning_threshold_input.setRange(0.1, 9999.0)
        self.warning_threshold_input.setDecimals(2)
        self.warning_threshold_input.setPrefix("¥")
        self.warning_threshold_input.setValue(warning_threshold)

        clear_button = QPushButton("清除本地用量数据")
        clear_button.setObjectName("primaryButton")
        clear_button.clicked.connect(self._confirm_clear_usage)

        clear_api_button = QPushButton("清除 API Key")
        clear_api_button.setObjectName("primaryButton")
        clear_api_button.clicked.connect(self._confirm_clear_api_key)

        clear_login_button = QPushButton("清除 DeepSeek 登录状态")
        clear_login_button.setObjectName("primaryButton")
        clear_login_button.clicked.connect(self._confirm_clear_login)

        save_button = QPushButton("保存")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.accept)

        layout.addWidget(tip_label)
        layout.addWidget(self.masked_api_key_label)
        layout.addWidget(self.api_key_input)
        layout.addWidget(refresh_label)
        layout.addWidget(self.refresh_interval_combo)
        layout.addWidget(self.auto_refresh_checkbox)
        layout.addWidget(self.scheduled_refresh_checkbox)
        layout.addWidget(self.silent_usage_sync_checkbox)
        layout.addWidget(self.autostart_checkbox)
        layout.addWidget(self.start_minimized_checkbox)
        layout.addWidget(self.hide_taskbar_checkbox)
        layout.addWidget(self.always_on_top_checkbox)
        layout.addWidget(warning_label)
        layout.addWidget(self.warning_threshold_input)
        layout.addWidget(clear_api_button)
        layout.addWidget(clear_button)
        layout.addWidget(clear_login_button)
        layout.addWidget(save_button)

    def selected_refresh_interval(self) -> int:
        """返回用户选择的刷新分钟数。"""
        return int(self.refresh_interval_combo.currentText().replace("分钟", ""))

    def _confirm_clear_usage(self) -> None:
        """确认后通知主窗口清除本地用量数据。"""
        answer = QMessageBox.question(
            self,
            "清除本地用量数据",
            "确定要清除 usage.db 里的本地用量记录吗？\n这不会影响已导入文件本身。",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_usage_requested.emit()

    def _confirm_clear_api_key(self) -> None:
        """确认后通知主窗口清除 API Key。"""
        answer = QMessageBox.question(
            self,
            "清除 API Key",
            "确定要清除已保存的 DeepSeek API Key 吗？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_api_key_requested.emit()
            self.masked_api_key_label.setText("当前：未设置")
            self.api_key_input.clear()

    def _confirm_clear_login(self) -> None:
        """确认后通知主窗口清除浏览器登录状态。"""
        answer = QMessageBox.question(
            self,
            "清除 DeepSeek 登录状态",
            "确定要清除 %LOCALAPPDATA%\\DeepSeek Monitor\\browser_profile\\ "
            "中保存的登录会话吗？\n"
            "这不会删除账号密码，因为程序从不保存账号密码。",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_login_requested.emit()


class SyncDiagnosticDialog(QDialog):
    """同步诊断详情弹窗。"""

    open_login_requested = Signal()
    retry_sync_requested = Signal()
    manual_import_requested = Signal()

    def __init__(
        self,
        diagnostic: SyncDiagnostic,
        phase_log: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.diagnostic = diagnostic
        self.phase_log = phase_log or []
        self.setWindowTitle("同步诊断详情")
        self.setFixedSize(460, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题
        title_label = QLabel(diagnostic.title)
        title_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #ffffff;"
        )
        layout.addWidget(title_label)

        # 原因
        reason_label = QLabel(diagnostic.message)
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet("font-size: 13px; color: rgba(255,255,255,0.82);")
        layout.addWidget(reason_label)

        # 建议
        suggestion_label = QLabel(f"建议：{diagnostic.suggestion}")
        suggestion_label.setWordWrap(True)
        suggestion_label.setStyleSheet(
            "font-size: 13px; color: #4adebe; padding: 8px 0;"
        )
        layout.addWidget(suggestion_label)

        # 技术细节（可折叠）
        if diagnostic.technical_detail:
            detail_label = QLabel(f"技术细节：{diagnostic.technical_detail}")
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet(
                "font-size: 11px; color: rgba(255,255,255,0.50); "
                "padding: 8px; background: rgba(0,0,0,0.20); border-radius: 6px;"
            )
            layout.addWidget(detail_label)

        # 诊断文件路径
        diag_paths = []
        if diagnostic.screenshot_path:
            diag_paths.append(f"截图：{diagnostic.screenshot_path}")
        if diagnostic.html_path:
            diag_paths.append(f"HTML：{diagnostic.html_path}")
        if diag_paths:
            paths_text = "\n".join(diag_paths)
            paths_label = QLabel(paths_text)
            paths_label.setWordWrap(True)
            paths_label.setStyleSheet(
                "font-size: 11px; color: rgba(255,255,255,0.40);"
            )
            layout.addWidget(paths_label)

        # 阶段日志
        if self.phase_log:
            log_text = "同步日志：\n" + "\n".join(self.phase_log)
            log_label = QLabel(log_text)
            log_label.setWordWrap(True)
            log_label.setStyleSheet(
                "font-size: 11px; color: rgba(255,255,255,0.45); "
                "padding: 6px; background: rgba(0,0,0,0.15); border-radius: 4px;"
                "font-family: monospace;"
            )
            log_label.setMaximumHeight(100)
            layout.addWidget(log_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        if diagnostic.can_retry:
            retry_btn = QPushButton("重试同步")
            retry_btn.setObjectName("primaryButton")
            retry_btn.clicked.connect(self._on_retry)
            btn_layout.addWidget(retry_btn)

        if diagnostic.need_login:
            login_btn = QPushButton("打开登录窗口")
            login_btn.setObjectName("primaryButton")
            login_btn.clicked.connect(self._on_open_login)
            btn_layout.addWidget(login_btn)

        if diagnostic.can_manual_import:
            import_btn = QPushButton("手动导入")
            import_btn.setObjectName("primaryButton")
            import_btn.clicked.connect(self._on_manual_import)
            btn_layout.addWidget(import_btn)

        # 打开诊断文件夹
        if diagnostic.screenshot_path or diagnostic.html_path:
            open_diag_btn = QPushButton("打开诊断文件夹")
            open_diag_btn.setObjectName("primaryButton")
            open_diag_btn.clicked.connect(
                lambda: self._open_folder(str(get_diagnostics_dir()))
            )
            btn_layout.addWidget(open_diag_btn)

        # 打开日志
        open_log_btn = QPushButton("打开日志")
        open_log_btn.setObjectName("primaryButton")
        open_log_btn.clicked.connect(
            lambda: self._open_folder(str(get_logs_dir()))
        )
        btn_layout.addWidget(open_log_btn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _on_retry(self) -> None:
        self.retry_sync_requested.emit()
        self.accept()

    def _on_open_login(self) -> None:
        self.open_login_requested.emit()
        self.accept()

    def _on_manual_import(self) -> None:
        self.manual_import_requested.emit()
        self.accept()

    @staticmethod
    def _open_folder(path: str) -> None:
        """在文件管理器中打开目录。"""
        import subprocess
        subprocess.Popen(["explorer", path], shell=True)


class DeepSeekMonitorWindow(QMainWindow):
    """DeepSeek Monitor 主窗口。"""

    def __init__(self, startup: bool = False) -> None:
        super().__init__()
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.started_from_autostart = startup
        self.database = UsageDatabase()
        self.balance_worker: BalanceRefreshWorker | None = None
        self.usage_sync_worker: UsageSilentSyncWorker | None = None
        self.login_worker: LoginWindowWorker | None = None
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(lambda: self.refresh_all(trigger="scheduled"))
        self.is_refreshing = False
        self.active_refresh_tasks = 0
        self.refresh_had_error = False
        self.refresh_needs_login = False
        self.imported_usage_stats: dict | None = None
        self.last_balance_update_text = ""
        self.last_usage_update_text = ""
        self.last_sync_diagnostic: SyncDiagnostic | None = None
        self.tray_manager: TrayManager | None = None
        self._allow_exit = False

        self.setWindowTitle("DeepSeek Monitor")
        self._set_window_icon()
        self.setFixedSize(420, 860)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        if self.config.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_position = QPoint()
        self._build_ui()
        self._init_tray_manager()
        self.apply_taskbar_visibility()
        self.refresh_usage_data()
        self.setup_refresh_timer()

        if self.config.auto_refresh_on_startup:
            QTimer.singleShot(1500, lambda: self.refresh_all(trigger="startup"))

        self._startup_browser_check()
        if startup:
            self._write_app_log("Application started with --startup")

    def _set_window_icon(self) -> None:
        """设置窗口和任务栏图标。"""
        base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        icon_path = base_dir / "assets" / "icon.ico"
        if icon_path.exists():
            self.app_icon = QIcon(str(icon_path))
            self.setWindowIcon(self.app_icon)
        else:
            self.app_icon = QIcon()

    def _init_tray_manager(self) -> None:
        """创建系统托盘管理器。"""
        self.tray_manager = TrayManager(
            icon=self.app_icon,
            parent=self,
            on_show=self.show_window_from_tray,
            on_refresh=lambda: self.refresh_all(trigger="manual"),
            on_settings=self._open_settings,
            on_quit=self.exit_application,
        )

    def _build_ui(self) -> None:
        """创建窗口内的所有控件。"""
        root = QWidget()
        root.setObjectName("rootWidget")
        root.setStyleSheet(APP_STYLE)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(9)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        title_label = QLabel("DeepSeek Monitor")
        title_label.setObjectName("titleLabel")
        title_block.addWidget(title_label)

        self.import_button = self._create_icon_button("↓", "导入用量文件")
        self.refresh_button = self._create_icon_button("↻", "刷新")
        settings_button = self._create_icon_button("⚙", "设置")
        close_button = self._create_icon_button("×", "关闭")

        self.import_button.clicked.connect(self.import_usage_file)
        self.refresh_button.clicked.connect(lambda: self.refresh_all(trigger="manual"))
        settings_button.clicked.connect(self._open_settings)
        close_button.clicked.connect(self.close)

        header_layout.addLayout(title_block)
        header_layout.addStretch()
        header_layout.addWidget(self.import_button)
        header_layout.addWidget(self.refresh_button)
        header_layout.addWidget(settings_button)
        header_layout.addWidget(close_button)

        layout.addLayout(header_layout)
        layout.addWidget(self._create_balance_card())
        layout.addLayout(self._create_stat_row())
        self.flash_card = ModelUsageCard("V4 Flash", 0, 0, 0)
        self.pro_card = ModelUsageCard("V4 Pro", 0, 0, 0)
        layout.addWidget(self.flash_card)
        layout.addWidget(self.pro_card)
        layout.addWidget(self._create_chart_card())

    def _create_icon_button(self, text: str, tooltip: str) -> QPushButton:
        """创建右上角小按钮。"""
        button = QPushButton(text)
        button.setObjectName("iconButton")
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _create_balance_card(self) -> GlassCard:
        """创建账户余额主卡片。"""
        card = GlassCard()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(7)

        header_row = QHBoxLayout()
        subtitle_label = QLabel("账户余额")
        subtitle_label.setObjectName("mutedLabel")
        self.status_label = QLabel("等待配置")
        self.status_label.setObjectName("statusPill")
        header_row.addWidget(subtitle_label)
        header_row.addStretch()
        header_row.addWidget(self.status_label)

        self.balance_label = QLabel("¥ --.--")
        self.balance_label.setObjectName("balanceValue")

        self.detail_label = QLabel("充值 -- · 赠送 --")
        self.detail_label.setObjectName("mutedLabel")

        self.balance_warning_label = QLabel("")
        self.balance_warning_label.setObjectName("warningPill")
        self.balance_warning_label.hide()

        self.source_label = QLabel("实时余额 · 用量暂无导入数据")
        self.source_label.setObjectName("sourceLabel")
        self.source_label.setWordWrap(True)

        layout.addLayout(header_row)
        layout.addWidget(self.balance_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.balance_warning_label)
        layout.addWidget(self.source_label)

        return card

    def _create_stat_row(self) -> QHBoxLayout:
        """创建今日消耗和本月消耗卡片行。"""
        row = QHBoxLayout()
        row.setSpacing(12)
        self.today_card = StatCard("今日消耗", "¥0.00")
        self.month_card = StatCard("本月消耗", "¥0.00")
        row.addWidget(self.today_card)
        row.addWidget(self.month_card)
        return row

    def _create_chart_card(self) -> GlassCard:
        """创建最近 7 天趋势卡片。"""
        card = GlassCard("chartCard")
        card.setMinimumHeight(300)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(8)

        title_label = QLabel("最近 7 天消耗趋势")
        title_label.setObjectName("sectionValue")
        self.chart_meta_label = QLabel("数据月份：未导入 · 7日消费 ¥0.00")
        self.chart_meta_label.setObjectName("mutedLabel")
        self.sync_status_label = QLabel("自动同步：未开始")
        self.sync_status_label.setObjectName("mutedLabel")

        self.chart = UsageBarChart(
            values=[0.12, 0.20, 0.08, 0.34, 0.18, 0.28, 0.16],
            labels=["一", "二", "三", "四", "五", "六", "日"],
        )
        self.login_button = QPushButton("打开登录窗口")
        self.login_button.setObjectName("loginActionButton")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self.open_login_window)
        if self.config.silent_usage_sync_enabled:
            self.login_button.show()
        else:
            self.login_button.hide()

        self.diag_button = QPushButton("诊断详情")
        self.diag_button.setObjectName("loginActionButton")
        self.diag_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.diag_button.clicked.connect(self._show_sync_diagnostic)
        self.diag_button.hide()

        title_row = QHBoxLayout()
        title_row.addWidget(title_label)
        title_row.addStretch()
        title_row.addWidget(self.diag_button)
        title_row.addWidget(self.login_button)

        layout.addLayout(title_row)
        layout.addWidget(self.chart_meta_label)
        layout.addWidget(self.sync_status_label)
        layout.addWidget(self.chart)
        return card

    def setup_refresh_timer(self) -> None:
        """根据配置启动或停止定时刷新。"""
        if self.config.scheduled_refresh_enabled:
            interval_ms = self.config.refresh_interval_minutes * 60 * 1000
            self.refresh_timer.start(interval_ms)
        else:
            self.refresh_timer.stop()
        self._update_source_label()

    def restart_refresh_timer(self) -> None:
        """设置变更后重启定时刷新。"""
        self.config = self.config_manager.load()
        self.setup_refresh_timer()

    def _startup_browser_check(self) -> None:
        """启动时在后台检查 Playwright Chromium 是否可用。"""
        if not self.config.silent_usage_sync_enabled:
            return

        def check():
            error = check_playwright_browser_available()
            if error:
                self._set_sync_status(error)
                self.login_button.show()

        QTimer.singleShot(3000, check)

    def refresh_all(self, trigger: str = "manual") -> None:
        """统一刷新入口：手动、启动、定时都调用这里。"""
        if self.is_refreshing:
            if trigger == "scheduled":
                return
            self._set_sync_status("正在刷新，请稍候...")
            return

        self.is_refreshing = True
        self.active_refresh_tasks = 0
        self.refresh_had_error = False
        self.refresh_needs_login = False
        self.refresh_button.setText("…")
        self.refresh_button.setEnabled(False)

        status_text = {
            "manual": "正在刷新...",
            "startup": "启动后自动刷新中...",
            "scheduled": "定时刷新中...",
        }.get(trigger, "正在刷新...")
        self._set_sync_status(status_text)

        started_balance = self.refresh_balance_only()
        started_usage = False
        if self.config.silent_usage_sync_enabled:
            started_usage = self.sync_usage_silent()
        else:
            self._set_sync_status("已跳过用量静默同步")

        if not started_balance and not started_usage:
            self._finish_refresh_cycle()

    def refresh_balance_only(self) -> bool:
        """后台刷新余额。"""
        self.config = self.config_manager.load()
        api_key = self.config_manager.get_api_key()

        if not api_key:
            self.status_label.setText("未配置")
            self.refresh_had_error = True
            self._set_sync_status("请先在设置中填写 DeepSeek API Key")
            return False

        self.status_label.setText("查询中")

        self._begin_refresh_task()
        self.balance_worker = BalanceRefreshWorker(
            api_key=api_key,
            base_url=self.config.api_base_url,
        )
        self.balance_worker.success.connect(self._handle_balance_success)
        self.balance_worker.failed.connect(self._handle_balance_error)
        self.balance_worker.finished.connect(self._finish_balance_worker)
        self.balance_worker.start()
        return True

    def sync_usage_silent(self) -> bool:
        """启动后台静默同步 Usage 数据。"""
        if self.usage_sync_worker and self.usage_sync_worker.isRunning():
            self._set_sync_status("正在后台同步用量...")
            return False

        self._set_sync_status("正在后台同步用量...")

        self._begin_refresh_task()
        self.usage_sync_worker = UsageSilentSyncWorker(self)
        self.usage_sync_worker.progress.connect(self._set_sync_status)
        self.usage_sync_worker.success.connect(self._handle_usage_sync_success)
        self.usage_sync_worker.need_login.connect(self._handle_usage_sync_need_login)
        self.usage_sync_worker.browser_not_installed.connect(self._handle_browser_not_installed)
        self.usage_sync_worker.diagnostic.connect(self._handle_sync_diagnostic)
        self.usage_sync_worker.failed.connect(self._handle_usage_sync_failed)
        self.usage_sync_worker.finished.connect(self._finish_usage_sync_worker)
        self.usage_sync_worker.start()
        return True

    def refresh_usage_data(self) -> None:
        """从 SQLite 读取本地统计并更新界面。"""
        if self.imported_usage_stats:
            self._refresh_usage_from_import(self.imported_usage_stats)
            return

        today_cost = self.database.get_today_cost()
        month_cost = self.database.get_month_cost()

        self.today_card.set_value(format_money(today_cost))
        self.month_card.set_value(format_money(month_cost))

        summaries = {summary.model: summary for summary in self.database.get_model_summaries()}
        max_tokens = max((summary.total_tokens for summary in summaries.values()), default=1)

        flash_summary = summaries.get("V4 Flash")
        pro_summary = summaries.get("V4 Pro")

        self.flash_card.update_usage(
            tokens=flash_summary.total_tokens if flash_summary else 0,
            estimated_cost=flash_summary.estimated_cost if flash_summary else 0,
            progress=self._progress_from_tokens(flash_summary.total_tokens if flash_summary else 0, max_tokens),
        )
        self.pro_card.update_usage(
            tokens=pro_summary.total_tokens if pro_summary else 0,
            estimated_cost=pro_summary.estimated_cost if pro_summary else 0,
            progress=self._progress_from_tokens(pro_summary.total_tokens if pro_summary else 0, max_tokens),
        )

        chart_data = self.database.get_last_7_days_cost()
        total_cost = sum(cost for _, cost in chart_data)
        self.chart_meta_label.setText(f"数据月份：未导入 · 7日消费 {format_money(total_cost)}")
        self.chart.set_data(
            values=[cost for _, cost in chart_data],
            labels=[label for label, _ in chart_data],
            month_text="未导入",
            total_cost=total_cost,
        )
        self._update_source_label()

    def import_usage_file(self) -> None:
        """选择并导入 DeepSeek Usage 导出的 ZIP/CSV 文件。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 DeepSeek Usage 导出文件",
            "",
            "Usage 导出文件 (*.zip *.csv);;所有文件 (*.*)",
        )

        if not file_path:
            return

        try:
            self.imported_usage_stats = import_usage_file(file_path)
        except UsageImportError as error:
            QMessageBox.warning(self, "导入失败", str(error))
            return
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", f"解析文件时出现未知错误：{error}")
            return

        self.refresh_usage_data()
        self.last_usage_update_text = self._now_text()
        self._update_source_label()
        QMessageBox.information(
            self,
            "导入成功",
            "已导入 Usage 文件，界面现在优先显示导出文件中的真实用量数据。",
        )

    def open_login_window(self) -> None:
        """用户主动点击后打开可见登录窗口。"""
        if self.login_worker and self.login_worker.isRunning():
            self._set_sync_status("登录窗口已打开，请完成登录...")
            return

        self.login_button.setEnabled(False)
        self._set_sync_status("请在打开的窗口中登录 DeepSeek...")
        self.login_worker = LoginWindowWorker(self)
        self.login_worker.progress.connect(self._set_sync_status)
        self.login_worker.success.connect(self._handle_login_success)
        self.login_worker.browser_not_installed.connect(self._handle_browser_not_installed)
        self.login_worker.failed.connect(self._handle_login_failed)
        self.login_worker.finished.connect(self._finish_login_worker)
        self.login_worker.start()

    def _refresh_usage_from_import(self, stats: dict) -> None:
        """用导入文件的统计结果刷新界面。"""
        self.today_card.set_value(format_money(stats.get("today_cost", 0)))
        self.month_card.set_value(format_money(stats.get("month_cost", 0)))

        flash_stats = self._find_imported_model(stats, ["flash"])
        pro_stats = self._find_imported_model(stats, ["pro"])
        max_tokens = max(
            int(flash_stats.get("tokens", 0)),
            int(pro_stats.get("tokens", 0)),
            1,
        )

        self.flash_card.update_usage(
            tokens=int(flash_stats.get("tokens", 0)),
            estimated_cost=float(flash_stats.get("cost", 0)),
            progress=self._progress_from_tokens(int(flash_stats.get("tokens", 0)), max_tokens),
            requests=int(flash_stats.get("requests", 0)),
        )
        self.pro_card.update_usage(
            tokens=int(pro_stats.get("tokens", 0)),
            estimated_cost=float(pro_stats.get("cost", 0)),
            progress=self._progress_from_tokens(int(pro_stats.get("tokens", 0)), max_tokens),
            requests=int(pro_stats.get("requests", 0)),
        )

        daily_costs = stats.get("daily_costs", [])
        data_month = str(stats.get("data_month") or self._infer_month_from_daily_costs(daily_costs))
        seven_day_cost = sum(float(item.get("cost", 0)) for item in daily_costs)
        self.chart_meta_label.setText(f"数据月份：{data_month} · 7日消费 {format_money(seven_day_cost)}")
        self.chart.set_data(
            values=[float(item.get("cost", 0)) for item in daily_costs],
            labels=[self._short_date_label(str(item.get("date", ""))) for item in daily_costs],
            month_text=data_month,
            total_cost=seven_day_cost,
        )
        self._update_source_label()

    def _handle_usage_sync_success(self, stats: dict) -> None:
        """静默同步成功后刷新界面。"""
        self.imported_usage_stats = stats
        self.last_usage_update_text = self._now_text()
        self.refresh_usage_data()
        self._set_sync_status(f"用量已同步：{self.last_usage_update_text}")
        self.login_button.hide()

    def _handle_usage_sync_need_login(self, message: str) -> None:
        """静默同步发现需要登录。"""
        short_msg = message or "需要登录 DeepSeek 后才能自动同步用量"
        self._set_sync_status(short_msg)
        self.refresh_needs_login = True
        self.login_button.show()
        self.login_button.setEnabled(True)

    def _handle_usage_sync_failed(self, message: str) -> None:
        """静默同步失败后保留手动导入入口。"""
        short_msg = message or "自动同步失败，可手动导入"
        self._set_sync_status(short_msg)
        self.refresh_had_error = True
        self.login_button.show()
        self.sync_status_label.setToolTip(message)

    def _handle_browser_not_installed(self, message: str) -> None:
        """Playwright Chromium 浏览器未安装时给用户清晰指引。"""
        self.refresh_had_error = True
        self._set_sync_status(message or "Chromium 未安装，请安装后再试")
        self.login_button.show()
        self.login_button.setEnabled(True)
        self.refresh_needs_login = True

    def _handle_sync_diagnostic(self, diagnostic: SyncDiagnostic) -> None:
        """接收后台同步的诊断信息并保存。"""
        self.last_sync_diagnostic = diagnostic
        if not diagnostic.ok:
            self.diag_button.show()
        if diagnostic.downloaded_file:
            self._write_app_log(f"Sync diagnostic: {diagnostic.code}, "
                                f"downloaded={diagnostic.downloaded_file}")

    def _show_sync_diagnostic(self) -> None:
        """打开诊断详情弹窗。"""
        diagnostic = self.last_sync_diagnostic
        if diagnostic is None:
            QMessageBox.information(self, "诊断", "暂无诊断信息。")
            return

        dialog = SyncDiagnosticDialog(
            diagnostic=diagnostic,
            phase_log=get_phase_log(),
            parent=self,
        )
        dialog.open_login_requested.connect(self.open_login_window)
        dialog.retry_sync_requested.connect(lambda: self.refresh_all(trigger="manual"))
        dialog.manual_import_requested.connect(self.import_usage_file)
        dialog.exec()

    def _finish_usage_sync_worker(self) -> None:
        """清理静默同步线程状态。"""
        self.usage_sync_worker = None
        self._complete_refresh_task()

    def _handle_login_success(self) -> None:
        """登录窗口完成后提示用户重新刷新。"""
        self.login_button.hide()
        self._set_sync_status("登录状态已保存，请再次点击刷新同步用量")

    def _handle_login_failed(self, message: str) -> None:
        """登录窗口失败后显示状态。"""
        self.login_button.show()
        short_msg = message or "登录窗口打开失败，请检查网络或 Chromium 是否已安装"
        self._set_sync_status(short_msg)
        self.sync_status_label.setToolTip(message)

    def _finish_login_worker(self) -> None:
        """清理登录线程状态。"""
        self.login_button.setEnabled(True)
        self.login_worker = None

    def _set_sync_status(self, message: str) -> None:
        """更新 Usage 同步状态。"""
        self.sync_status_label.setText(message)

    def _begin_refresh_task(self) -> None:
        """记录一个后台刷新任务开始。"""
        self.active_refresh_tasks += 1

    def _complete_refresh_task(self) -> None:
        """记录一个后台刷新任务结束。"""
        self.active_refresh_tasks = max(0, self.active_refresh_tasks - 1)
        if self.active_refresh_tasks == 0:
            self._finish_refresh_cycle()

    def _finish_refresh_cycle(self) -> None:
        """恢复刷新按钮和刷新状态。"""
        self.is_refreshing = False
        self.refresh_button.setText("↻")
        self.refresh_button.setEnabled(True)
        if not self.refresh_had_error and not self.refresh_needs_login:
            self._set_sync_status(f"已更新：{self._now_text()}")

    def _find_imported_model(self, stats: dict, keywords: list[str]) -> dict:
        """从导入统计中按模型关键字汇总数据。"""
        result = {"tokens": 0, "cost": 0.0, "requests": 0}
        models = stats.get("models", {})

        for model_name, model_stats in models.items():
            compact_name = str(model_name).lower().replace("-", "").replace("_", "").replace(" ", "")
            if any(keyword in compact_name for keyword in keywords):
                result["tokens"] += int(model_stats.get("tokens", 0))
                result["cost"] += float(model_stats.get("cost", 0))
                result["requests"] += int(model_stats.get("requests", 0))

        return result

    def _short_date_label(self, value: str) -> str:
        """把 2026-06-08 转成 6/8，给柱状图使用。"""
        parts = value.split("-")
        if len(parts) == 3:
            return f"{int(parts[1])}/{int(parts[2])}"
        return value

    def _handle_balance_success(self, result: BalanceResult) -> None:
        """余额查询成功后更新界面。"""
        if not result.balance_infos:
            self.balance_label.setText("¥ --.--")
            self.status_label.setText("可用")
            self.detail_label.setText("充值 -- · 赠送 --")
            self._show_balance_warning(None)
            self.last_balance_update_text = self._now_text()
            self._update_source_label()
            return

        balance = result.balance_infos[0]
        status_text = "可用" if result.is_available else "不可用"
        total_balance = self._parse_money_value(balance.total_balance)

        self.balance_label.setText(format_money(total_balance))
        self.status_label.setText(status_text)
        self.detail_label.setText(
            f"充值 {format_money(balance.topped_up_balance)} · "
            f"赠送 {format_money(balance.granted_balance)}"
        )
        self._show_balance_warning(total_balance)
        self.last_balance_update_text = self._now_text()
        self._update_source_label()

    def _handle_balance_error(self, message: str) -> None:
        """余额查询失败后显示清楚提示。"""
        self.status_label.setText("查询失败")
        self.refresh_had_error = True
        self._set_sync_status(message or "刷新失败，可稍后重试")
        self.sync_status_label.setToolTip(message)

    def _finish_balance_worker(self) -> None:
        """清理余额线程引用。"""
        self.balance_worker = None
        self._complete_refresh_task()

    def _open_settings(self) -> None:
        """打开设置窗口。"""
        self.config = self.config_manager.load()
        autostart_enabled = AutoStartManager.is_enabled()
        self.config.autostart_enabled = autostart_enabled
        dialog = SettingsDialog(
            masked_api_key=self.config_manager.get_masked_api_key(),
            refresh_interval_minutes=self.config.refresh_interval_minutes,
            always_on_top=self.config.always_on_top,
            warning_threshold=self.config.balance_warning_yellow,
            auto_refresh_on_startup=self.config.auto_refresh_on_startup,
            scheduled_refresh_enabled=self.config.scheduled_refresh_enabled,
            silent_usage_sync_enabled=self.config.silent_usage_sync_enabled,
            hide_taskbar_icon=self.config.hide_taskbar_icon,
            autostart_enabled=autostart_enabled,
            start_minimized_to_tray=self.config.start_minimized_to_tray,
            startup_command=AutoStartManager.get_startup_command(),
            parent=self,
        )
        dialog.clear_usage_requested.connect(self._clear_local_usage_data)
        dialog.clear_login_requested.connect(self._clear_deepseek_login_state)
        dialog.clear_api_key_requested.connect(self._clear_saved_api_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            api_key = dialog.api_key_input.text().strip()
            if api_key:
                self.config_manager.set_api_key(api_key)
            self.config.refresh_interval_minutes = dialog.selected_refresh_interval()
            self.config.always_on_top = dialog.always_on_top_checkbox.isChecked()
            self.config.balance_warning_yellow = dialog.warning_threshold_input.value()
            self.config.auto_refresh_on_startup = dialog.auto_refresh_checkbox.isChecked()
            self.config.scheduled_refresh_enabled = dialog.scheduled_refresh_checkbox.isChecked()
            self.config.silent_usage_sync_enabled = dialog.silent_usage_sync_checkbox.isChecked()
            self.config.hide_taskbar_icon = dialog.hide_taskbar_checkbox.isChecked()
            self.config.start_minimized_to_tray = dialog.start_minimized_checkbox.isChecked()
            self.config.autostart_enabled = dialog.autostart_checkbox.isChecked()
            self.config.auto_start = self.config.autostart_enabled
            try:
                if self.config.autostart_enabled:
                    AutoStartManager.enable()
                else:
                    AutoStartManager.disable()
            except AutoStartError as error:
                self._write_app_log(f"Autostart setting failed: {error}")
                QMessageBox.warning(self, "开机自启失败", str(error))
                return
            self.config_manager.save(self.config)
            self._apply_always_on_top(self.config.always_on_top)
            self.apply_taskbar_visibility()
            self.restart_refresh_timer()
            QMessageBox.information(self, "设置", "设置已保存。")

    def _set_stat_card_value(self, card: StatCard, value: str) -> None:
        """更新 StatCard 中的数值标签。"""
        card.set_value(value)

    def _clear_local_usage_data(self) -> None:
        """清除 SQLite 本地用量数据。"""
        self.database.clear_usage_records()
        self.imported_usage_stats = None
        self.last_usage_update_text = ""
        self.refresh_usage_data()
        QMessageBox.information(self, "已清除", "本地用量数据已清除。")

    def _clear_deepseek_login_state(self) -> None:
        """清除 Playwright 浏览器会话。"""
        try:
            clear_browser_profile()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "清除失败", f"清除登录状态失败：{error}")
            return

        self.login_button.show()
        self._set_sync_status("DeepSeek 登录状态已清除")
        QMessageBox.information(self, "已清除", "DeepSeek 登录状态已清除。")

    def _clear_saved_api_key(self) -> None:
        """清除保存的 API Key。"""
        self.config_manager.clear_api_key()
        self.status_label.setText("未配置")
        QMessageBox.information(self, "已清除", "API Key 已清除。")

    def _apply_always_on_top(self, enabled: bool) -> None:
        """应用窗口置顶设置。"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def apply_taskbar_visibility(self) -> None:
        """根据配置显示或隐藏 Windows 任务栏图标。"""
        hide_taskbar = bool(self.config.hide_taskbar_icon)
        was_visible = self.isVisible()

        self.setWindowFlag(Qt.WindowType.Tool, hide_taskbar)
        if self.tray_manager:
            self.tray_manager.set_mode_text(hide_taskbar)
        self._write_taskbar_log(hide_taskbar)

        if was_visible:
            self.hide()
            self.show_window_from_tray()

    def show_window_from_tray(self) -> None:
        """从托盘菜单显示并激活主窗口。"""
        self.show()
        self.raise_()
        self.activateWindow()

    def exit_application(self) -> None:
        """通过托盘菜单真正退出程序。"""
        self._allow_exit = True
        if self.tray_manager:
            self.tray_manager.hide_icon()
        QApplication.quit()

    def _write_taskbar_log(self, hidden: bool) -> None:
        """记录任务栏图标显示状态，不包含敏感信息。"""
        self._write_app_log(f"Taskbar icon hidden: {str(hidden).lower()}")

    def _write_app_log(self, message: str) -> None:
        """写入普通运行日志，不包含敏感信息。"""
        try:
            logs_dir = get_logs_dir()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / "app.log"
            line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
            with log_file.open("a", encoding="utf-8") as file:
                file.write(line)
        except OSError:
            return

    def should_start_hidden(self) -> bool:
        """判断启动时是否直接进入托盘。"""
        if self.tray_manager is None or not self.tray_manager.available:
            return False
        return bool(self.started_from_autostart or self.config.start_minimized_to_tray)

    def _show_balance_warning(self, total_balance: float | None) -> None:
        """根据余额显示预警提示。"""
        if total_balance is None:
            self.balance_warning_label.hide()
            return

        red_threshold = getattr(self.config, "balance_warning_red", CRITICAL_BALANCE_WARNING)
        yellow_threshold = getattr(self.config, "balance_warning_yellow", LOW_BALANCE_WARNING)

        if total_balance < red_threshold:
            self.balance_warning_label.setStyleSheet(
                "background-color: rgba(251, 113, 133, 0.14); "
                "border: 1px solid rgba(251, 113, 133, 0.34); "
                "border-radius: 9px; color: #fb7185; "
                "padding: 3px 8px; font-size: 12px; font-weight: 700;"
            )
            self.balance_warning_label.setText("⚠ 余额严重不足")
            self.balance_warning_label.show()
        elif total_balance < yellow_threshold:
            self.balance_warning_label.setStyleSheet(
                "background-color: rgba(250, 204, 21, 0.14); "
                "border: 1px solid rgba(250, 204, 21, 0.34); "
                "border-radius: 9px; color: #facc15; "
                "padding: 3px 8px; font-size: 12px; font-weight: 700;"
            )
            self.balance_warning_label.setText("⚠ 余额偏低")
            self.balance_warning_label.show()
        else:
            self.balance_warning_label.hide()

    def _update_source_label(self) -> None:
        """刷新数据来源提示文字。"""
        balance_time = self.last_balance_update_text or "--:--"
        usage_time = self.last_usage_update_text or "--:--"
        timer_text = (
            f"{self.config.refresh_interval_minutes}分钟"
            if self.config.scheduled_refresh_enabled
            else "关闭"
        )
        self.source_label.setText(
            f"余额：{balance_time} 更新 · 用量：{usage_time} 更新 · 定时刷新：{timer_text}"
        )

    def _now_text(self) -> str:
        """返回当前时间文本。"""
        return datetime.now().strftime("%H:%M")

    def _parse_money_value(self, value: str | float | int) -> float:
        """把接口返回的余额字符串转成数字。"""
        try:
            return float(str(value).replace(",", "").replace("¥", "").replace("￥", ""))
        except ValueError:
            return 0.0

    def _infer_month_from_daily_costs(self, daily_costs: list[dict]) -> str:
        """从最近 7 天数据中推断数据月份。"""
        for item in daily_costs:
            date_text = str(item.get("date", ""))
            parts = date_text.split("-")
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}"
        return "未导入"

    def _progress_from_tokens(self, tokens: int, max_tokens: int) -> int:
        """根据最大 token 数计算进度条比例。"""
        if max_tokens <= 0:
            return 0

        return min(100, int(tokens / max_tokens * 100))

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制深蓝绿色渐变背景。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor("#092f35"))
        gradient.setColorAt(0.45, QColor("#0d4f58"))
        gradient.setColorAt(1.0, QColor("#081b2c"))

        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 24, 24)

        super().paintEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """允许拖动无边框窗口。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """拖动窗口时移动位置。"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        """隐藏任务栏模式下关闭窗口时转入系统托盘。"""
        if self._allow_exit:
            event.accept()
            return

        if self.tray_manager and self.tray_manager.available:
            event.ignore()
            self.hide()
            return

        self._allow_exit = True
        if self.tray_manager:
            self.tray_manager.hide_icon()
        event.accept()
        QApplication.quit()


def run_app(startup: bool = False) -> None:
    """启动 PySide6 应用。"""
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = DeepSeekMonitorWindow(startup=startup)
    if window.should_start_hidden():
        window.hide()
    else:
        window.show()
    app.exec()
