"""真实 DeepSeek API 调用用量记录模块。

在你自己的 DeepSeek API 调用脚本中引入该模块，自动将每次调用的
token 用量写入本地 SQLite（usage.db），界面会在下次刷新时展示。

使用方法：
    from src.usage_recorder import record_usage, record_from_response, UsageRecorder

    # 方式 1：从 API 响应 JSON 自动提取（推荐）
    response = requests.post("https://api.deepseek.com/chat/completions", ...)
    data = response.json()
    record_from_response(data)

    # 方式 2：手动记录 token 数
    record_usage("deepseek-chat", input_tokens=100, output_tokens=50)

    # 方式 3：使用上下文管理器记录批量调用
    with UsageRecorder() as recorder:
        for resp in api_responses:
            recorder.record_from_response(resp)

DeepSeek API 响应格式（OpenAI 兼容）：
    {
        "model": "deepseek-chat",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.database import UsageDatabase, UsageRecord


# ---------------------------------------------------------------------------
# DeepSeek 官方定价（每 1K tokens，单位 CNY）
# 来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# 更新日期：2026-06
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat":            {"input": 0.0005, "output": 0.0020},
    "deepseek-v4-flash":        {"input": 0.0005, "output": 0.0010},
    "deepseek-v4-pro":          {"input": 0.0020, "output": 0.0080},
    "deepseek-reasoner":        {"input": 0.0020, "output": 0.0080},
    # 兼容旧模型别名
    "deepseek-v3":              {"input": 0.0005, "output": 0.0020},
    "deepseek-r1":              {"input": 0.0020, "output": 0.0080},
}

# 未列出的模型的默认价格
_DEFAULT_INPUT_PRICE = 0.001
_DEFAULT_OUTPUT_PRICE = 0.002


def get_model_pricing(model: str) -> tuple[float, float]:
    """获取指定模型的 input/output 每千 token 单价（CNY）。

    Returns:
        (input_price_per_1k, output_price_per_1k)
    """
    # 尝试精确匹配，再尝试前缀匹配（如 "deepseek-chat-v2" → "deepseek-chat"）
    if model in MODEL_PRICING:
        pricing = MODEL_PRICING[model]
        return pricing["input"], pricing["output"]

    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key):
            return pricing["input"], pricing["output"]

    return _DEFAULT_INPUT_PRICE, _DEFAULT_OUTPUT_PRICE


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """根据模型和 token 数估算费用。"""
    input_price, output_price = get_model_pricing(model)
    cost = (input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price)
    return round(cost, 6)


def canonical_model_name(model: str) -> str:
    """将 API 返回的模型名映射为界面友好的短名称。

    映射规则：
        deepseek-chat → deepseek-chat
        deepseek/deepseek-chat → deepseek-chat
        deepseek-v4-flash → V4 Flash (界面显示)
    """
    name = model.strip()
    # 去掉 provider 前缀
    if "/" in name:
        name = name.split("/")[-1]

    # 界面友好名映射
    friendly_names = {
        "deepseek-chat": "deepseek-chat",
        "deepseek-v4-flash": "V4 Flash",
        "deepseek-v4-pro": "V4 Pro",
        "deepseek-reasoner": "deepseek-reasoner",
    }
    return friendly_names.get(name, name)


def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float | None = None,
    database: UsageDatabase | None = None,
) -> None:
    """记录一次 API 调用的 token 用量到 usage.db。

    Args:
        model: 模型名称，如 "deepseek-chat"、"V4 Flash"
        input_tokens: 输入（prompt）token 数
        output_tokens: 输出（completion）token 数
        cost: 实际费用（CNY）。为 None 时根据模型定价自动估算
        database: UsageDatabase 实例。为 None 时使用默认单例
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    db = database or UsageDatabase()
    if cost is None:
        cost = estimate_cost(model, input_tokens, output_tokens)

    record = UsageRecord(
        record_date=date.today().isoformat(),
        model=canonical_model_name(model),
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        estimated_cost=cost,
    )
    db.add_usage_record(record)
    print(f"[UsageRecorder] {record.model}: +{record.input_tokens}in / +{record.output_tokens}out = CNY {cost:.6f}")


def record_from_response(
    response_data: dict[str, Any],
    model: str | None = None,
    database: UsageDatabase | None = None,
) -> dict[str, int] | None:
    """从 DeepSeek API 响应 JSON 中提取并记录 token 用量。

    兼容 OpenAI 格式的 usage 字段：
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }

    Args:
        response_data: DeepSeek API 返回的 JSON 字典
        model: 模型名称。为 None 时从 response_data["model"] 读取
        database: UsageDatabase 实例

    Returns:
        记录的 usage 字典 {"input_tokens": ..., "output_tokens": ...}
        如果响应中没有 usage 信息则返回 None
    """
    usage = response_data.get("usage")
    if not usage or not isinstance(usage, dict):
        return None

    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0

    if input_tokens <= 0 and output_tokens <= 0:
        return None

    resolved_model = model or response_data.get("model", "unknown")

    record_usage(
        model=resolved_model,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        database=database,
    )

    return {"input_tokens": int(input_tokens), "output_tokens": int(output_tokens)}


def record_from_streaming_chunks(
    chunks: list[dict[str, Any]],
    model: str | None = None,
    database: UsageDatabase | None = None,
) -> dict[str, int] | None:
    """从流式（SSE）响应的 chunk 列表中提取总用量。

    DeepSeek 流式响应中，最后一个 chunk 通常包含完整 usage 信息。

    Args:
        chunks: 流式响应收集到的所有 JSON chunk
        model: 模型名称（通常第一个 chunk 包含 model 字段）
        database: UsageDatabase 实例

    Returns:
        记录的 usage 字典，或 None
    """
    # 从第一个非空 chunk 取 model
    resolved_model = model
    if not resolved_model:
        for chunk in chunks:
            if chunk.get("model"):
                resolved_model = chunk["model"]
                break

    # 从最后一个 chunk 取 usage（流式最后一条带汇总）
    for chunk in reversed(chunks):
        result = record_from_response(chunk, model=resolved_model, database=database)
        if result is not None:
            return result

    # 如果没有任何 chunk 包含 usage，尝试累加 delta 中的 token
    total_input = 0
    total_output = 0
    for chunk in chunks:
        usage = chunk.get("usage")
        if usage:
            # 有些流式实现每次发增量
            total_input += usage.get("prompt_tokens", 0) or 0
            total_output += usage.get("completion_tokens", 0) or 0

    if total_input > 0 or total_output > 0:
        record_usage(
            model=resolved_model or "unknown",
            input_tokens=total_input,
            output_tokens=total_output,
            database=database,
        )
        return {"input_tokens": total_input, "output_tokens": total_output}

    return None


@dataclass
class UsageStats:
    """一次会话中的用量汇总。"""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    request_count: int = 0
    models: dict[str, dict[str, int | float]] = field(default_factory=dict)


class UsageRecorder:
    """API 调用用量记录器（上下文管理器）。

    适用于批量记录多条 API 调用后统一写入 DB。
    也可以在单次调用场景直接使用模块级函数。

    用法：
        recorder = UsageRecorder()

        # 记录单个响应
        recorder.record_from_response(response_data)

        # 记录流式响应
        recorder.record_from_streaming_chunks(chunks)

        # 手动记录
        recorder.record("deepseek-chat", input_tokens=100, output_tokens=50)

        # 获取统计
        stats = recorder.stats()
        print(stats)

        # 批量写入 DB
        recorder.flush()
    """

    def __init__(self, database: UsageDatabase | None = None) -> None:
        self.database = database or UsageDatabase()
        self._records: list[UsageRecord] = []

    def __enter__(self) -> UsageRecorder:
        return self

    def __exit__(self, *args: Any) -> None:
        self.flush()

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float | None = None,
    ) -> None:
        """添加一条用量记录（暂不写入 DB，调用 flush() 后统一写入）。"""
        if input_tokens <= 0 and output_tokens <= 0:
            return

        if cost is None:
            cost = estimate_cost(model, input_tokens, output_tokens)

        self._records.append(
            UsageRecord(
                record_date=date.today().isoformat(),
                model=canonical_model_name(model),
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                estimated_cost=cost,
            )
        )

    def record_from_response(self, response_data: dict[str, Any]) -> bool:
        """从 API 响应 JSON 中提取并暂存用量。"""
        usage = response_data.get("usage")
        if not usage or not isinstance(usage, dict):
            return False

        input_tokens = usage.get("prompt_tokens", 0) or 0
        output_tokens = usage.get("completion_tokens", 0) or 0

        if input_tokens <= 0 and output_tokens <= 0:
            return False

        model = response_data.get("model", "unknown")
        self.record(model, int(input_tokens), int(output_tokens))
        return True

    def record_from_streaming_chunks(self, chunks: list[dict[str, Any]]) -> bool:
        """从流式响应 chunks 中提取并暂存用量。"""
        resolved_model: str | None = None
        for chunk in chunks:
            if chunk.get("model"):
                resolved_model = chunk["model"]
                break

        for chunk in reversed(chunks):
            usage = chunk.get("usage")
            if usage:
                input_tokens = usage.get("prompt_tokens", 0) or 0
                output_tokens = usage.get("completion_tokens", 0) or 0
                if input_tokens > 0 or output_tokens > 0:
                    self.record(
                        model=resolved_model or "unknown",
                        input_tokens=int(input_tokens),
                        output_tokens=int(output_tokens),
                    )
                    return True

        return False

    def flush(self) -> int:
        """将暂存的记录批量写入 usage.db。

        Returns:
            写入的记录条数
        """
        count = len(self._records)
        for record in self._records:
            self.database.add_usage_record(record)
        self._records.clear()
        return count

    def stats(self) -> UsageStats:
        """返回当前暂存记录的统计汇总。"""
        stats = UsageStats()
        for record in self._records:
            stats.total_input_tokens += record.input_tokens
            stats.total_output_tokens += record.output_tokens
            stats.total_cost += record.estimated_cost
            stats.request_count += 1

            if record.model not in stats.models:
                stats.models[record.model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "requests": 0,
                }
            m = stats.models[record.model]
            m["input_tokens"] += record.input_tokens
            m["output_tokens"] += record.output_tokens
            m["cost"] = round(float(m["cost"]) + record.estimated_cost, 6)
            m["requests"] += 1

        return stats

    def __len__(self) -> int:
        return len(self._records)
