"""130point 适配器（默认禁用）。

PoC 结论（2026-08-16）：130point 由 Cloudflare 全面防护，
requests / curl_cffi(chrome/safari) 均返回 403。要接入需要：
- 无头浏览器（playwright）+ 代理池，成本高、稳定性差；
- 或改用第三方代理采集服务（如 Apify/openwire），注意 ToS 风险。

因此 MVP 成交价主数据源定为 eBay 官方 API，此适配器暂不启用。
"""

from __future__ import annotations


class ThirteenPointClient:
    enabled = False

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "130point 采集被 Cloudflare 阻断，MVP 阶段不启用。"
            "成交价请走 eBay Marketplace Insights API。"
        )
