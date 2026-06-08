"""DeepSeek Usage 导出文件导入模块。

这个模块只解析用户手动导出的 ZIP/CSV 文件。
不抓取网页接口，不保存网页登录密码，也不使用 Cookie。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class UsageImportError(Exception):
    """导入 Usage 文件失败时抛出的错误。"""


def import_usage_file(file_path: str | Path) -> dict[str, Any]:
    """导入 DeepSeek Usage 页面导出的 ZIP 或 CSV 文件。"""
    path = Path(file_path)

    if not path.exists():
        raise UsageImportError(f"文件不存在：{path}")

    if path.suffix.lower() == ".csv":
        csv_files = [path]

        rows: list[dict[str, str]] = []
        for csv_file in csv_files:
            rows.extend(_read_csv_rows(csv_file))

        if not rows:
            raise UsageImportError("CSV 文件为空，或者没有可识别的数据行。")

        return _build_usage_summary(rows)

    if path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="deepseek_usage_") as temp_dir:
            csv_files = _extract_zip_csv_files(path, Path(temp_dir))
            if not csv_files:
                raise UsageImportError("没有在导出 ZIP 中找到 CSV 文件。")

            rows = []
            for csv_file in csv_files:
                rows.extend(_read_csv_rows(csv_file))

            if not rows:
                raise UsageImportError("CSV 文件为空，或者没有可识别的数据行。")

            return _build_usage_summary(rows)

    raise UsageImportError("只支持导入 .zip 或 .csv 文件。")


def _extract_zip_csv_files(zip_path: Path, temp_dir: Path) -> list[Path]:
    """把 ZIP 中的 CSV 解压到临时目录，并返回 CSV 路径列表。"""
    csv_files: list[Path] = []

    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".csv"):
                    continue

                safe_name = Path(member.filename).name
                if not safe_name:
                    continue

                target = temp_dir / safe_name
                with archive.open(member) as source, target.open("wb") as output:
                    output.write(source.read())
                csv_files.append(target)
    except zipfile.BadZipFile as error:
        raise UsageImportError("ZIP 文件损坏或格式不正确。") from error

    return csv_files


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """读取 CSV，兼容 utf-8 和 utf-8-sig。"""
    last_error: Exception | None = None

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return _read_csv_rows_with_encoding(csv_path, encoding)
        except UnicodeDecodeError as error:
            last_error = error

    raise UsageImportError(f"无法用 utf-8 读取 CSV：{csv_path.name}") from last_error


def _read_csv_rows_with_encoding(csv_path: Path, encoding: str) -> list[dict[str, str]]:
    """用指定编码读取 CSV，并清理空列空行。"""
    with csv_path.open("r", encoding=encoding, newline="") as file:
        sample = file.read(4096)
        file.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(file, dialect=dialect, restkey="__extra__")
        rows: list[dict[str, str]] = []

        for row in reader:
            clean_row: dict[str, str] = {}
            for key, value in row.items():
                if key is None or key == "__extra__":
                    continue

                clean_key = _normalize_header(key)
                clean_value = "" if value is None else str(value).strip()
                if clean_key:
                    clean_row[clean_key] = clean_value

            if any(value for value in clean_row.values()):
                rows.append(clean_row)

    for row in rows:
        row["__source_file"] = csv_path.name.lower()

    return rows


def _build_usage_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    """把 CSV 行聚合成界面需要的统一字典结构。"""
    if _looks_like_deepseek_official_export(rows):
        return _build_deepseek_official_summary(rows)

    return _build_generic_usage_summary(rows)


def _looks_like_deepseek_official_export(rows: list[dict[str, str]]) -> bool:
    """判断是否是 DeepSeek Usage 页面当前官方导出格式。"""
    has_amount_rows = any("type" in row and "amount" in row for row in rows)
    has_cost_rows = any("wallet_type" in row and "cost" in row for row in rows)
    return has_amount_rows or has_cost_rows


def _build_deepseek_official_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    """解析 DeepSeek 官方 Usage 导出的 cost/amount CSV 格式。

    当前官方格式里：
    - cost-*.csv 的 cost 是实际 CNY 消费金额。
    - amount-*.csv 的 amount 是数量，type 决定它是 tokens 还是 request_count。
    - amount-*.csv 的 price * amount 也可以还原该行费用。
    """
    today = date.today()
    month_start = today.replace(day=1)
    seven_day_start = today - timedelta(days=6)

    daily_cost_map: dict[str, float] = defaultdict(float)
    parsed_dates: list[date] = []
    model_costs: dict[str, float] = defaultdict(float)
    model_tokens: dict[str, int] = defaultdict(int)
    model_requests: dict[str, int] = defaultdict(int)
    api_keys: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
    )

    has_cost_rows = any("cost" in row and row.get("cost", "").strip() for row in rows)

    for row in rows:
        row_date = _pick_date(row)
        if row_date:
            parsed_dates.append(row_date)
        model = _pick_string(row, MODEL_HEADERS) or "unknown"

        if "cost" in row and row.get("cost", "").strip():
            cost = _parse_number(row.get("cost", "")) or 0.0
            model_costs[model] += cost
            if row_date:
                daily_cost_map[row_date.isoformat()] += cost
            continue

        usage_type = row.get("type", "").strip().lower()
        amount = _parse_number(row.get("amount", "")) or 0.0
        price = _parse_number(row.get("price", "")) or 0.0
        row_cost = round(price * amount, 12) if price and amount else 0.0
        api_key = _pick_string(row, API_KEY_HEADERS)

        if "request_count" in usage_type or usage_type == "requests":
            request_count = int(amount)
            model_requests[model] += request_count
            if api_key:
                api_keys[api_key]["requests"] = int(api_keys[api_key]["requests"]) + request_count
            continue

        if "token" in usage_type:
            token_count = int(amount)
            model_tokens[model] += token_count
            if api_key:
                api_keys[api_key]["tokens"] = int(api_keys[api_key]["tokens"]) + token_count

        if row_cost:
            if not has_cost_rows:
                model_costs[model] += row_cost
                if row_date:
                    daily_cost_map[row_date.isoformat()] += row_cost
            if api_key:
                api_keys[api_key]["cost"] = float(api_keys[api_key]["cost"]) + row_cost

    month_cost = 0.0
    today_cost = 0.0
    for date_text, cost in daily_cost_map.items():
        parsed_date = _parse_date(date_text)
        if not parsed_date:
            continue
        if month_start <= parsed_date <= today:
            month_cost += cost
        if parsed_date == today:
            today_cost += cost

    models: dict[str, dict[str, float | int]] = {}
    all_model_names = set(model_costs) | set(model_tokens) | set(model_requests)
    for model in all_model_names:
        models[model] = {
            "tokens": model_tokens.get(model, 0),
            "cost": round(model_costs.get(model, 0.0), 6),
            "requests": model_requests.get(model, 0),
        }

    daily_costs = []
    for offset in range(7):
        current_day = seven_day_start + timedelta(days=offset)
        daily_costs.append(
            {
                "date": current_day.isoformat(),
                "cost": round(daily_cost_map.get(current_day.isoformat(), 0.0), 6),
            }
        )

    return {
        "month_cost": round(month_cost, 6),
        "today_cost": round(today_cost, 6),
        "total_tokens": sum(model_tokens.values()),
        "api_requests": sum(model_requests.values()),
        "data_month": _infer_data_month(parsed_dates),
        "daily_costs": daily_costs,
        "models": _round_nested_costs(models),
        "api_keys": _round_nested_costs(dict(api_keys)),
    }


def _build_generic_usage_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    """解析普通明细 CSV 格式。"""
    today = date.today()
    month_start = today.replace(day=1)
    seven_day_start = today - timedelta(days=6)

    daily_cost_map: dict[str, float] = defaultdict(float)
    models: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
    )
    api_keys: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
    )

    month_cost = 0.0
    today_cost = 0.0
    total_tokens = 0
    api_requests = 0
    parsed_signal_count = 0
    parsed_dates: list[date] = []

    for row in rows:
        row_date = _pick_date(row)
        if row_date:
            parsed_dates.append(row_date)
        model = _pick_string(row, MODEL_HEADERS) or "unknown"
        api_key = _pick_string(row, API_KEY_HEADERS)
        cost = _pick_number(row, COST_HEADERS)
        requests = int(_pick_number(row, REQUEST_HEADERS) or 0)
        input_tokens = int(_pick_number(row, INPUT_TOKEN_HEADERS) or 0)
        output_tokens = int(_pick_number(row, OUTPUT_TOKEN_HEADERS) or 0)
        total_row_tokens = int(_pick_number(row, TOTAL_TOKEN_HEADERS) or 0)

        if not total_row_tokens:
            total_row_tokens = input_tokens + output_tokens

        if not requests and (cost or total_row_tokens or model != "unknown"):
            requests = 1

        if cost or total_row_tokens or requests:
            parsed_signal_count += 1

        if row_date:
            daily_cost_map[row_date.isoformat()] += cost
            if month_start <= row_date <= today:
                month_cost += cost
            if row_date == today:
                today_cost += cost

        total_tokens += total_row_tokens
        api_requests += requests

        model_bucket = models[model]
        model_bucket["tokens"] = int(model_bucket["tokens"]) + total_row_tokens
        model_bucket["cost"] = float(model_bucket["cost"]) + cost
        model_bucket["requests"] = int(model_bucket["requests"]) + requests

        if api_key:
            key_bucket = api_keys[api_key]
            key_bucket["tokens"] = int(key_bucket["tokens"]) + total_row_tokens
            key_bucket["cost"] = float(key_bucket["cost"]) + cost
            key_bucket["requests"] = int(key_bucket["requests"]) + requests

    if parsed_signal_count == 0:
        raise UsageImportError("没有识别到金额、token 或请求次数列，请检查导出的 CSV 表头。")

    daily_costs = []
    for offset in range(7):
        current_day = seven_day_start + timedelta(days=offset)
        daily_costs.append(
            {
                "date": current_day.isoformat(),
                "cost": round(daily_cost_map.get(current_day.isoformat(), 0.0), 6),
            }
        )

    return {
        "month_cost": round(month_cost, 6),
        "today_cost": round(today_cost, 6),
        "total_tokens": total_tokens,
        "api_requests": api_requests,
        "data_month": _infer_data_month(parsed_dates),
        "daily_costs": daily_costs,
        "models": _round_nested_costs(dict(models)),
        "api_keys": _round_nested_costs(dict(api_keys)),
    }


def _normalize_header(header: str) -> str:
    """把表头转成便于匹配的格式。"""
    return str(header).strip().lower().replace("\ufeff", "")


def _pick_string(row: dict[str, str], names: set[str]) -> str:
    """按候选表头从一行里取文本值。"""
    for key, value in row.items():
        if _header_matches(key, names) and value.strip():
            return value.strip()
    return ""


def _pick_number(row: dict[str, str], names: set[str]) -> float:
    """按候选表头从一行里取数字。"""
    for key, value in row.items():
        if names is TOTAL_TOKEN_HEADERS and _looks_like_partial_token_header(key):
            continue
        if _header_matches(key, names):
            number = _parse_number(value)
            if number is not None:
                return number
    return 0.0


def _pick_date(row: dict[str, str]) -> date | None:
    """从一行里识别日期。"""
    for key, value in row.items():
        if _header_matches(key, DATE_HEADERS):
            parsed_date = _parse_date(value)
            if parsed_date:
                return parsed_date
    return None


def _header_matches(header: str, names: set[str]) -> bool:
    """判断表头是否命中候选名称。"""
    compact = re.sub(r"[\s_\-()/（）]+", "", header.lower())
    for name in names:
        name_compact = re.sub(r"[\s_\-()/（）]+", "", name.lower())
        if name_compact in {"key", "time", "date", "day", "count", "tokens"}:
            if compact == name_compact:
                return True
            continue
        if compact == name_compact or name_compact in compact:
            return True
    return False


def _looks_like_partial_token_header(header: str) -> bool:
    """判断表头是否是输入/输出 token，而不是总 token。"""
    compact = re.sub(r"[\s_\-()/（）]+", "", header.lower())
    partial_words = {
        "input",
        "prompt",
        "output",
        "completion",
        "输入",
        "提示",
        "输出",
        "补全",
    }
    return any(word in compact for word in partial_words)


def _parse_number(value: str) -> float | None:
    """解析金额、token、请求数等数字。"""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", "")
    text = re.sub(r"(cny|rmb|usd|¥|￥|\$|元|次|tokens?|token)", "", text, flags=re.IGNORECASE)
    text = text.strip()

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None

    return float(match.group(0))


def _parse_date(value: str) -> date | None:
    """解析常见中英文日期格式。"""
    text = str(value).strip()
    if not text:
        return None

    text = text.replace("/", "-")
    text = re.sub(r"[年月]", "-", text).replace("日", "")
    text = text.split("T")[0].strip()
    text = text.split(" ")[0].strip()

    for fmt in ("%Y-%m-%d", "%Y-%m", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue

    return None


def _round_nested_costs(data: dict[str, dict[str, float | int]]) -> dict[str, dict[str, float | int]]:
    """把聚合字典里的 cost 统一四舍五入。"""
    rounded: dict[str, dict[str, float | int]] = {}
    for key, value in data.items():
        rounded[key] = {
            "tokens": int(value.get("tokens", 0)),
            "cost": round(float(value.get("cost", 0.0)), 6),
            "requests": int(value.get("requests", 0)),
        }
    return rounded


def _infer_data_month(dates: list[date]) -> str:
    """从导出数据日期推断月份。"""
    if not dates:
        return "未导入"

    month_counts: dict[str, int] = defaultdict(int)
    for item in dates:
        month_counts[item.strftime("%Y-%m")] += 1

    return max(month_counts, key=month_counts.get)


DATE_HEADERS = {
    "date",
    "utc_date",
    "utc date",
    "day",
    "time",
    "created_at",
    "created time",
    "request time",
    "usage date",
    "日期",
    "月份",
    "时间",
    "创建时间",
    "请求时间",
    "用量日期",
}

COST_HEADERS = {
    "amount",
    "cost",
    "price",
    "charge",
    "fee",
    "total amount",
    "total cost",
    "金额",
    "费用",
    "消费",
    "花费",
    "用量金额",
    "总金额",
    "总费用",
}

MODEL_HEADERS = {
    "model",
    "model_name",
    "model name",
    "模型",
    "模型名称",
}

INPUT_TOKEN_HEADERS = {
    "input_tokens",
    "prompt_tokens",
    "input tokens",
    "prompt tokens",
    "输入tokens",
    "输入 token",
    "输入token",
    "提示tokens",
}

OUTPUT_TOKEN_HEADERS = {
    "output_tokens",
    "completion_tokens",
    "output tokens",
    "completion tokens",
    "输出tokens",
    "输出 token",
    "输出token",
    "补全tokens",
}

TOTAL_TOKEN_HEADERS = {
    "tokens",
    "total_tokens",
    "total tokens",
    "token usage",
    "used tokens",
    "总tokens",
    "总 token",
    "总token",
    "token用量",
    "tokens用量",
}

REQUEST_HEADERS = {
    "requests",
    "request_count",
    "request count",
    "calls",
    "count",
    "api requests",
    "请求次数",
    "调用次数",
    "次数",
}

API_KEY_HEADERS = {
    "api_key",
    "api key",
    "key",
    "apikey",
    "密钥",
    "api密钥",
}


def main() -> None:
    """命令行测试入口。"""
    parser = argparse.ArgumentParser(description="导入 DeepSeek Usage 导出的 ZIP/CSV 文件")
    parser.add_argument("file", help="DeepSeek Usage 页面导出的 .zip 或 .csv 文件路径")
    args = parser.parse_args()

    try:
        result = import_usage_file(args.file)
    except UsageImportError as error:
        print(f"导入失败：{error}")
        return

    print(json.dumps(_mask_result_for_cli(result), ensure_ascii=False, indent=2))


def _mask_result_for_cli(result: dict[str, Any]) -> dict[str, Any]:
    """命令行输出时遮蔽 API Key，避免误泄露。"""
    safe_result = dict(result)
    masked_api_keys = {}

    for api_key, stats in result.get("api_keys", {}).items():
        masked_api_keys[_mask_secret(str(api_key))] = stats

    safe_result["api_keys"] = masked_api_keys
    return safe_result


def _mask_secret(value: str) -> str:
    """遮蔽密钥中间部分。"""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


if __name__ == "__main__":
    main()
