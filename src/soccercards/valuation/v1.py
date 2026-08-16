"""V1 特征回归模型：训练、评估、预测，并与 V0 参考价混合。"""

from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import GroupKFold

from ..config import config
from ..features import FEATURE_COLUMNS, build_predict_row, build_training_frame
from .v0 import estimate_from_sales

MODEL_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "model_v1.pkl"


def _back_transform(pred_log: np.ndarray) -> np.ndarray:
    return np.exp(np.clip(pred_log, -3, 12))


def _mape(truth: np.ndarray, pred: np.ndarray) -> float:
    """价格尺度的中位绝对百分比误差（对离群值稳健）。"""
    return float(np.median(np.abs(pred / np.maximum(truth, 0.01) - 1)) * 100)


def train_and_evaluate() -> dict:
    """训练 + 按卡片分组的交叉验证评估，返回指标并保存模型。"""
    df = build_training_frame()
    n_raw = len(df)
    # 剔除"挑卡/自选"类散装低价成交（Complete Your Set / You Pick，非单卡估值样本）
    df = df[~((df["title_insert_hint"] == 1) & (df["price"] < 10))].copy()
    # 缩尾：避免个别天价/低价样本过度影响回归
    lo_q, hi_q = df["log_price"].quantile(0.02), df["log_price"].quantile(0.98)
    df["log_price"] = df["log_price"].clip(lo_q, hi_q)
    X = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = df["log_price"].to_numpy(dtype=float)
    groups = df["card_id"].to_numpy()

    models = {
        "ridge": RidgeCV(alphas=[1e-2, 1e-1, 1, 1e1, 1e2]),
        "rf": RandomForestRegressor(
            n_estimators=400, max_depth=8, min_samples_leaf=4,
            max_features=0.5, random_state=42, n_jobs=-1,
        ),
    }
    results = {}
    gkf = GroupKFold(n_splits=5)
    for name, model in models.items():
        mape_list, rmse_list = [], []
        for train_idx, test_idx in gkf.split(X, y, groups):
            m = model.__class__(**model.get_params()) if name == "rf" else RidgeCV(
                alphas=[1e-2, 1e-1, 1, 1e1, 1e2]
            )
            m.fit(X[train_idx], y[train_idx])
            pred = _back_transform(m.predict(X[test_idx]))
            truth = np.exp(y[test_idx])
            mape_list.append(_mape(truth, pred))
            rmse_list.append(float(np.sqrt(np.mean((np.log(pred) - y[test_idx]) ** 2))))
        results[name] = {
            "mape_pct": round(float(np.mean(mape_list)), 1),
            "rmse_log": round(float(np.mean(rmse_list)), 3),
            "samples": int(len(df)),
        }
    results["_raw_samples"] = int(n_raw)

    # 全量数据再训一个随机森林用于预测（CV 结果见上）
    final = RandomForestRegressor(
        n_estimators=400, max_depth=8, min_samples_leaf=4,
        max_features=0.5, random_state=42, n_jobs=-1,
    )
    final.fit(X, y)
    payload = {
        "model": final,
        "feature_columns": FEATURE_COLUMNS,
        "feature_importance": dict(
            zip(FEATURE_COLUMNS, [round(float(v), 4) for v in final.feature_importances_])
        ),
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "n_samples": len(df),
        "cv": results,
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(payload, f)
    return payload


def _load_model() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError("模型未训练，先运行: python -m soccercards train")
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def predict_card(card_id: int, grade: str | None = None, blend: bool = True, db=None) -> dict:
    """单卡估价：V0 参考价 + V1 模型 + 混合值。"""
    from ..db import Database

    payload = _load_model()
    model = payload["model"]
    row = build_predict_row(card_id)
    X = row[payload["feature_columns"]].to_numpy(dtype=float).reshape(1, -1)
    model_price = float(_back_transform(model.predict(X))[0])

    if db is None:
        db = Database(config.db_path)
        db.init()
    sales = db.sales_for_card(card_id, grade=grade)
    v0 = estimate_from_sales(sales) if sales else None

    if not blend or not v0 or not v0.get("price"):
        final_price, method = model_price, "v1_model"
    else:
        n = v0["sample_size"]
        w = min(0.8, n / 8.0)
        final_price = w * v0["price"] + (1 - w) * model_price
        method = f"v1_blend_v0(w={w:.2f})"

    return {
        "card_id": card_id,
        "model_price": round(model_price, 2),
        "v0_price": round(v0["price"], 2) if v0 and v0.get("price") else None,
        "v0_low": round(v0["low"], 2) if v0 and v0.get("low") else None,
        "v0_high": round(v0["high"], 2) if v0 and v0.get("high") else None,
        "v0_n": v0["sample_size"] if v0 else 0,
        "final_price": round(final_price, 2),
        "method": method,
    }
