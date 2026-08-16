"""SQLite 存储层（PoC）。schema 设计为后续可平滑迁移到 PostgreSQL。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    transfermarkt_id TEXT,
    transfermarkt_url TEXT,
    club TEXT,
    nationality TEXT,
    position TEXT,
    birth_date TEXT,
    market_value_eur INTEGER,
    market_value_updated_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(transfermarkt_id)
);

CREATE TABLE IF NOT EXISTS card_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    brand TEXT,
    year TEXT,
    sport TEXT DEFAULT 'soccer',
    tcdb_set_id INTEGER,
    aliases TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id INTEGER NOT NULL REFERENCES card_sets(id),
    card_number TEXT,
    player_id INTEGER REFERENCES players(id),
    parallel TEXT,
    serial TEXT,
    variant TEXT,
    tcdb_card_id INTEGER,
    identity_key TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER REFERENCES cards(id),
    sold_at TEXT,
    platform TEXT,
    price REAL,
    currency TEXT DEFAULT 'USD',
    is_bin INTEGER,
    grade TEXT,
    cert_no TEXT,
    title TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sales_card_time ON sales(card_id, sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_card_grade ON sales(card_id, grade);

CREATE TABLE IF NOT EXISTS populations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER REFERENCES cards(id),
    grader TEXT,
    grade TEXT,
    count INTEGER,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(card_id, grader, grade)
);

CREATE TABLE IF NOT EXISTS valuations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER REFERENCES cards(id),
    grade TEXT,
    price REAL,
    low REAL,
    high REAL,
    sample_size INTEGER,
    method TEXT,
    window_days INTEGER,
    computed_at TEXT DEFAULT (datetime('now'))
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def conn(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def init(self) -> None:
        with self.conn() as con:
            con.executescript(SCHEMA)
            # 兼容已有库的增量迁移
            for sql in [
                "ALTER TABLE card_sets ADD COLUMN tcdb_set_id INTEGER",
                "ALTER TABLE card_sets ADD COLUMN aliases TEXT",
                "ALTER TABLE cards ADD COLUMN tcdb_card_id INTEGER",
            ]:
                try:
                    con.execute(sql)
                except sqlite3.OperationalError:
                    pass
            # 清理历史重复成交（保留最早一条），保证唯一索引可建
            con.execute(
                """
                DELETE FROM sales WHERE id NOT IN (
                    SELECT MIN(id) FROM sales
                    GROUP BY card_id, sold_at, price, title
                )
                """
            )
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_dedup "
                "ON sales(card_id, sold_at, price, title)"
            )
            # 玩家按名字合并（TCDB 与 Transfermarkt 可能建了重名球员；
            # 优先保留有市值/档案更全的那一行）
            con.execute(
                """
                UPDATE cards SET player_id = (
                    SELECT p2.id FROM players p2
                    WHERE p2.name = (SELECT name FROM players WHERE id = cards.player_id)
                    ORDER BY (p2.market_value_eur IS NOT NULL) DESC, p2.id ASC
                    LIMIT 1
                )
                """
            )
            con.execute(
                """
                DELETE FROM players WHERE id NOT IN (
                    SELECT p2.id FROM players p2 WHERE p2.id = (
                        SELECT p3.id FROM players p3
                        WHERE p3.name = p2.name
                        ORDER BY (p3.market_value_eur IS NOT NULL) DESC, p3.id ASC
                        LIMIT 1
                    )
                )
                """
            )
            # 重建身份键（合并玩家后可能产生重复身份）并把成交指向保留的卡片
            con.execute(
                """
                UPDATE cards SET identity_key = (
                    SELECT name FROM card_sets WHERE id = cards.set_id
                ) || '|' || COALESCE(card_number,'') || '|' || CAST(player_id AS TEXT)
                || '|' || COALESCE(parallel,'') || '|' || COALESCE(serial,'')
                || '|' || COALESCE(variant,'')
                """
            )
            con.execute(
                """
                UPDATE sales SET card_id = (
                    SELECT MIN(c.id) FROM cards c
                    WHERE c.identity_key = (SELECT identity_key FROM cards WHERE id = sales.card_id)
                )
                """
            )
            con.execute(
                "DELETE FROM cards "
                "WHERE id NOT IN (SELECT MIN(id) FROM cards GROUP BY identity_key)"
            )

    # ---- players ----
    def upsert_player(self, p: dict) -> int:
        with self.conn() as con:
            cur = con.execute(
                """
                INSERT INTO players (
                    name, transfermarkt_id, transfermarkt_url, club, nationality,
                    position, birth_date, market_value_eur, market_value_updated_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transfermarkt_id) DO UPDATE SET
                    name = excluded.name,
                    club = excluded.club,
                    nationality = excluded.nationality,
                    position = excluded.position,
                    birth_date = excluded.birth_date,
                    market_value_eur = excluded.market_value_eur,
                    market_value_updated_at = excluded.market_value_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    p["name"], p.get("transfermarkt_id"), p.get("transfermarkt_url"),
                    p.get("club"), p.get("nationality"), p.get("position"),
                    p.get("birth_date"), p.get("market_value_eur"),
                    p.get("market_value_updated_at"), utcnow(),
                ),
            )
            return cur.lastrowid

    def get_player(self, player_id: int) -> dict | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            return dict(row) if row else None

    def find_player_by_name(self, name: str) -> dict | None:
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM players WHERE lower(name) = lower(?)", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_players(self) -> list[dict]:
        with self.conn() as con:
            return [dict(r) for r in con.execute("SELECT * FROM players ORDER BY name")]

    # ---- sets / cards ----
    def get_or_create_set(
        self,
        name: str,
        brand: str | None = None,
        year: str | None = None,
        tcdb_set_id: int | None = None,
        aliases: list[str] | None = None,
    ) -> int:
        with self.conn() as con:
            row = con.execute("SELECT id FROM card_sets WHERE name = ?", (name,)).fetchone()
            if row:
                if tcdb_set_id is not None or aliases is not None:
                    con.execute(
                        "UPDATE card_sets SET tcdb_set_id = COALESCE(?, tcdb_set_id), "
                        "aliases = COALESCE(?, aliases) WHERE id = ?",
                        (tcdb_set_id, json.dumps(aliases, ensure_ascii=False) if aliases else None, row["id"]),
                    )
                return row["id"]
            cur = con.execute(
                "INSERT INTO card_sets (name, brand, year, tcdb_set_id, aliases) VALUES (?, ?, ?, ?, ?)",
                (name, brand, year, tcdb_set_id, json.dumps(aliases, ensure_ascii=False) if aliases else None),
            )
            return cur.lastrowid

    def get_set(self, set_id: int) -> dict | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM card_sets WHERE id = ?", (set_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("aliases"):
                d["aliases"] = json.loads(d["aliases"])
            return d

    def list_sets(self) -> list[dict]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT id, name, brand, year, aliases FROM card_sets ORDER BY id"
            ).fetchall()
            sets = []
            for r in rows:
                d = dict(r)
                if d.get("aliases"):
                    d["aliases"] = json.loads(d["aliases"])
                sets.append(d)
            return sets

    def get_or_create_player(self, name: str) -> int:
        name = name.strip()
        with self.conn() as con:
            row = con.execute(
                "SELECT id FROM players WHERE lower(name) = lower(?)", (name,)
            ).fetchone()
            if row:
                return row["id"]
            cur = con.execute("INSERT INTO players (name) VALUES (?)", (name,))
            return cur.lastrowid

    def upsert_card(
        self,
        set_name: str,
        player_id: int,
        *,
        brand: str | None = None,
        year: str | None = None,
        card_number: str | None = None,
        parallel: str | None = None,
        serial: str | None = None,
        variant: str | None = None,
        tcdb_card_id: int | None = None,
    ) -> int:
        set_id = self.get_or_create_set(set_name, brand, year)
        identity_key = "|".join(
            [set_name, card_number or "", str(player_id), parallel or "", serial or "", variant or ""]
        )
        with self.conn() as con:
            row = con.execute(
                "SELECT id FROM cards WHERE identity_key = ?", (identity_key,)
            ).fetchone()
            if row:
                if tcdb_card_id is not None:
                    con.execute(
                        "UPDATE cards SET tcdb_card_id = ? WHERE id = ?",
                        (tcdb_card_id, row["id"]),
                    )
                return row["id"]
            cur = con.execute(
                """
                INSERT INTO cards (set_id, card_number, player_id, parallel, serial,
                                   variant, tcdb_card_id, identity_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (set_id, card_number, player_id, parallel, serial, variant, tcdb_card_id, identity_key),
            )
            return cur.lastrowid

    def get_card(self, card_id: int) -> dict | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            return dict(row) if row else None

    def cards_in_set(self, set_id: int) -> list[dict]:
        with self.conn() as con:
            rows = con.execute(
                """
                SELECT c.id, c.card_number, c.parallel, c.serial, c.tcdb_card_id,
                       p.name AS player_name
                FROM cards c LEFT JOIN players p ON p.id = c.player_id
                WHERE c.set_id = ? ORDER BY c.card_number
                """,
                (set_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- sales ----
    def add_sale(
        self,
        card_id: int,
        *,
        sold_at: str,
        price: float,
        currency: str = "USD",
        platform: str = "manual",
        is_bin: bool | None = None,
        grade: str | None = None,
        cert_no: str | None = None,
        title: str | None = None,
        raw: dict | None = None,
    ) -> int | None:
        """插入一条成交；若与已有记录重复则忽略并返回 None。"""
        with self.conn() as con:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO sales (card_id, sold_at, platform, price, currency,
                                             is_bin, grade, cert_no, title, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id, sold_at, platform, price, currency,
                    1 if is_bin else 0 if is_bin is False else None,
                    grade, cert_no, title,
                    json.dumps(raw, ensure_ascii=False) if raw else None,
                ),
            )
            return cur.lastrowid if cur.rowcount == 1 else None

    def sales_for_card(self, card_id: int, grade: str | None = None) -> list[dict]:
        with self.conn() as con:
            if grade:
                rows = con.execute(
                    "SELECT * FROM sales WHERE card_id = ? AND grade = ? ORDER BY sold_at",
                    (card_id, grade),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM sales WHERE card_id = ? ORDER BY sold_at", (card_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def import_sales(self, card_id: int, sales: list[dict]) -> int:
        """批量导入已归一化的成交记录，返回导入条数。"""
        count = 0
        for s in sales:
            bin_raw = s.get("is_bin")
            if isinstance(bin_raw, str):
                bin_raw = bin_raw.strip().lower() in ("1", "true", "yes", "y")
            self.add_sale(
                card_id,
                sold_at=s.get("sold_at"),
                price=float(s["price"]),
                currency=s.get("currency", "USD"),
                platform=s.get("platform", "import"),
                is_bin=bin_raw,
                grade=s.get("grade"),
                cert_no=s.get("cert_no"),
                title=s.get("title"),
                raw=s.get("raw"),
            )
            count += 1
        return count

    # ---- valuations ----
    def save_valuation(self, card_id: int, grade: str | None, v: dict) -> int:
        with self.conn() as con:
            cur = con.execute(
                """
                INSERT INTO valuations (card_id, grade, price, low, high, sample_size,
                                        method, window_days, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id, grade, v.get("price"), v.get("low"), v.get("high"),
                    v.get("sample_size"), v.get("method"), v.get("window_days"), utcnow(),
                ),
            )
            return cur.lastrowid
