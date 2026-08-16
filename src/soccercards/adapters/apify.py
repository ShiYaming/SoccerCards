"""Apify 云端采集适配器（eBay 已售数据，无需 eBay 开发者审核）。

路径说明：eBay 官方 API 需要开发者密钥（审核耗时），而 eBay 搜索页在本机
被 Akamai 反爬拦截。Apify 上的 eBay 采集 actor 由平台托管、维护反爬，
注册即有免费额度，是当前最省事的替代路径。

使用：
1. 注册 https://console.apify.com 获取 API token（免费额度）。
2. 默认使用 caffein.dev/ebay-sold-listings（只返回真实已售，含成交价/
   结束时间/成交方式），输入字段已对齐；换其他 actor 时在
   EBAY_APIFY_ACTOR_INPUT 里覆盖输入。
3. 将 token 填入 .env：APIFY_TOKEN=xxx
"""

from __future__ import annotations

import json
import re
from datetime import datetime

import requests

API_BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    pass


def _api_actor_id(actor_id: str) -> str:
    """Apify API 的 actor ID 格式为 username~name；兼容 'username/name' 写法。"""
    if "~" not in actor_id and "/" in actor_id:
        return actor_id.replace("/", "~", 1)
    return actor_id


class ApifyEbayClient:
    def __init__(
        self,
        token: str,
        *,
        actor_id: str = "caffein.dev/ebay-sold-listings",
        actor_input: dict | None = None,
        timeout: float = 300.0,
    ) -> None:
        if not token:
            raise ApifyError(
                "未配置 APIFY_TOKEN。注册 https://console.apify.com 获取 token，填入 .env"
            )
        self.token = token
        self.actor_id = actor_id
        self.actor_input = actor_input or {}
        self.timeout = timeout

    def search_sold(self, query: str, limit: int = 60) -> list[dict]:
        """同步运行 actor 并直接取回数据集（run-sync-get-dataset-items）。"""
        payload = {
            "keywords": [query],
            "count": limit,
            "daysToScrape": 30,
            "ebaySite": "ebay.com",
            "categoryId": "0",
            "includeCompletedListings": True,
            **self.actor_input,
        }
        url = (
            f"{API_BASE}/acts/{_api_actor_id(self.actor_id)}/run-sync-get-dataset-items"
            f"?token={self.token}&timeout={int(self.timeout)}"
        )
        resp = requests.post(url, json=payload, timeout=self.timeout + 30)
        if resp.status_code >= 400:
            raise ApifyError(
                f"Apify 调用失败 {resp.status_code}: {resp.text[:300]}"
            )
        try:
            items = resp.json()
        except ValueError:
            raise ApifyError("Apify 返回的不是 JSON，可能 actor 不存在或额度不足")
        if not isinstance(items, list):
            raise ApifyError(f"Apify 返回格式异常: {str(items)[:200]}")
        return self.normalize(items)

    @staticmethod
    def normalize(items: list[dict]) -> list[dict]:
        """把 Apify actor 的常见输出字段归一化为统一 sale 结构。

        不同 actor 字段名不同，这里做常见别名映射；接入具体 actor 后
        如字段缺失，在 _aliases 里补充即可。
        """
        aliases = {
            "title": ["title", "name", "listingTitle"],
            "price": ["soldPrice", "price", "priceValue", "currentPrice"],
            "currency": ["soldCurrency", "currency", "currencyCode"],
            "sold_at": ["endedAt", "soldDate", "endTime", "itemEndDate", "soldAt"],
            "item_id": ["itemId", "itemID", "id"],
            "url": ["url", "itemUrl", "viewItemURL"],
            "is_bin": ["listingType", "buyingFormat", "buyingOptions"],
        }

        def pick(item: dict, keys: list[str]):
            for k in keys:
                if isinstance(item, dict) and item.get(k) not in (None, ""):
                    return item[k]
            return None

        sales = []
        for it in items:
            price = pick(it, aliases["price"])
            try:
                price_f = float(re.sub(r"[^\d.]", "", str(price))) if price else 0.0
            except ValueError:
                price_f = 0.0
            sold_at = pick(it, aliases["sold_at"])
            if sold_at:
                try:
                    sold_at = datetime.fromisoformat(
                        str(sold_at).replace("Z", "+00:00")
                    ).isoformat(timespec="seconds")
                except ValueError:
                    pass
            bin_opt = pick(it, aliases["is_bin"])
            is_bin = None
            if isinstance(bin_opt, list):
                is_bin = "FIXED_PRICE" in bin_opt or "Buy It Now" in bin_opt
            elif isinstance(bin_opt, str):
                b = bin_opt.lower()
                is_bin = b in ("buy_it_now", "buyitnow") or "fix" in b or "buy it now" in b
            sales.append(
                {
                    "sold_at": sold_at,
                    "platform": "eBay(via Apify)",
                    "price": price_f,
                    "currency": (pick(it, aliases["currency"]) or "USD").upper(),
                    "is_bin": is_bin,
                    "title": pick(it, aliases["title"]),
                    "raw": it,
                }
            )
        return sales
