"""系统托盘模块。

将 DeepSeek Monitor 最小化到系统托盘的管理器。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


class TrayManager:
    """管理系统托盘图标和右键菜单。

    Args:
        icon: 托盘图标的 QIcon
        parent: 父窗口（DeepSeekMonitorWindow）
        on_show: 点击"显示窗口"时的回调
        on_refresh: 点击"立即刷新"时的回调
        on_settings: 点击"打开设置"时的回调
        on_quit: 点击"退出程序"时的回调
    """

    def __init__(
        self,
        icon: QIcon,
        parent: QWidget,
        *,
        on_show: Callable[[], None],
        on_refresh: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._parent = parent
        self._on_quit = on_quit
        self._tray_icon: QSystemTrayIcon | None = None
        self._status_action: QAction | None = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray_icon = QSystemTrayIcon(icon, parent)
        self._tray_icon.setToolTip("DeepSeek Monitor")

        menu = QMenu(parent)
        self._status_action = QAction("", parent)
        self._status_action.setEnabled(False)
        show_action = QAction("显示窗口", parent)
        refresh_action = QAction("立即刷新", parent)
        settings_action = QAction("打开设置", parent)
        quit_action = QAction("退出程序", parent)

        show_action.triggered.connect(on_show)
        refresh_action.triggered.connect(on_refresh)
        settings_action.triggered.connect(on_settings)
        quit_action.triggered.connect(self._on_quit_called)

        menu.addAction(self._status_action)
        menu.addSeparator()
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._handle_activated)
        self._tray_icon.show()

    # -- 公开属性 ----------------------------------------------------------

    @property
    def available(self) -> bool:
        """系统托盘是否可用。"""
        return self._tray_icon is not None

    @property
    def icon(self) -> QSystemTrayIcon | None:
        """QSystemTrayIcon 实例（供 closeEvent 使用）。"""
        return self._tray_icon

    # -- 公开方法 ----------------------------------------------------------

    def set_mode_text(self, hide_taskbar: bool) -> None:
        """更新托盘菜单中的当前显示模式文本。"""
        if self._status_action is None:
            return
        if hide_taskbar:
            self._status_action.setText("当前模式：仅托盘显示")
        else:
            self._status_action.setText("当前模式：任务栏 + 托盘")

    def hide_icon(self) -> None:
        """隐藏托盘图标（退出程序时调用）。"""
        if self._tray_icon is not None:
            self._tray_icon.hide()

    # -- 内部方法 ----------------------------------------------------------

    def _on_quit_called(self) -> None:
        """退出程序时确保托盘图标被移除。"""
        self.hide_icon()
        self._on_quit()

    def _handle_activated(self, reason) -> None:
        """双击托盘图标时显示窗口。"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._parent:
                self._parent.show()
                self._parent.raise_()
                self._parent.activateWindow()
