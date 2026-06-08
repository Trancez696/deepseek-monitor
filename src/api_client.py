"""DeepSeek API 请求模块。

这个文件负责访问 DeepSeek 的余额接口：

    GET https://api.deepseek.com/user/balance

注意：
- 不要把 API Key 写死在代码里。
- 命令行测试时，可以用参数或环境变量传入 API Key。
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_BASE_URL = "https://api.deepseek.com"


@dataclass
class BalanceInfo:
    """单个币种的余额信息。"""

    currency: str
    total_balance: str
    granted_balance: str
    topped_up_balance: str


@dataclass
class BalanceResult:
    """余额接口返回的整理结果。"""

    is_available: bool
    balance_infos: list[BalanceInfo]


class DeepSeekApiError(Exception):
    """DeepSeek API 请求失败时使用的错误。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DeepSeekApiClient:
    """DeepSeek API 客户端。

    第一版只实现余额查询，后续如果需要调用其他接口，可以继续在这里扩展。
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    def get_balance(self) -> BalanceResult:
        """查询账户余额。

        Returns:
            BalanceResult: 整理后的余额结果。

        Raises:
            DeepSeekApiError: 当 API Key 缺失、网络失败或接口返回错误时抛出。
        """
        if not self.api_key:
            raise DeepSeekApiError("API Key 为空，请先提供 DeepSeek API Key。")

        url = f"{self.base_url}/user/balance"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            response = requests.get(url, headers=headers, timeout=15)
        except requests.ConnectionError as error:
            raise DeepSeekApiError("网络连接失败，请检查网络后重试。") from error
        except requests.Timeout as error:
            raise DeepSeekApiError("请求超时，请稍后重试。") from error
        except requests.RequestException as error:
            raise DeepSeekApiError(f"请求失败：{error}") from error

        if response.status_code != 200:
            raise DeepSeekApiError(
                self._message_for_status(response.status_code),
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as error:
            raise DeepSeekApiError("服务器返回的数据不是有效 JSON。") from error

        return self._parse_balance_result(data)

    def _parse_balance_result(self, data: dict[str, Any]) -> BalanceResult:
        """把接口 JSON 转换成程序内部更好用的数据结构。"""
        balance_infos: list[BalanceInfo] = []

        for item in data.get("balance_infos", []):
            balance_infos.append(
                BalanceInfo(
                    currency=str(item.get("currency", "")),
                    total_balance=str(item.get("total_balance", "0")),
                    granted_balance=str(item.get("granted_balance", "0")),
                    topped_up_balance=str(item.get("topped_up_balance", "0")),
                )
            )

        return BalanceResult(
            is_available=bool(data.get("is_available", False)),
            balance_infos=balance_infos,
        )

    def _message_for_status(self, status_code: int) -> str:
        """根据 HTTP 状态码生成适合显示给用户看的提示。"""
        status_messages = {
            401: "API Key 错误或已失效，请检查后重试。",
            402: "账户余额不足，请充值后重试。",
            429: "请求太频繁，请稍后再试。",
            500: "DeepSeek 服务器出现问题，请稍后重试。",
            503: "DeepSeek 服务暂时不可用，请稍后重试。",
        }
        return status_messages.get(status_code, f"请求失败，HTTP 状态码：{status_code}")


def print_balance_result(result: BalanceResult) -> None:
    """在命令行打印余额查询结果。"""
    status_text = "可用" if result.is_available else "不可用"
    print(f"接口状态：{status_text}")

    if not result.balance_infos:
        print("没有返回余额信息。")
        return

    for balance in result.balance_infos:
        print(f"币种：{balance.currency}")
        print(f"总余额：{balance.total_balance}")
        print(f"充值余额：{balance.topped_up_balance}")
        print(f"赠送余额：{balance.granted_balance}")


def main() -> None:
    """命令行测试入口。

    示例：
        python -m src.api_client --api-key sk-xxxx

    也可以先设置环境变量：
        $env:DEEPSEEK_API_KEY="sk-xxxx"
        python -m src.api_client
    """
    parser = argparse.ArgumentParser(description="测试 DeepSeek 余额查询接口")
    parser.add_argument("--api-key", help="DeepSeek API Key，不建议长期写在命令历史里")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="DeepSeek API 基础地址")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY", "")
    client = DeepSeekApiClient(api_key=api_key, base_url=args.base_url)

    try:
        result = client.get_balance()
    except DeepSeekApiError as error:
        print(f"查询失败：{error}")
        return

    print_balance_result(result)


if __name__ == "__main__":
    main()
