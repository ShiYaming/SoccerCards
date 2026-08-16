"""FastAPI 后端：检索、榜单、卡片详情、估价与预测。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from .config import config
from .db import Database
from .forecast import forecast_card
from .valuation.v0 import estimate_from_sales
from .valuation.v1 import predict_card

app = FastAPI(title="SoccerCards 估价台", version="0.2.0")

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
db = Database(config.db_path)
db.init()

from .identity import PLAYER_ZH_ALIASES

# 检索用英文短名（中文别名 → 英文全名 → 短名）
PLAYER_ZH = {zh: en.split()[-1] for zh, en in PLAYER_ZH_ALIASES.items()}


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path)
    con.row_factory = sqlite3.Row
    return con


def _row_to_card(r: sqlite3.Row) -> dict:
    return {
        "card_id": r["id"],
        "player": r["player"],
        "club": r["club"],
        "set_name": r["set_name"],
        "card_number": r["card_number"],
        "parallel": r["parallel"],
        "market_value_eur": r["market_value_eur"],
        "n_sales": r["n_sales"],
        "avg_price": r["avg_price"],
        "median_price": r["median_price"],
    }


@app.get("/api/overview")
def overview():
    con = _conn()
    stats = {
        "sets": con.execute("SELECT COUNT(*) FROM card_sets").fetchone()[0],
        "cards": con.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
        "sales": con.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
        "players": con.execute("SELECT COUNT(*) FROM players").fetchone()[0],
    }
    sets_breakdown = [
        dict(r)
        for r in con.execute(
            """
            SELECT cs.name, COUNT(DISTINCT c.id) cards, COUNT(s.id) sales
            FROM card_sets cs
            LEFT JOIN cards c ON c.set_id = cs.id
            LEFT JOIN sales s ON s.card_id = c.id
            GROUP BY cs.id ORDER BY sales DESC
            """
        )
    ]
    con.close()
    top = _search_cards(limit=12, order_by="sales")
    return {"stats": stats, "sets_breakdown": sets_breakdown, "top_cards": top}


@app.get("/api/sets")
def sets():
    con = _conn()
    rows = [
        dict(r)
        for r in con.execute(
            """
            SELECT cs.id, cs.name, cs.brand, cs.year, COUNT(DISTINCT c.id) cards,
                   COUNT(s.id) sales
            FROM card_sets cs
            LEFT JOIN cards c ON c.set_id = cs.id
            LEFT JOIN sales s ON s.card_id = c.id
            GROUP BY cs.id ORDER BY cs.name
            """
        )
    ]
    con.close()
    return rows


def _search_cards(limit: int = 50, order_by: str = "sales", q: str = "", set_id: int | None = None):
    con = _conn()
    sql = """
        SELECT c.id, p.name AS player, p.club, p.market_value_eur,
               cs.name AS set_name, c.card_number, c.parallel,
               (SELECT COUNT(*) FROM sales s WHERE s.card_id = c.id) AS n_sales,
               (SELECT ROUND(AVG(price),2) FROM sales s WHERE s.card_id = c.id) AS avg_price
        FROM cards c
        JOIN card_sets cs ON cs.id = c.set_id
        JOIN players p ON p.id = c.player_id
    """
    params: list = []
    where = []
    if q:
        patterns = [q]
        for zh, en in PLAYER_ZH.items():
            if zh in q:
                patterns.append(q.replace(zh, en))
        ors = []
        for pat in set(patterns):
            like = f"%{pat}%"
            ors.append(
                "(p.name LIKE ? OR cs.name LIKE ? OR c.card_number LIKE ? OR c.parallel LIKE ?)"
            )
            params += [like, like, like, like]
        where.append("(" + " OR ".join(ors) + ")")
    if set_id:
        where.append("cs.id = ?")
        params.append(set_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    if order_by == "sales":
        sql += " ORDER BY n_sales DESC, avg_price DESC"
    else:
        sql += " ORDER BY p.market_value_eur DESC NULLS LAST, n_sales DESC"
    sql += " LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    for r in rows:
        r["card_id"] = r.pop("id")
    # 中位数：一次性取回所有相关成交价，Python 侧计算（规避 SQLite OFFSET 子查询坑）
    ids = [r["card_id"] for r in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        grouped: dict[int, list[float]] = {}
        for card_id, price in con.execute(
            f"SELECT card_id, price FROM sales WHERE card_id IN ({placeholders}) "
            "ORDER BY card_id, price",
            ids,
        ):
            grouped.setdefault(card_id, []).append(price)
        for r in rows:
            ps = grouped.get(r["card_id"], [])
            r["median_price"] = round(ps[len(ps) // 2], 2) if ps else None
    con.close()
    for r in rows:
        try:
            fc = forecast_card(r["card_id"], db=db)
            r["current_value"] = fc["base_value"]
            r["forecast"] = {p["label"]: p["value"] for p in fc["points"]}
        except Exception:
            r["current_value"] = None
            r["forecast"] = {}
    return rows


@app.get("/api/cards")
def search_cards(
    q: str = Query("", description="球员/系列/卡号/平行关键字"),
    set_id: int | None = None,
    limit: int = Query(50, le=100),
):
    return _search_cards(limit=limit, q=q, set_id=set_id)


@app.get("/api/cards/{card_id}")
def card_detail(card_id: int):
    con = _conn()
    row = con.execute(
        """
        SELECT c.id, p.name AS player, p.club, p.position, p.nationality,
               p.market_value_eur, p.birth_date,
               cs.name AS set_name, cs.brand, cs.year, c.card_number, c.parallel
        FROM cards c
        JOIN card_sets cs ON cs.id = c.set_id
        JOIN players p ON p.id = c.player_id
        WHERE c.id = ?
        """,
        (card_id,),
    ).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "卡片不存在")
    sales = [dict(r) for r in con.execute(
        """
        SELECT sold_at, price, currency, grade, platform, title
        FROM sales WHERE card_id = ? ORDER BY sold_at DESC LIMIT 60
        """,
        (card_id,),
    )]
    con.close()

    card = dict(row)
    card["sales"] = sales
    card["v0"] = estimate_from_sales(sales)
    try:
        card["valuation"] = predict_card(card_id, db=db)
        card["forecast"] = forecast_card(card_id, db=db)
    except Exception as e:
        card["valuation"] = None
        card["forecast"] = {"error": str(e)}
    return card


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
