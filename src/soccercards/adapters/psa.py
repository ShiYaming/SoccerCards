"""PSA 数据适配器（占位）。

计划能力：
- 人口报告（population report）：某卡各评级数量 → 稀缺性特征。
- Auction Prices Realized：评级卡拍卖成交（补充 eBay 的高端成交样本）。

PSA 官网无正式公开 API；其前端使用内部 JSON 端点，需要抓包确认，
或用 Apify 等第三方爬虫服务。此模块先留接口，PoC 阶段不做实现。
"""

from __future__ import annotations


def fetch_population(card_name: str) -> dict | None:
    """TODO: 按卡名查询人口报告。返回 {grader: {grade: count}} 或 None。"""
    raise NotImplementedError("PSA population adapter 尚未实现（需抓包确认内部端点）")


def fetch_auction_prices(player: str, set_name: str) -> list[dict]:
    """TODO: 查询 PSA Auction Prices Realized。"""
    raise NotImplementedError("PSA APR adapter 尚未实现")
