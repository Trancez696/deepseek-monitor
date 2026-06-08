"""SQLite 本地用量统计模块。

DeepSeek 官方余额接口只能查账户余额。
今日消耗、本月消耗、模型 token 用量和最近 7 天趋势通过本地 SQLite 记录。

用户数据保存到 %LOCALAPPDATA%\\DeepSeek Monitor\\usage.db
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.app_data import get_app_data_dir


DATABASE_FILE = get_app_data_dir() / "usage.db"


@dataclass
class UsageRecord:
    """一条本地用量记录。"""

    record_date: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float


@dataclass
class ModelUsageSummary:
    """单个模型的用量汇总。"""

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float


class UsageDatabase:
    """负责创建、写入和查询 usage.db。"""

    def __init__(self, database_file: Path = DATABASE_FILE) -> None:
        self.database_file = database_file
        self.initialize()

    def initialize(self) -> None:
        """创建数据库和 usage_records 表。"""
        self.database_file.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def add_usage_record(self, record: UsageRecord) -> None:
        """新增一条用量记录。"""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_records (
                    date,
                    model,
                    input_tokens,
                    output_tokens,
                    estimated_cost,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_date,
                    record.model,
                    record.input_tokens,
                    record.output_tokens,
                    record.estimated_cost,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            connection.commit()

    def get_today_cost(self) -> float:
        """查询今日消耗。"""
        return self._sum_cost_by_date_range(date.today(), date.today())

    def get_month_cost(self) -> float:
        """查询本月消耗。"""
        today = date.today()
        first_day = today.replace(day=1)
        return self._sum_cost_by_date_range(first_day, today)

    def get_model_summaries(self) -> list[ModelUsageSummary]:
        """按模型汇总 token 和估算费用。"""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    model,
                    SUM(input_tokens) AS input_total,
                    SUM(output_tokens) AS output_total,
                    SUM(estimated_cost) AS cost_total
                FROM usage_records
                GROUP BY model
                ORDER BY model
                """
            ).fetchall()

        summaries: list[ModelUsageSummary] = []
        for row in rows:
            input_tokens = int(row["input_total"] or 0)
            output_tokens = int(row["output_total"] or 0)
            summaries.append(
                ModelUsageSummary(
                    model=str(row["model"]),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    estimated_cost=float(row["cost_total"] or 0),
                )
            )

        return summaries

    def get_last_7_days_cost(self) -> list[tuple[str, float]]:
        """查询最近 7 天每天的估算费用。

        Returns:
            list[tuple[str, float]]: 例如 [("06-02", 0.12), ...]
        """
        today = date.today()
        start_day = today - timedelta(days=6)

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT date, SUM(estimated_cost) AS cost_total
                FROM usage_records
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                """,
                (start_day.isoformat(), today.isoformat()),
            ).fetchall()

        cost_by_date = {
            str(row["date"]): float(row["cost_total"] or 0) for row in rows
        }
        result: list[tuple[str, float]] = []

        for offset in range(7):
            current_day = start_day + timedelta(days=offset)
            date_key = current_day.isoformat()
            label = current_day.strftime("%m-%d")
            result.append((label, cost_by_date.get(date_key, 0.0)))

        return result

    def clear_usage_records(self) -> None:
        """清除本地用量记录。"""
        with self._connect() as connection:
            connection.execute("DELETE FROM usage_records")
            connection.commit()

    def _sum_cost_by_date_range(
        self, start_day: date, end_day: date
    ) -> float:
        """按日期范围统计 estimated_cost 总和。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT SUM(estimated_cost) AS cost_total
                FROM usage_records
                WHERE date BETWEEN ? AND ?
                """,
                (start_day.isoformat(), end_day.isoformat()),
            ).fetchone()

        return float(row["cost_total"] or 0)

    def _connect(self) -> sqlite3.Connection:
        """连接数据库，并让查询结果可以像字典一样读取。"""
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        return connection


def main() -> None:
    """命令行测试入口。

    初始化数据库：
        python -m src.database

    """
    import argparse

    parser = argparse.ArgumentParser(
        description="DeepSeek Monitor 本地用量数据库"
    )
    parser.parse_args()

    database = UsageDatabase()

    print(f"数据库已准备好：{DATABASE_FILE}")

    print(f"今日消耗：¥{database.get_today_cost():.4f}")
    print(f"本月消耗：¥{database.get_month_cost():.4f}")

    for summary in database.get_model_summaries():
        print(
            f"{summary.model}: "
            f"{summary.total_tokens} tokens, "
            f"¥{summary.estimated_cost:.4f}"
        )


if __name__ == "__main__":
    main()
