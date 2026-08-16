"""特征工程：把库里的卡片/球员/系列/成交数据变成模型样本。

V1 特征（按预分析设计）：
- 卡片层：平行稀有度、限量印量、插入卡、系列规模、卡号
- 球员层：Transfermarkt 市值、年龄、位置
- 系列层：品牌、年份、系列热度（成交笔数）
- 市场层：单卡流动性、球员流动性
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from .config import config
from .identity import extract_insert_hint, extract_parallel


def _grade_tier(grade: str) -> int:
    g = (grade or "").upper()
    if g.startswith("PSA 10") or g.startswith("SGC 10") or g.startswith("BGS 10"):
        return 3
    if g.startswith("PSA 9") or g.startswith("SGC 9") or g.startswith("BGS 9"):
        return 2
    if g.startswith("PSA 8"):
        return 1
    return 0

# 平行稀有度分档（经验值，后续可用数据校准）
PARALLEL_TIER = {
    "": 0,
    "Refractor": 1,
    "Silver Refractor": 2,
    "Pulsar Refractor": 2,
    "Aqua Prism Refractor": 3,
    "Blue Lava Refractor": 3,
    "Pink Lava Refractor": 3,
    "Aqua Wave Refractor": 3,
    "Neon Green Wave Refractor": 3,
    "Pink Geo Refractor": 3,
    "Neon Green Lava Refractor": 3,
}


def _tier(parallel: str | None, serial: str | None) -> int:
    if serial:
        run = _print_run(serial)
        if run and run <= 25:
            return 5
        if run and run <= 99:
            return 4
        if run:
            return 3
    p = parallel or ""
    return PARALLEL_TIER.get(p, 2 if "Refractor" in p else 1)


def _print_run(serial: str | None) -> int | None:
    if not serial:
        return None
    m = re.match(r"(\d+)/(\d+)", serial)
    if m:
        return int(m.group(2))
    m2 = re.match(r"/(\d+)", serial)
    return int(m2.group(1)) if m2 else None


def _set_year(year: str | None) -> float:
    if not year:
        return 0.0
    m = re.match(r"(\d{4})", str(year))
    return float(m.group(1)) if m else 0.0


def _age(birth_date: str | None) -> float:
    if not birth_date:
        return 0.0
    m = re.search(r"\((\d+)\)", birth_date)
    if m:
        return float(m.group(1))
    return 0.0


def _position_flags(position: str | None) -> dict[str, int]:
    p = (position or "").lower()
    return {
        "pos_fw": int(any(k in p for k in ["winger", "forward", "striker", "attacking"])),
        "pos_mf": int(any(k in p for k in ["midfield", "midfielder", "central"])),
        "pos_df": int(any(k in p for k in ["defender", "back", "centre-back"])),
        "pos_gk": int("goalkeeper" in p),
    }


def _card_number_num(card_number: str | None) -> float:
    if not card_number:
        return 0.0
    m = re.match(r"(\d+)", card_number)
    return float(m.group(1)) if m else 0.0


def _fill_missing(df: pd.DataFrame) -> pd.DataFrame:
    """把 SQL NULL（pandas NaN）归一为可处理的空串/0。"""
    for col in ("serial", "parallel", "card_number", "position", "birth_date",
                "year", "set_name", "brand", "grade", "player_name", "title"):
        if col in df.columns:
            df[col] = df[col].fillna("")
    for col in ("market_value_eur", "price", "set_id", "player_id", "card_id"):
        if col in df.columns:
            df[col] = df[col].fillna(0)
    return df


def _load_rows() -> pd.DataFrame:
    """从数据库构建逐条成交的特征样本。"""
    con = sqlite3.connect(config.db_path)
    sql = """
        SELECT s.id AS sale_id, s.price, s.grade, s.sold_at, s.title,
               c.id AS card_id, c.card_number, c.parallel, c.serial,
               cs.id AS set_id, cs.name AS set_name, cs.brand, cs.year,
               p.id AS player_id, p.name AS player_name,
               p.market_value_eur, p.birth_date, p.position
        FROM sales s
        JOIN cards c ON c.id = s.card_id
        JOIN card_sets cs ON cs.id = c.set_id
        JOIN players p ON p.id = c.player_id
    """
    df = pd.read_sql_query(sql, con)

    # 流动性特征（用整库统计，避免泄漏用成交时间前的计数——MVP 先全量）
    liq = pd.read_sql_query(
        """
        SELECT card_id, COUNT(*) AS card_sales_count,
               SUM(CASE WHEN price < 5000 THEN 1 ELSE 0 END) AS card_sales_count_clean
        FROM sales GROUP BY card_id
        """,
        con,
    )
    play_liq = pd.read_sql_query(
        """
        SELECT p.id AS player_id, COUNT(*) AS player_sales_count
        FROM sales s JOIN cards c ON c.id = s.card_id JOIN players p ON p.id = c.player_id
        GROUP BY p.id
        """,
        con,
    )
    set_liq = pd.read_sql_query(
        """
        SELECT cs.id AS set_id, COUNT(*) AS set_sales_count
        FROM sales s JOIN cards c ON c.id = s.card_id JOIN card_sets cs ON cs.id = c.set_id
        GROUP BY cs.id
        """,
        con,
    )
    set_size = pd.read_sql_query(
        "SELECT set_id, COUNT(*) AS set_card_count FROM cards GROUP BY set_id", con
    )
    con.close()

    df = df.merge(liq, on="card_id", how="left")
    df = df.merge(play_liq, on="player_id", how="left")
    df = df.merge(set_liq, on="set_id", how="left")
    df = df.merge(set_size, on="set_id", how="left")

    df = _fill_missing(df)
    df["log_price"] = df["price"].map(lambda x: math.log(max(x, 0.01)))
    df["set_year"] = df["year"].map(_set_year)
    df["brand_topps"] = (df["brand"] == "Topps").astype(int)
    df["insert"] = df["set_name"].map(lambda n: int(" - " in (n or "")))
    df["parallel_tier"] = df.apply(lambda r: _tier(r["parallel"], r["serial"]), axis=1)
    df["print_run"] = df["serial"].map(_print_run).fillna(0.0)
    df["numbered"] = (df["print_run"] > 0).astype(int)
    df["card_no_num"] = df["card_number"].map(_card_number_num)
    df["grade_tier"] = df["grade"].map(_grade_tier)
    df["has_grade_label"] = (df["grade"] != "").astype(int)
    df["title_insert_hint"] = df["title"].map(extract_insert_hint).astype(int)
    df["title_has_parallel"] = df["title"].map(
        lambda t: int(extract_parallel(t) is not None)
    )
    df["log_market_value"] = df["market_value_eur"].map(
        lambda v: math.log10(max(v or 0, 1))
    )
    df["player_age"] = df["birth_date"].map(_age)
    for k in ("pos_fw", "pos_mf", "pos_df", "pos_gk"):
        df[k] = df["position"].map(lambda p: _position_flags(p)[k])
    df["card_sales_count"] = df["card_sales_count"].fillna(0).astype(int)
    df["player_sales_count"] = df["player_sales_count"].fillna(0).astype(int)
    df["set_sales_count"] = df["set_sales_count"].fillna(0).astype(int)
    df["set_card_count"] = df["set_card_count"].fillna(0).astype(int)
    return df


FEATURE_COLUMNS = [
    "set_year", "brand_topps", "insert", "parallel_tier", "print_run", "numbered",
    "card_no_num", "grade_tier", "has_grade_label",
    "title_insert_hint", "title_has_parallel",
    "log_market_value", "player_age",
    "pos_fw", "pos_mf", "pos_df", "pos_gk",
    "card_sales_count", "player_sales_count", "set_sales_count", "set_card_count",
]


def build_training_frame() -> pd.DataFrame:
    df = _load_rows()
    return df.dropna(subset=["log_price"])


def build_predict_row(card_id: int) -> pd.DataFrame:
    """为单张卡构建特征行（用于冷门卡推断）。"""
    df = _load_rows()
    card_rows = df[df["card_id"] == card_id]
    if card_rows.empty:
        con = sqlite3.connect(config.db_path)
        base = pd.read_sql_query(
            """
            SELECT c.id AS card_id, c.card_number, c.parallel, c.serial,
                   cs.id AS set_id, cs.name AS set_name, cs.brand, cs.year,
                   p.id AS player_id, p.market_value_eur, p.birth_date, p.position
            FROM cards c
            JOIN card_sets cs ON cs.id = c.set_id
            JOIN players p ON p.id = c.player_id
            WHERE c.id = ?
            """,
            con,
            params=(card_id,),
        )
        set_size = pd.read_sql_query(
            "SELECT set_id, COUNT(*) AS set_card_count FROM cards WHERE set_id = "
            "(SELECT set_id FROM cards WHERE id = ?) GROUP BY set_id",
            con,
            params=(card_id,),
        )
        con.close()
        if base.empty:
            raise KeyError(f"卡片 {card_id} 不存在")
        base["price"] = 0.0
        base["card_sales_count"] = 0
        base["player_sales_count"] = 0
        base["set_sales_count"] = 0
        base = base.merge(set_size, on="set_id", how="left")
        base = _fill_missing(base)
        return _augment(base.iloc[0:1])

    row = card_rows.iloc[0:1].copy()
    row["price"] = 0.0
    return row


def _augment(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("grade", "title", "serial", "parallel", "position", "birth_date",
                "year", "set_name", "brand", "card_number", "player_name"):
        if col not in df.columns:
            df[col] = ""
    df = _fill_missing(df)
    df["log_price"] = 0.0
    df["set_year"] = df["year"].map(_set_year)
    df["brand_topps"] = (df["brand"] == "Topps").astype(int)
    df["insert"] = df["set_name"].map(lambda n: int(" - " in (n or "")))
    df["parallel_tier"] = df.apply(lambda r: _tier(r["parallel"], r["serial"]), axis=1)
    df["print_run"] = df["serial"].map(_print_run).fillna(0.0)
    df["numbered"] = (df["print_run"] > 0).astype(int)
    df["card_no_num"] = df["card_number"].map(_card_number_num)
    df["grade_tier"] = df["grade"].map(_grade_tier)
    df["has_grade_label"] = (df["grade"] != "").astype(int)
    df["title_insert_hint"] = 0
    df["title_has_parallel"] = 0
    df["log_market_value"] = df["market_value_eur"].map(
        lambda v: math.log10(max(v or 0, 1))
    )
    df["player_age"] = df["birth_date"].map(_age)
    for k in ("pos_fw", "pos_mf", "pos_df", "pos_gk"):
        df[k] = df["position"].map(lambda p: _position_flags(p)[k])
    for c in ("card_sales_count", "player_sales_count", "set_sales_count", "set_card_count"):
        df[c] = df[c].fillna(0).astype(int)
    return df
