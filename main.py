"""DeepSeek Monitor 程序入口。

从这里启动 PySide6 桌面窗口。
"""

from src.app import run_app


def main() -> None:
    """程序主函数。"""
    run_app()


if __name__ == "__main__":
    main()
