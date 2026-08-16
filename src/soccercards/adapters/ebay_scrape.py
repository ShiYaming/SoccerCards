"""eBay 已售搜索爬虫（Playwright 无头浏览器路径，无 API 密钥）。

背景：eBay 搜索页有 Akamai JS challenge，requests / curl_cffi 均被拦截
（本机实测 403 + splash 页）。真实浏览器能执行 challenge，因此用
Playwright 驱动 Chromium 抓取“已售”搜索结果。

安装（一次性）：
    pip install playwright
    playwright install chromium

注意：
- 这是 ToS 灰色地带，仅建议作为过渡/低频使用，控制请求频率。
- 若 Playwright 路径不稳定，推荐改用 Apify 云端采集（adapters/apify.py）。
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

EBAY_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class PlaywrightUnavailableError(RuntimeError):
    pass


def _parse_price(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"[\d,.]+", text.replace("US $", "").replace("$", ""))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _parse_sold_date(text: str) -> str | None:
    """'Sold Apr 12, 2026' → ISO 时间。"""
    if not text:
        return None
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}", text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0).replace(",", ""), "%b %d %Y").isoformat()
    except ValueError:
        return None


def search_sold(
    query: str,
    *,
    max_items: int = 60,
    headless: bool = True,
    timeout_ms: int = 60_000,
) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PlaywrightUnavailableError(
            "未安装 playwright。请先执行: pip install playwright && playwright install chromium\n"
            "若不想装浏览器，可用 Apify 云端采集（APIFY_TOKEN）或手动导入成交数据（import-sales）。"
        )

    search_url = "https://www.ebay.com/sch/i.html?" + urlencode(
        {
            "_nkw": query,
            "LH_Sold": 1,
            "LH_Complete": 1,
            "_ipg": min(max_items, 240),
        }
    )
    sales: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=EBAY_UA,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        # 先访问首页建立会话，降低被 challenge 的概率
        page.goto("https://www.ebay.com/", wait_until="domcontentloaded", timeout=timeout_ms)
        page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector("li.s-item", timeout=timeout_ms)

        nodes = page.locator("li.s-item").evaluate_all(
            """(els) => els.map(el => ({
                title: el.querySelector('.s-item__title')?.innerText || '',
                price: el.querySelector('.s-item__price')?.innerText || '',
                link: el.querySelector('.s-item__link')?.href || '',
                caption: el.querySelector('.s-item__caption')?.innerText || '',
            }))"""
        )
        browser.close()

    for n in nodes:
        price = _parse_price(n["price"])
        if price is None:
            continue
        m = re.search(r"/itm/(\d+)", n["link"]) or re.search(r"[?&]item=(\d+)", n["link"])
        sales.append(
            {
                "sold_at": _parse_sold_date(n["caption"]) or _parse_sold_date(n["title"]),
                "platform": "eBay(scrape)",
                "price": price,
                "currency": "USD",
                "is_bin": None,
                "title": n["title"],
                "item_id": m.group(1) if m else None,
                "raw": {"url": n["link"], "caption": n["caption"]},
            }
        )
    return sales[:max_items]
