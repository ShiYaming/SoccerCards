"""eBay 官方 API 适配器。

两条数据线：
1. Browse API `item_summary/search` —— 活跃挂单（挂单价，供参考）。
2. Marketplace Insights API `search` —— 已售出记录（成交价，估值主数据）。

注意：legacy Finding API（findCompletedItems）已于 2025 年初退役。
需要 eBay 开发者账号的 Client ID / Client Secret / RuName。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
INSIGHTS_URL = "https://api.ebay.com/sell/marketplace_insights/v1_beta/search"


class EbayConfigError(RuntimeError):
    pass


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 20.0,
    ) -> None:
        if not client_id or not client_secret:
            raise EbayConfigError(
                "未配置 eBay 开发者密钥。请在 https://developer.ebay.com 注册账号，"
                "并将 EBAY_CLIENT_ID / EBAY_CLIENT_SECRET 填入 .env"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._token: str | None = None

    def _oauth_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            OAUTH_URL,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._oauth_token()}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Accept": "application/json",
        }

    def search_active(self, query: str, limit: int = 50) -> list[dict]:
        """活跃挂单（Browse API）。"""
        resp = requests.get(
            BROWSE_URL,
            headers=self._headers(),
            params={
                "q": query,
                "limit": min(limit, 200),
                "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("itemSummaries", [])

    def search_sold(
        self,
        query: str,
        *,
        days_back: int = 30,
        limit: int = 100,
    ) -> list[dict]:
        """已售出记录（Marketplace Insights API，Beta）。

        该接口的成交数据窗口较短（历史数据约 7 天 TTL），因此需要
        高频采集并入库积累历史。字段以实际响应为准，接入真实密钥后需校验。
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_back)
        date_filter = (
            f"itemEndDate:[{start.isoformat(timespec='seconds')}Z.."
            f"{now.isoformat(timespec='seconds')}Z]"
        )
        resp = requests.get(
            INSIGHTS_URL,
            headers=self._headers(),
            params={
                "q": query,
                "filter": date_filter,
                "limit": min(limit, 200),
                "sort": "itemEndDate",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    @staticmethod
    def normalize_sold(items: list[dict]) -> list[dict]:
        """把 API 原始响应归一化为统一的 sale 结构。"""
        sales = []
        for it in items:
            price = it.get("price", {})
            sales.append(
                {
                    "sold_at": it.get("itemEndDate"),
                    "platform": "eBay",
                    "price": float(price.get("value") or 0),
                    "currency": price.get("currency") or "USD",
                    "is_bin": it.get("buyingOptions", [None])[0] == "FIXED_PRICE",
                    "title": it.get("title"),
                    "raw": it,
                }
            )
        return sales
