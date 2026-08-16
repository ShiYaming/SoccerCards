"""TCDB（The Trading Card Database）适配器：足球卡系列与 checklist 主数据。

数据源结构（2026-08 实测）：
- 系列列表：/ViewAll.cfm/sp/Soccer/year/{year}
- 系列页：/ViewSet.cfm/sid/{sid}
- 完整清单：/Checklist.cfm/sid/{sid}?PageIndex={n}（每页 300 张）
- 卡片链接：/ViewCard.cfm/sid/{sid}/cid/{cid}/{set-slug}-{card-no}-{player}

TCDB 命名与 eBay 俗称不同（如 eBay 写 "2023 Topps Chrome UEFA"，
TCDB 为 "2023-24 Topps Chrome UEFA Club Competitions"），
匹配时需用别名表，见 identity.py 的 SET_ALIASES。
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE = "https://www.tcdb.com"


class TcdbClient:
    def __init__(self, user_agent: str, delay: float = 2.0, timeout: float = 25.0) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.delay = delay
        self.timeout = timeout

    def _get(self, url: str, **kw) -> requests.Response:
        resp = None
        for attempt in range(4):
            time.sleep(self.delay)
            resp = self.session.get(url, timeout=self.timeout, **kw)
            if resp.status_code < 500:
                return resp
            # 503 多半是限流：退避重试
            time.sleep(10 * (attempt + 1))
        return resp

    def list_sets(self, sport: str = "Soccer", year: int | None = None) -> list[dict]:
        """按运动/年份列出系列。"""
        url = f"{BASE}/ViewAll.cfm/sp/{quote(sport)}"
        if year:
            url += f"/year/{year}"
        resp = self._get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        sets = []
        seen = set()
        for a in soup.select("a[href*='ViewSet.cfm/sid/']"):
            href = a.get("href", "")
            m = re.search(r"sid/(\d+)", href)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            sets.append(
                {
                    "sid": int(m.group(1)),
                    "name": a.get_text(" ", strip=True),
                    "url": BASE + href,
                }
            )
        return sets

    def get_set_name(self, sid: int) -> str | None:
        """从系列页的 Checklist 链接里提取系列全名。"""
        resp = self._get(f"{BASE}/ViewSet.cfm/sid/{sid}")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select(f"a[href*='Checklist.cfm/sid/{sid}/']"):
            name = a.get("href").split("/", 5)[-1]
            if name:
                return name
        return None

    def get_checklist(
        self, sid: int, set_name: str | None = None, max_pages: int = 10
    ) -> list[dict]:
        """抓取系列完整 checklist，返回 [{cid, card_number, player_name}]。"""
        if set_name and " " in set_name:
            set_name = re.sub(r"[^A-Za-z0-9]+", "-", set_name).strip("-")
        # 注意：不带系列名 slug 的 URL 会返回空页（2026-08 实测）
        base = f"{BASE}/Checklist.cfm/sid/{sid}"
        if set_name:
            base += f"/{set_name}"
        items: dict[int, dict] = {}
        for page in range(1, max_pages + 1):
            url = base
            if page > 1:
                url += f"?PageIndex={page}"
            resp = self._get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            found = 0
            for a in soup.select(f"a[href*='/ViewCard.cfm/sid/{sid}/cid/']"):
                m = re.search(r"cid/(\d+)/([^?]+)", a.get("href", ""))
                if not m:
                    continue
                cid = int(m.group(1))
                if cid in items:
                    continue
                parsed = self._parse_slug(m.group(2))
                items[cid] = {
                    "cid": cid,
                    "card_number": parsed[0],
                    "player_name": parsed[1],
                    "url": BASE + a.get("href").split("?")[0],
                }
                found += 1
            if found == 0:
                break
        return list(items.values())

    def get_inserts(self, sid: int, set_name: str | None = None) -> list[dict]:
        """列出系列的插入卡/平行系列（TCDB 把每个平行/插入卡做成独立 set）。

        链接形如 /Checklist.cfm/sid/{insert_sid}/{主系列}---{插入名}。
        """
        if set_name and " " in set_name:
            set_name = re.sub(r"[^A-Za-z0-9]+", "-", set_name).strip("-")
        base = f"{BASE}/Inserts.cfm/sid/{sid}"
        if set_name:
            base += f"/{set_name}"
        resp = self._get(base)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        inserts: dict[int, dict] = {}
        for a in soup.select("a[href*='/Checklist.cfm/sid/']"):
            m = re.search(r"sid/(\d+)/([^?]+)", a.get("href", ""))
            if not m:
                continue
            isid = int(m.group(1))
            slug = m.group(2)
            if isid in inserts:
                continue
            # 插入名在 slug 的 "---" 之后；文本链接优先用锚文本
            name = a.get_text(" ", strip=True) or None
            if not name or len(name) < 3:
                if "---" in slug:
                    name = slug.split("---", 1)[1].replace("-", " ")
            if not name:
                continue
            inserts[isid] = {
                "sid": isid,
                "name": name.strip(),
                "slug": m.group(2),
                "url": BASE + a.get("href").split("?")[0],
            }
        return list(inserts.values())

    @staticmethod
    def _parse_slug(slug: str) -> tuple[str | None, str]:
        """从卡片链接 slug 解析卡号与球员名。

        slug 形如 "2023-24-Topps-Chrome-UEFA-Club-Competitions-64-Lamine-Yamal"，
        去掉系列前缀后，剩余部分以 "-{卡号}-{球员}" 结尾（球员名可能含连字符）。
        """
        # 去掉系列 slug 前缀：找最后一个 "-\d+[a-z]?-" 模式，其前为系列名
        m = re.search(r"-(\d+[a-z]?)-([A-Za-zÀ-ž' .-]+)$", slug)
        if not m:
            return None, slug
        return m.group(1), m.group(2).strip().replace("-", " ")
