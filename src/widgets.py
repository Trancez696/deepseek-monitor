"""自定义界面组件模块。

这里放主界面会复用的小组件，让 app.py 保持清爽。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


def format_money(value: float | int | str, digits: int = 2) -> str:
    """把金额统一格式化为人民币显示。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"¥{number:.{digits}f}"


class GlassCard(QFrame):
    """半透明玻璃卡片。"""

    def __init__(self, object_name: str = "glassCard", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._add_shadow()

    def _add_shadow(self) -> None:
        """给卡片加柔和阴影。"""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)


class StatCard(GlassCard):
    """今日消耗、本月消耗这类小统计卡片。"""

    def __init__(self, title: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__("smallCard", parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("mutedLabel")

        value_label = QLabel(value)
        value_label.setObjectName("sectionValue")

        layout.addWidget(title_label)
        layout.addWidget(value_label)

    def set_value(self, value: str) -> None:
        """更新小统计卡片的数值。"""
        value_label = self.findChild(QLabel, "sectionValue")
        if value_label:
            value_label.setText(value)


class ModelUsageCard(GlassCard):
    """模型 token 用量卡片。"""

    def __init__(
        self,
        model_name: str,
        tokens: int,
        estimated_cost: float,
        progress: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("modelCard", parent)
        self.model_name = model_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        name_label = QLabel(model_name)
        name_label.setObjectName("sectionValue")

        cost_label = QLabel(format_money(estimated_cost))
        cost_label.setObjectName("mutedLabel")
        cost_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_layout.addWidget(name_label)
        header_layout.addWidget(cost_label)

        self.cost_label = cost_label
        self.token_label = QLabel()
        self.token_label.setObjectName("mutedLabel")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)

        layout.addLayout(header_layout)
        layout.addWidget(self.token_label)
        layout.addWidget(self.progress_bar)

        self.update_usage(tokens, estimated_cost, progress)

    def update_usage(self, tokens: int, estimated_cost: float, progress: int, requests: int = 0) -> None:
        """更新模型卡片显示的数据。"""
        if tokens <= 0:
            self.cost_label.setText("")
            self.token_label.setText("暂无用量数据")
            self.progress_bar.setValue(0)
            self.progress_bar.setEnabled(False)
            self.progress_bar.hide()
            return

        self.cost_label.setText(format_money(estimated_cost))
        request_text = f"请求 {requests:,} 次 · " if requests else ""
        self.token_label.setText(f"{request_text}{tokens:,} tokens")
        self.progress_bar.setEnabled(True)
        self.progress_bar.show()
        self.progress_bar.setValue(progress)


class UsageBarChart(QWidget):
    """最近 7 天消耗趋势柱状图。

    第一版先用传入的简单数字绘制，后续会接入 SQLite 数据。
    """

    def __init__(self, values: list[float], labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values = values
        self.labels = labels
        self.month_text = "未导入"
        self.total_text = format_money(0)
        self.empty_text = "暂无用量数据，请导入 DeepSeek Usage 文件"
        self.setMinimumHeight(152)

    def set_data(
        self,
        values: list[float],
        labels: list[str],
        month_text: str = "未导入",
        total_cost: float = 0.0,
    ) -> None:
        """更新柱状图数据并重绘。"""
        self.values = values
        self.labels = labels
        self.month_text = month_text
        self.total_text = format_money(total_cost)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制柱状图。"""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        left_padding = 12
        right_padding = 12
        bottom_padding = 28
        top_padding = 22
        chart_width = width - left_padding - right_padding
        chart_height = height - top_padding - bottom_padding

        if not self.values or max(self.values, default=0) <= 0:
            painter.setPen(QColor(242, 255, 251, 150))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.empty_text,
            )
            return

        max_value = max(max(self.values), 0.01)
        bar_count = len(self.values)
        slot_width = chart_width / bar_count
        bar_width = max(12, min(28, slot_width * 0.46))

        line_pen = QPen(QColor(255, 255, 255, 35))
        painter.setPen(line_pen)
        for index in range(3):
            y = top_padding + chart_height * index / 2
            painter.drawLine(left_padding, int(y), width - right_padding, int(y))

        for index, value in enumerate(self.values):
            normalized = value / max_value
            bar_height = chart_height * normalized
            x = left_padding + slot_width * index + (slot_width - bar_width) / 2
            y = top_padding + chart_height - bar_height

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(74, 222, 190, 175))
            painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_height), 6, 6)

            if value > 0:
                painter.setPen(QColor(242, 255, 251, 185))
                painter.drawText(
                    int(x - 15),
                    max(2, int(y - 18)),
                    int(bar_width + 30),
                    14,
                    Qt.AlignmentFlag.AlignCenter,
                    format_money(value),
                )

            painter.setPen(QColor(242, 255, 251, 160))
            label = self.labels[index] if index < len(self.labels) else ""
            painter.drawText(
                int(x - 8),
                height - 18,
                int(bar_width + 16),
                16,
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
