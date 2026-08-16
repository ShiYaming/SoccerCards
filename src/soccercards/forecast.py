"""估价预测引擎（MVP：动量外推 + 置信区间）。

方法说明（透明可解释）：
1. 基准价 = V0/V1 混合当前估值（predict_card）。
2. 动量 = 近 180 天成交价的 log-线性斜率（每日漂移率），
   按样本量衰减、并钳制在 ±0.4%/天，防止小样本外推出离谱数字。
3. 预测价(t) = 基准价 × e^(r·t)；置信带 = 基准价 × e^((r±σ)·t)，
   σ 随样本量增大而收窄（5 笔以上更稳）。
4. 无成交的冷门卡：r=0（走平），置信带更宽。

后续可替换为更复杂的预测器（大赛周期、球员身价趋势、搜索热度等），
接口保持不变。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import config
from .valuation.v1 import predict_card

MAX_DAILY_DRIFT = 0.002  # ±0.2%/天（约 ±70%/年上限，保守外推）
LOOKBACK_DAYS = 180


def _momentum(sales: list[dict]) -> tuple[float, float, int]:
    """返回 (每日漂移率 r, 每日波动 σ, 有效样本数)。"""
    n = len(sales)
    if n < 3:
        return 0.0, 0.008, n
    now = datetime.now(timezone.utc)
    xs, ys = [], []
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
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
        if dt < cutoff:
            continue
        price = float(s["price"])
        if price <= 0:
            continue
        xs.append(max((now - dt).total_seconds() / 86400.0, 0.0))
        ys.append(math.log(price))
    if len(xs) < 3:
        return 0.0, 0.008, len(xs)
    x = np.array(xs)
    y = np.array(ys)
    slope = float(np.polyfit(x, y, 1)[0])  # d(ln p)/d(day)，负=越近越涨
    damp = min(1.0, len(xs) / 6.0)
    r = float(np.clip(-slope, -MAX_DAILY_DRIFT, MAX_DAILY_DRIFT)) * damp
    sigma = 0.002 + 0.006 * (1.0 - min(1.0, len(xs) / 8.0))
    return r, sigma, len(xs)


def forecast_card(card_id: int, horizons: tuple[int, ...] = (90, 180, 365), db=None) -> dict:
    """对单卡输出未来多时点估价与置信带。"""
    from .db import Database

    if db is None:
        db = Database(config.db_path)
        db.init()
    val = predict_card(card_id, db=db)
    base = val["final_price"] or val["model_price"] or 0.0
    sales = db.sales_for_card(card_id)
    r, sigma, n = _momentum(sales)

    points = []
    for h in horizons:
        value = base * math.exp(r * h)
        low = base * math.exp((r - sigma) * h)
        high = base * math.exp((r + sigma) * h)
        points.append(
            {
                "days": h,
                "label": f"{h}天",
                "value": round(value, 2),
                "low": round(low, 2),
                "high": round(high, 2),
            }
        )
    return {
        "card_id": card_id,
        "base_value": round(base, 2),
        "daily_drift_pct": round(r * 100, 3),
        "sigma_daily_pct": round(sigma * 100, 3),
        "method": "momentum_extrapolation",
        "n_sales_used": n,
        "points": points,
        "valuation": val,
    }
