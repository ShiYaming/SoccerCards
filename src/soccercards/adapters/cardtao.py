"""卡淘（Card Hobby）适配器：中文球星卡平台的已售成交数据。

实测结论（2026-08-16）：
- 主域 cardtao.com 从本机不可达（SSL/502），可用域名是 www.cardhobby.com.cn。
- 搜索接口：GET /NewCommodity/SearchCommodity
  - 必须带 Referer（否则返回空结果）
  - searchJson = [{"Key":"Status","Value":-2}] 表示"已售"（1=出售中）
  - 返回字段：LowestPrice（成交价 ¥）、USD_LowestPrice（美元折算）、
    LastOnTime（成交时间 ms）、ByWay（2=竞价 / 1=一口价 / 议价）、Title、SellRealName

注意：卡淘标题多为中文混合（如 "2026 Topps UEFA 亚马尔 巴塞罗那"），
需要先做球员中文别名翻译再走统一的标题匹配器。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import requests

SEARCH_URL = "https://www.cardhobby.com.cn/NewCommodity/SearchCommodity"
REFERER = "https://www.cardhobby.com.cn/market/search?searchtype=1"


class CardTaoError(RuntimeError):
    pass


def _parse_ms_time(value) -> str | None:
    """'/Date(1786762140000)/' → ISO 时间。"""
    if not value:
        return None
    m = re.search(r"(\d{10,13})", str(value))
    if not m:
        return None
    ms = int(m.group(1))
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


class CardTaoClient:
    def __init__(self, user_agent: str, delay: float = 1.5, timeout: float = 25.0) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": REFERER,
            }
        )
        self.delay = delay
        self.timeout = timeout

    def search_sold(
        self,
        keyword: str,
        *,
        pages: int = 1,
        page_size: int = 60,
    ) -> list[dict]:
        """搜索已售成交，返回归一化记录。"""
        sales: list[dict] = []
        for page in range(1, pages + 1):
            params = {
                "userId": "",
                "pageIndex": page,
                "pageSize": page_size,
                "searchKey": keyword,
                "searchJson": json.dumps([{"Key": "Status", "Value": -2}]),
                "sort": "",
                "sortType": "",
            }
            time.sleep(self.delay)
            resp = self.session.get(SEARCH_URL, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                raise CardTaoError(f"卡淘接口 HTTP {resp.status_code}")
            try:
                payload = resp.json()
            except ValueError:
                raise CardTaoError("卡淘接口返回非 JSON（可能被限流）")
            data = payload.get("data") or {}
            items = data.get("PagedMarketItemList") or []
            if not items:
                break
            for it in items:
                sales.append(self._normalize(it))
            total = data.get("TotalCount")
            if total and len(sales) >= int(total):
                break
        return sales

    @staticmethod
    def _normalize(it: dict) -> dict:
        title = it.get("Title") or ""
        price_cny = it.get("LowestPrice") or it.get("Price")
        usd_price = it.get("USD_LowestPrice") or it.get("USD_Price")
        try:
            price_usd = float(usd_price) if usd_price else None
        except (TypeError, ValueError):
            price_usd = None
        try:
            price_cny_f = float(price_cny) if price_cny else None
        except (TypeError, ValueError):
            price_cny_f = None
        # 统一折算为 USD（平台提供折算价）；CNY 保留在 raw 里
        if price_usd is None and price_cny_f is not None:
            price_usd = round(price_cny_f / 6.7, 2)
        sold_at = _parse_ms_time(it.get("LastOnTime")) or it.get("EffectiveDate")
        by_way = it.get("ByWay")
        return {
            "sold_at": sold_at,
            "platform": "CardTao",
            "price": price_usd if price_usd is not None else price_cny_f,
            "currency": "USD" if price_usd is not None else "CNY",
            "is_bin": by_way == 1,
            "title": title,
            "raw": {
                "item_id": it.get("ID"),
                "price_cny": price_cny_f,
                "price_usd": price_usd,
                "by_way": by_way,
                "seller": it.get("SellRealName"),
                "effective_date": it.get("EffectiveDate"),
                "status": it.get("Status"),
            },
        }
