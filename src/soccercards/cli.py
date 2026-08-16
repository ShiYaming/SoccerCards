"""命令行入口：python -m soccercards <subcommand>"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .config import config
from .db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soccercards", description="球星卡估价工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="初始化数据库 schema")

    p_tm = sub.add_parser("player", help="抓取 Transfermarkt 球员档案")
    p_tm.add_argument("name", help="球员名，如 'Lamine Yamal'")

    p_ebay = sub.add_parser("ebay", help="eBay 成交/挂单查询（需配置密钥）")
    p_ebay.add_argument("--query", required=True)
    p_ebay.add_argument("--sold", action="store_true", help="查已售出（默认查活跃挂单）")
    p_ebay.add_argument("--days", type=int, default=30)
    p_ebay.add_argument("--limit", type=int, default=20)

    p_scrape = sub.add_parser("ebay-scrape", help="无密钥抓 eBay 已售（需 playwright）")
    p_scrape.add_argument("--query", required=True)
    p_scrape.add_argument("--max-items", type=int, default=60)
    p_scrape.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    p_scrape.add_argument("--save-to-db", type=int, metavar="CARD_ID",
                          help="同时导入到指定卡片")
    p_scrape.add_argument("--grade", default=None)

    p_apify = sub.add_parser("apify", help="Apify 云端采集 eBay 已售（需 APIFY_TOKEN）")
    p_apify.add_argument("--query", required=True)
    p_apify.add_argument("--limit", type=int, default=60)
    p_apify.add_argument("--out", default=None, help="把归一化结果保存为 JSON 文件")

    p_import = sub.add_parser("import-sales", help="从 CSV/JSON 导入成交记录")
    p_import.add_argument("--card-id", type=int, required=True)
    p_import.add_argument("--file", required=True)

    p_tcdb = sub.add_parser("tcdb", help="从 TCDB 采集卡片主数据")
    tsub = p_tcdb.add_subparsers(dest="tcdb_cmd", required=True)
    p_sets = tsub.add_parser("sets", help="列出某运动/年份的系列")
    p_sets.add_argument("--sport", default="Soccer")
    p_sets.add_argument("--year", type=int, default=None)
    p_sets.add_argument("--filter", default=None, help="按关键字过滤系列名")
    p_check = tsub.add_parser("checklist", help="抓取系列 checklist 并入库")
    p_check.add_argument("--sid", type=int, required=True)
    p_check.add_argument("--name", default=None, help="系列名（缺省从 TCDB 自动获取）")
    p_check.add_argument("--brand", default=None)
    p_check.add_argument("--year", default=None)
    p_ins = tsub.add_parser("inserts", help="列出/入库系列下的插入卡系列")
    p_ins.add_argument("--sid", type=int, required=True)
    p_ins.add_argument("--name", default=None)
    p_ins.add_argument("--filter", default=None, help="只处理名称含该关键词的插入系列")
    p_ins.add_argument("--ingest", action="store_true", help="把匹配到的插入系列 checklist 也入库")
    p_ins.add_argument("--brand", default=None)
    p_ins.add_argument("--year", default=None)

    p_match = sub.add_parser("match", help="把 eBay 标题匹配到卡片身份")
    p_match.add_argument("--title", required=True)
    p_match.add_argument("--set-id", type=int, default=None)

    p_matchf = sub.add_parser("match-file", help="批量匹配成交文件里的标题")
    p_matchf.add_argument("--file", required=True)
    p_matchf.add_argument("--set-id", type=int, default=None)
    p_matchf.add_argument("--import", dest="do_import", action="store_true",
                          help="把匹配到的成交按身份入库（自动创建平行卡片）")

    p_ct = sub.add_parser("cardtao", help="卡淘中文市场已售成交")
    cts = p_ct.add_subparsers(dest="cardtao_cmd", required=True)
    p_cts = cts.add_parser("search", help="搜索已售成交")
    p_cts.add_argument("--keyword", required=True, help="中文关键词，如 亚马尔")
    p_cts.add_argument("--pages", type=int, default=1)
    p_cts.add_argument("--page-size", type=int, default=60)
    p_cts.add_argument("--out", default=None, help="保存归一化结果 JSON")
    p_cts.add_argument("--import", dest="do_import", action="store_true",
                       help="匹配并入库（自动识别系列）")
    p_cts.add_argument("--set-id", type=int, default=None)

    sub.add_parser("poc", help="运行端到端数据 PoC")

    p_est = sub.add_parser("estimate", help="对库内卡片跑 V0 估价")
    p_est.add_argument("--card-id", type=int, required=True)
    p_est.add_argument("--grade", default=None)

    sub.add_parser("train", help="训练 V1 特征回归模型（含交叉验证评估）")

    p_serve = sub.add_parser("serve", help="启动估价台 Web 服务")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    p_pred = sub.add_parser("predict", help="V1 模型 + V0 参考价混合估价")
    p_pred.add_argument("--card-id", type=int, required=True)
    p_pred.add_argument("--grade", default=None)
    p_pred.add_argument("--no-blend", action="store_true", help="只用模型，不混合 V0")

    args = parser.parse_args(argv)
    db = Database(config.db_path)
    db.init()  # 幂等：建表 + 增量迁移，保证每个命令都能跑在最新 schema 上

    if args.cmd == "init-db":
        db.init()
        print(f"数据库已初始化: {config.db_path}")
        return 0

    if args.cmd == "player":
        from .adapters import TransfermarktClient

        tm = TransfermarktClient(config.tm_user_agent, delay=config.request_delay)
        profile = tm.get_player(args.name)
        if not profile:
            print(f"未找到球员: {args.name}")
            return 1
        pid = db.upsert_player(profile)
        print(json.dumps({"id": pid, **profile}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "ebay":
        from .adapters.ebay import EbayClient, EbayConfigError

        try:
            client = EbayClient(config.ebay_client_id, config.ebay_client_secret)
        except EbayConfigError as e:
            print(f"[配置错误] {e}")
            return 2
        if args.sold:
            items = client.search_sold(args.query, days_back=args.days, limit=args.limit)
        else:
            items = client.search_active(args.query, limit=args.limit)
        print(json.dumps(items[: args.limit], ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "ebay-scrape":
        from .adapters.ebay_scrape import PlaywrightUnavailableError, search_sold

        try:
            sales = search_sold(
                args.query, max_items=args.max_items, headless=not args.headed
            )
        except PlaywrightUnavailableError as e:
            print(f"[依赖缺失] {e}")
            return 2
        if args.save_to_db:
            n = db.import_sales(args.save_to_db, sales)
            print(f"已导入 {n} 条成交到卡片 {args.save_to_db}")
        print(json.dumps(sales, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "apify":
        from .adapters.apify import ApifyEbayClient

        import os

        try:
            client = ApifyEbayClient(
                os.environ.get("APIFY_TOKEN", ""),
                actor_id=os.environ.get("EBAY_APIFY_ACTOR", "caffein.dev/ebay-sold-listings"),
            )
            sales = client.search_sold(args.query, limit=args.limit)
        except Exception as e:  # noqa: BLE001 - 统一隐藏网络细节，避免泄露 token
            print(f"[Apify 采集失败] {e}")
            return 1
        if args.out:
            out_path = args.out
            if not out_path.endswith(".json"):
                out_path += ".json"
            import os

            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(sales, f, ensure_ascii=False, indent=2)
            print(f"已保存 {len(sales)} 条到 {out_path}")
        print(json.dumps(sales, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "import-sales":
        path = args.file
        rows: list[dict] = []
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        else:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        n = db.import_sales(args.card_id, rows)
        print(f"已导入 {n} 条成交到卡片 {args.card_id}")
        return 0

    if args.cmd == "tcdb":
        from .adapters.tcdb import TcdbClient

        tm = TcdbClient(config.tm_user_agent, delay=max(config.request_delay, 2.0))
        if args.tcdb_cmd == "sets":
            sets = tm.list_sets(sport=args.sport, year=args.year)
            if args.filter:
                f = args.filter.lower()
                sets = [s for s in sets if f in s["name"].lower()]
            print(f"共 {len(sets)} 个系列")
            for s in sets[:60]:
                print(f"  {s['sid']}  {s['name']}")
            return 0

        if args.tcdb_cmd == "checklist":
            name = args.name or tm.get_set_name(args.sid)
            if not name:
                print("无法获取系列名，请用 --name 指定")
                return 1
            cards = tm.get_checklist(args.sid, set_name=name)
            set_id = db.get_or_create_set(
                name, brand=args.brand, year=args.year,
                tcdb_set_id=args.sid, aliases=[name],
            )
            n_cards = 0
            for c in cards:
                if not c["player_name"]:
                    continue
                pid = db.get_or_create_player(c["player_name"])
                db.upsert_card(
                    name, pid,
                    brand=args.brand, year=args.year,
                    card_number=c["card_number"],
                    tcdb_card_id=c["cid"],
                )
                n_cards += 1
            print(f"系列 [{name}] (sid={args.sid}): 抓取 {len(cards)} 条，入库 {n_cards} 张卡 (set_id={set_id})")
            return 0

        if args.tcdb_cmd == "inserts":
            parent_name = args.name or tm.get_set_name(args.sid)
            if not parent_name:
                print("无法获取系列名，请用 --name 指定")
                return 1
            inserts = tm.get_inserts(args.sid, set_name=parent_name)
            if args.filter:
                f = args.filter.lower()
                inserts = [i for i in inserts if f in i["name"].lower()]
            print(f"系列 {parent_name} 的插入系列: {len(inserts)} 个")
            for i in inserts[:40]:
                print(f"  {i['sid']}  {i['name']}")
            if args.ingest:
                parent = db.get_or_create_set(
                    parent_name, brand=args.brand, year=args.year,
                    tcdb_set_id=args.sid,
                )
                for i in inserts:
                    cards = tm.get_checklist(i["sid"], set_name=i["slug"])
                    set_name = f"{parent_name} - {i['name']}"
                    set_id = db.get_or_create_set(
                        set_name, brand=args.brand, year=args.year,
                        tcdb_set_id=i["sid"], aliases=[i["name"], set_name],
                    )
                    n = 0
                    for c in cards:
                        if not c["player_name"]:
                            continue
                        pid = db.get_or_create_player(c["player_name"])
                        db.upsert_card(
                            set_name, pid,
                            brand=args.brand, year=args.year,
                            card_number=c["card_number"],
                            tcdb_card_id=c["cid"],
                        )
                        n += 1
                    print(f"  入库 [{i['name']}] (sid={i['sid']}): {n} 张 -> set_id={set_id}")
            return 0

    if args.cmd == "match":
        from .identity import detect_set, match_card

        if args.set_id:
            cards = db.cards_in_set(args.set_id)
            if not cards:
                print(f"系列 {args.set_id} 还没有 checklist，先运行 tcdb checklist")
                return 1
            set_name = db.get_set(args.set_id)["name"]
        else:
            sets = db.list_sets()
            detected = detect_set(args.title, sets)
            if not detected:
                print("无法识别标题所属系列（无匹配系列）")
                return 1
            set_name = detected["name"]
            cards = db.cards_in_set(detected["id"])
        result = match_card(args.title, args.set_id, cards)
        result["set_name"] = set_name
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "match-file":
        with open(args.file, encoding="utf-8") as f:
            sales = json.load(f)
        stats, matched_rows, imported = _match_sales(
            sales, db, set_id=args.set_id, do_import=args.do_import
        )
        if args.do_import:
            print(f"已按身份入库 {imported} 条成交")
        print(f"共 {stats['total']} 条，匹配 {stats['matched']} 条 "
              f"(high={stats['high']}, medium={stats['medium']}, low={stats['low']})，"
              f"未匹配 {stats['unmatched']} 条")
        for r in matched_rows:
            mark = "✓" if r["card_id"] else "✗"
            print(f"  {mark} [{r['confidence']:6s}] #{r['card_number'] or '-':5s} "
                  f"{r['player_name'] or '-':22s} {r['parallel'] or '-':22s} "
                  f"{r['grade'] or '-':7s} ${r['price']}  [{r['set_name'] or '未识别'}]")
        return 0

    if args.cmd == "cardtao":
        from .adapters.cardtao import CardTaoClient

        client = CardTaoClient(config.tm_user_agent, delay=config.request_delay)
        sales = client.search_sold(
            args.keyword, pages=args.pages, page_size=args.page_size
        )
        print(f"卡淘已售: {len(sales)} 条 <- {args.keyword}")
        if args.out:
            out_path = args.out if args.out.endswith(".json") else args.out + ".json"
            import os

            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(sales, f, ensure_ascii=False, indent=2)
            print(f"已保存到 {out_path}")
        if args.do_import:
            stats, matched_rows, imported = _match_sales(
                sales, db, set_id=args.set_id, do_import=True
            )
            print(f"已按身份入库 {imported} 条成交")
            print(f"共 {stats['total']} 条，匹配 {stats['matched']} 条 "
                  f"(high={stats['high']}, medium={stats['medium']}, low={stats['low']})，"
                  f"未匹配 {stats['unmatched']} 条")
            for r in matched_rows[:25]:
                mark = "✓" if r["card_id"] else "✗"
                print(f"  {mark} [{r['confidence']:6s}] #{r['card_number'] or '-':5s} "
                      f"{r['player_name'] or '-':22s} ${r['price']}  [{r['set_name'] or '未识别'}]")
        return 0

    if args.cmd == "poc":
        from .poc import run_poc

        report = run_poc()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "estimate":
        from .valuation import estimate_from_sales

        sales = db.sales_for_card(args.card_id, grade=args.grade)
        if not sales:
            print(f"卡片 {args.card_id} 无成交数据")
            return 1
        est = estimate_from_sales(sales)
        db.save_valuation(args.card_id, args.grade, est)
        print(json.dumps(est, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "train":
        from .valuation.v1 import train_and_evaluate

        report = train_and_evaluate()
        print(json.dumps(
            {
                "samples": report["n_samples"],
                "cv": report["cv"],
                "feature_importance": report["feature_importance"],
            },
            ensure_ascii=False, indent=2,
        ))
        return 0

    if args.cmd == "predict":
        from .valuation.v1 import predict_card

        result = predict_card(args.card_id, grade=args.grade, blend=not args.no_blend)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("soccercards.api:app", host=args.host, port=args.port, log_level="warning")
        return 0

    parser.print_help()
    return 2


def _match_sales(sales: list[dict], db, set_id: int | None = None, do_import: bool = False):
    """批量匹配成交并（可选）按身份入库。返回 (stats, rows, imported)。"""
    from collections import Counter

    from .identity import detect_set, match_card

    all_sets = db.list_sets()
    stats = Counter()
    matched_rows = []
    imported = 0
    for s in sales:
        title = s.get("title") or ""
        if set_id:
            cards = db.cards_in_set(set_id)
            set_name = db.get_set(set_id)["name"]
            sid = set_id
        else:
            detected = detect_set(title, all_sets)
            set_name = detected["name"] if detected else None
            cards = db.cards_in_set(detected["id"]) if detected else []
            sid = detected["id"] if detected else None
        r = match_card(title, sid, cards) if sid else {
            "card_id": None, "card_number": None, "player_name": None,
            "confidence": "none", "matched_by": [], "grade": None,
            "serial": None, "parallel": None, "score": 0,
        }
        r["set_name"] = set_name
        r["price"] = s.get("price")
        r["sold_at"] = s.get("sold_at")
        matched_rows.append(r)
        stats["total"] += 1
        if r["card_id"]:
            stats["matched"] += 1
            if r["confidence"] == "high":
                stats["high"] += 1
            elif r["confidence"] == "medium":
                stats["medium"] += 1
            else:
                stats["low"] += 1
        else:
            stats["unmatched"] += 1
        if do_import and r["card_id"] and r["confidence"] != "low":
            card = db.get_card(r["card_id"])
            if card:
                cur_set = db.get_set(sid)
                is_insert_set = " - " in cur_set["name"]
                new_card_id = db.upsert_card(
                    cur_set["name"],
                    card["player_id"],
                    brand=cur_set.get("brand"),
                    year=cur_set.get("year"),
                    card_number=r["card_number"],
                    parallel=None if is_insert_set else r["parallel"],
                    serial=r["serial"],
                )
                added = db.add_sale(
                    new_card_id,
                    sold_at=r["sold_at"],
                    price=r["price"],
                    platform=s.get("platform", "import"),
                    grade=r["grade"],
                    title=title,
                    raw=s.get("raw"),
                )
                if added is not None:
                    imported += 1
    return stats, matched_rows, imported


if __name__ == "__main__":
    sys.exit(main())
