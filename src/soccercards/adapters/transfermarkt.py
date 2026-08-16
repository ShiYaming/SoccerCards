"""Transfermarkt 适配器：球员元数据与市场价值（作为估值特征，非成交价）。"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche"
PROFILE_URL = "https://www.transfermarkt.com"


def _parse_market_value(text: str) -> int | None:
    """解析 '€ 220.00 m' / '€ 750 k' / '€ 1.5 b' 形式的文本。"""
    if not text:
        return None
    m = re.search(r"€\s*([\d.,]+)\s*([mkb])\b", text, re.I)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[unit]
    return int(amount * multiplier)


class TransfermarktClient:
    """极简客户端：搜索球员 → 抓取档案页 → 返回结构化字段。"""

    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 20.0) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.delay = delay
        self.timeout = timeout

    def _get(self, url: str, **kwargs) -> requests.Response:
        time.sleep(self.delay)
        return self.session.get(url, timeout=self.timeout, **kwargs)

    def search(self, query: str) -> list[dict]:
        """搜索球员，返回 [{name, url, id}]，按相关性排序。"""
        resp = self._get(SEARCH_URL, params={"query": query})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        seen = set()
        for a in soup.select("a[href*='/profil/spieler/']"):
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            player_id = href.rstrip("/").split("/")[-1]
            name = a.get("title") or a.get_text(" ", strip=True)
            results.append(
                {"name": name, "url": PROFILE_URL + href, "transfermarkt_id": player_id}
            )
        return results

    def get_player(self, query: str) -> dict | None:
        """按名字搜索并返回第一个球员的完整档案。"""
        hits = self.search(query)
        if not hits:
            return None
        return self.get_profile(hits[0])

    def get_profile(self, player: dict) -> dict:
        resp = self._get(player["url"])
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        def text_of(selector: str) -> str | None:
            el = soup.select_one(selector)
            return el.get_text(" ", strip=True) if el else None

        mv_wrapper = soup.select_one("a.data-header__market-value-wrapper")
        mv_text = mv_wrapper.get_text(" ", strip=True) if mv_wrapper else None

        positions = [e.get_text(" ", strip=True) for e in soup.select("dd[class*='position']")]

        profile = {
            "name": player.get("name") or text_of("h1"),
            "transfermarkt_id": player.get("transfermarkt_id"),
            "transfermarkt_url": player.get("url"),
            "club": text_of("span[itemprop='affiliation']"),
            "nationality": text_of("span[itemprop='nationality']"),
            "position": ", ".join(positions) or None,
            "birth_date": text_of("span[itemprop='birthDate']"),
            "market_value_eur": _parse_market_value(mv_text),
            "market_value_updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return profile
