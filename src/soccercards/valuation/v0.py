"""V0 参考价模型。

逻辑：
1. 按窗口（30/90/365 天）分组，取成交价。
2. 清洗：剔除非正价格，用 IQR 剔除极端值（防 1 美元垃圾价、1/1 天价）。
3. 选择“样本量 >= 3 的最小窗口”作为主窗口；样本不足则扩大到下一档。
4. 输出中位数、区间（10–90 分位）、样本量、趋势（主窗口 vs 上一档中位数）。
5. 样本过少时明确返回“数据不足”，不硬给单一价格。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _clean_prices(prices: list[float]) -> list[float]:
    valid = [p for p in prices if p and p > 0]
    if len(valid) < 4:
        return valid
    valid.sort()
    q1 = valid[len(valid) // 4]
    q3 = valid[3 * len(valid) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
    return [p for p in valid if lo <= p <= hi]


def _window_sales(sales: list[dict], days: int) -> list[float]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    prices = []
    for s in sales:
        sold_at = s.get("sold_at")
        if not sold_at:
            continue
        try:
            dt = datetime.fromisoformat(sold_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            prices.append(float(s["price"]))
    return _clean_prices(prices)


def _percentile(sorted_prices: list[float], p: float) -> float:
    if not sorted_prices:
        return 0.0
    k = (len(sorted_prices) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_prices) - 1)
    return sorted_prices[f] + (sorted_prices[c] - sorted_prices[f]) * (k - f)


def estimate_from_sales(
    sales: list[dict],
    *,
    windows: tuple[int, ...] = (30, 90, 365),
    min_samples: int = 3,
) -> dict:
    """sales: [{sold_at, price}]。返回估值结果 dict。"""
    window_stats: dict[int, dict] = {}
    for days in windows:
        prices = _window_sales(sales, days)
        if not prices:
            continue
        prices.sort()
        window_stats[days] = {
            "n": len(prices),
            "median": _percentile(prices, 0.5),
            "trimmed_mean": sum(prices) / len(prices),
            "low": _percentile(prices, 0.10),
            "high": _percentile(prices, 0.90),
            "latest": prices[-1],
        }

    if not window_stats:
        return {
            "price": None,
            "low": None,
            "high": None,
            "sample_size": 0,
            "method": "insufficient_data",
            "window_days": None,
            "windows": {},
        }

    # 选样本量达标的最小窗口
    primary_days = next(
        (d for d in windows if d in window_stats and window_stats[d]["n"] >= min_samples),
        max(window_stats),
    )
    primary = window_stats[primary_days]

    # 趋势：主窗口 vs 更大一档窗口
    larger = [d for d in windows if d > primary_days and d in window_stats]
    trend_pct = None
    if larger and window_stats[larger[0]]["n"] >= min_samples:
        base = window_stats[larger[0]]["median"]
        if base > 0:
            trend_pct = round((primary["median"] - base) / base * 100, 1)

    return {
        "price": round(primary["median"], 2),
        "low": round(primary["low"], 2),
        "high": round(primary["high"], 2),
        "sample_size": primary["n"],
        "method": "v0_reference" if primary["n"] >= min_samples else "v0_low_sample",
        "window_days": primary_days,
        "trend_pct": trend_pct,
        "windows": {str(d): w for d, w in window_stats.items()},
    }
