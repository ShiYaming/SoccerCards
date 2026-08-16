# SoccerCards · 球星卡二级市场估价工具

针对足球球星卡（Topps Chrome UEFA、Panini Prizm World Cup 等）的二级市场估价工具。

> 📄 完整产品文档见 [PRD.md](PRD.md)（设计思路 / 功能 / 不足 / 优化建议）

## 当前状态

PoC 骨架已完成，包含：

- 数据模型：球员 / 系列 / 卡片身份 / 成交 / 人口 / 估值（SQLite，可迁 Postgres）
- 数据源适配器：Transfermarkt（可用）、eBay 官方 API（待密钥）、PSA（占位）、130point（禁用）
- 无密钥替代数据线：Apify 云端采集（推荐）、Playwright 本机爬取、CSV/JSON 手动导入
- 卡片主数据：TCDB checklist/插入系列采集 + 系列识别层 + eBay 标题 → 卡片身份 匹配器
- V0 估价引擎：窗口参考价 + IQR 清洗 + 置信区间 + 趋势
- V1 特征回归模型：21 维特征 + 交叉验证 + V0/模型混合估价
- Web 估价台：检索（中/英）、主流卡片榜单、卡片详情、3/6/12 个月预测图表
- 卡淘中文市场：已售成交采集（中文关键词 + 中文球员别名翻译）
- CLI 与端到端 PoC

## 快速开始

```bash
cd SoccerCards
export PYTHONPATH=src

# 1. 初始化数据库
python3 -m soccercards init-db

# 2. 抓取球员档案（Transfermarkt，无需密钥）
python3 -m soccercards player "Lamine Yamal"

# 3. 运行端到端 PoC（联网抓球员 + 演示成交 + V0 估价）
python3 -m soccercards poc

# 4. eBay 查询（需要先在 .env 配置开发者密钥）
cp .env.example .env
python3 -m soccercards ebay --query "Lamine Yamal 2023 Topps Chrome Refractor" --sold --days 30

# 5. 替代路径 A：Apify 云端采集（无需 eBay 审核，需 APIFY_TOKEN）
python3 -m soccercards apify --query "Lamine Yamal 2023 Topps Chrome Refractor" --limit 60

# 6. 替代路径 B：Playwright 本机爬 eBay 已售（需 pip install playwright && playwright install chromium）
python3 -m soccercards ebay-scrape --query "Lamine Yamal 2023 Topps Chrome Refractor" --save-to-db 1

# 7. 替代路径 C：手动导入成交 CSV 后估价（不依赖任何采集）
python3 -m soccercards import-sales --card-id 1 --file examples/sales_import_sample.csv
python3 -m soccercards estimate --card-id 1 --grade "PSA 10"

# 8. 卡片主数据：列出 TCDB 足球系列 / 抓取 checklist 入库
python3 -m soccercards tcdb sets --year 2023 --filter "Chrome UEFA"
python3 -m soccercards tcdb checklist --sid 434800 --brand Topps --year "2023-24"
python3 -m soccercards tcdb inserts --sid 434800 --filter wonderkid --ingest

# 9. 标题 → 卡片身份：单条匹配 / 批量匹配并自动入库
python3 -m soccercards match --title "2023-24 Topps Chrome UEFA Lamine Yamal #64 Silver Refractor PSA 9" --set-id 3
python3 -m soccercards match-file --file data/raw/yamal_refractor.json --set-id 3 --import

# 10. V1 模型：训练评估 / 单卡估价（V0 + 模型混合）
python3 -m soccercards train
python3 -m soccercards predict --card-id 1268

# 11. 启动 Web 估价台（浏览器打开 http://127.0.0.1:8123）
PYTHONPATH=src .venv/bin/python -m soccercards serve --port 8123

# 12. 卡淘中文市场已售（关键词搜索 + 匹配入库）
PYTHONPATH=src .venv/bin/python -m soccercards cardtao search --keyword "亚马尔" --pages 2 --import
```

## 配置

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 用途 |
| --- | --- |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | eBay 开发者应用密钥（成交价数据线必需） |
| `APIFY_TOKEN` | Apify 云端采集 token（无需 eBay 审核的替代路径） |
| `EBAY_APIFY_ACTOR` | Apify Store 中的 eBay 采集 actor ID |
| `DB_PATH` | SQLite 路径，默认 `data/soccercards.db` |
| `TM_USER_AGENT` | Transfermarkt 请求 UA |
| `REQUEST_DELAY_SECONDS` | 采集请求间隔，防封 |

eBay 开发者账号申请：<https://developer.ebay.com>

## PoC 结论（2026-08-16）

| 数据线 | 状态 | 说明 |
| --- | --- | --- |
| Transfermarkt | ✅ 可用 | 搜索 + 档案页（市场价值/俱乐部/国籍/位置）稳定 |
| eBay 官方 API | ⏳ 待密钥 | 适配器已写好，审核通过后配置密钥即可跑 |
| eBay 公开搜索页 | ❌ 本机直连被拦 | Akamai JS challenge（requests/curl_cffi 均 403），走 Apify 或 Playwright |
| 130point | ❌ 不可用 | Cloudflare 全面阻断，MVP 不启用 |
| PSA 人口报告 | ⏳ 待实现 | 需抓包确认内部端点，或用第三方服务 |
| Apify 云端采集 | ✅ 已验证 | 真实采集 30 条 Yamal 成交，单次约 $0.08（$2.5/千条） |
| 手动导入 | ✅ 可用 | CSV/JSON → import-sales → estimate，零依赖闭环 |
| TCDB 卡片主数据 | ✅ 已验证 | 足球系列覆盖全，checklist 可抓（见下） |
| 卡淘中文市场 | ✅ 已验证 | 已售接口可采（见下） |

## 多系列覆盖与系列识别（2026-08-16）

- 已入库 7 个 TCDB 系列、1,278 张卡：
  - 2023-24 Topps Chrome UEFA Club Competitions（235 条）
  - 2023-24 Merlin UEFA Club Competitions（151 条）
  - 2022 Panini Prizm FIFA World Cup（300 条）
  - 2023-24 Panini Prizm Premier League（300 条）
  - 2023-24 Topps Chrome Bundesliga（100 条）
  - Chrome UEFA 插入系列：Wonderkids（10 条）、Pulsar Refractor（200 条）
- **系列识别层**（identity.py `detect_set`）：从标题识别所属系列，插入卡名（如 Wonderkids）优先级高于产品名（Chrome UEFA/Merlin），并处理了 TCDB 与 eBay 的命名差异。
- 30 条真实成交自动识别 + 匹配：**28/30**（22 高置信 / 6 中置信），Wonderkids 3 笔 → 插入系列、Merlin 2 笔 → Merlin #27、Pulsar 4 笔 → Pulsar Refractor 系列；2 笔 2026 NSCC（不在库中）正确标记未识别。
- 数据管道已具备幂等性：重复导入同一批成交不会产生重复记录（唯一索引 + INSERT OR IGNORE）。

## 卡淘中文市场接入（2026-08-16）

- 主域 `cardtao.com` 本机不可达（SSL/502），实际可用域名：`www.cardhobby.com.cn`。
- 已售接口：`GET /NewCommodity/SearchCommodity`，`searchJson=[{"Key":"Status","Value":-2}]` 表示已售（1=出售中），**必须带 Referer 头**。
- 实测：搜索「亚马尔」2 页得 120 条真实已售（¥ 成交价 + 平台美元折算 + 成交时间 + 卖家）。
- 中文标题匹配：`translate_title` 把中文球员别名（亚马尔 → Lamine Yamal）翻译后走统一匹配器；120 条中 22 条匹配到库内卡片（1 高 / 8 中 / 13 低置信），9 条入库（Messi/Ronaldo/Yamal/Bellingham 的 Prizm WC / Merlin 卡）。
- **已知局限**：卡淘标题中文混杂、含大量不在库内系列的产品（Topps Living、laurent milestone 等），且有多卡打包（如"梅西 C罗 打包"）——按单卡价格理解需人工甄别。低匹配率符合预期，可作为中文市场参考价，不建议直接混入模型训练标签。

## 踩坑记录（供后续参考）

- TCDB 有反爬限流：请求间隔建议 ≥2s，503 自动退避重试（已内置）。
- TCDB checklist URL 必须带系列名 slug（大小写敏感），且不能全小写。
- eBay 标题 "2023/24" 是赛季年份，不是限量号（正则已加年份护栏）。
- "#2" 不能匹配 "#27"（卡号匹配加了词边界）。
- 同一球员可能同时来自 Transfermarkt 与 TCDB checklist，入库时按名字合并（已内置迁移）。

## V1 特征回归模型（2026-08-16）

### 数据

- 真实成交 240 笔（Apify 采集 9 个查询，约 $0.7 额度），覆盖 7 个系列、21 位球员。
- 球员特征：18/21 球员补全 Transfermarkt 市值（€1.8M–€220M）。

### 特征（21 维）

- 卡片层：平行稀有度分档、限量印量、插入卡、卡号
- 评级层：评级档位（PSA10=3/PSA9=2/PSA8=1）、是否有评级标签
- 球员层：市值（log10）、年龄、位置（FW/MF/DF/GK）
- 系列层：品牌、年份、系列规模、系列热度
- 市场层：单卡流动性、球员流动性、标题插入卡提示、标题平行提示

### 结果（按卡片分组的 5 折交叉验证）

| 模型 | MAPE（中位误差率） | RMSE(log) | 说明 |
| --- | --- | --- | --- |
| Ridge（对数价格） | **79.7%** | 1.64 | 当前最优，用于预测 |
| RandomForest | 125% | 1.63 | 小样本下过拟合更明显 |

基线对比：不加评级/标题特征时 Ridge MAPE 152%；加评级档位 + 标题提示后降至 79.7%。
特征重要性前五：评级档位 > 是否有评级标签 > 卡号 > 球员流动性 > 标题平行提示。

### 混合估价

`predict` 输出三层：V0 参考价（真实成交）、V1 模型价、混合价
（按样本量加权：`w = min(0.8, n/8)`，样本越多越信 V0）。冷门卡无成交时直接用模型推断。

示例：

- Yamal Silver Refractor（6 笔成交）：V0 $293.5 + 模型 $383.3 → 混合 $316
- Wonderkids Yamal（3 笔）：V0 $31.7 + 模型 $55.4 → 混合 $46.5
- Wirtz Bundesliga 基卡（13 笔）：V0 $60 + 模型 $12 → 混合 $50.4

### 已知局限（诚实评估）

- 模型整体 MAPE ~80%，离产品目标（<25%）还有距离。**瓶颈不是模型，是标签质量**：
  - 评级标签覆盖率仅 22%（其余靠证书号反查 PSA 才能补）；
  - 平行标签覆盖率仅 19%（大量 Prizm 平行/插入卡被归到基卡身份，如 Mbappé 基卡被低估到 $12）；
  - 样本量小（240 笔）。
- 下一步杠杆：PSA 证书号评级归因 → 完整平行/插入卡系列入库 → 扩大采样。数据质量到位后，同一套模型管道可直接提升到目标精度。

## Web 估价台（2026-08-16）

纯静态前端（无 CDN 依赖）+ FastAPI 后端，启动后浏览器打开 `http://127.0.0.1:8123`。

### 功能

- **主流卡片榜单**：按成交热度排序 Top 12，展示球员 / 系列 / 卡号 / 平行 / 成交笔数 / 均价 / 中位价 / 当前估值 / 3·6·12 个月预测。
- **检索**：支持中英文球员名（哈兰德 ↔ Haaland）、系列名、卡号、平行；系列下拉过滤。
- **卡片详情**：点击行展开——球员市值、成交均价/中位价、当前估值（V0+模型混合）、成交价格散点图、未来估价曲线（含置信区间带）、最近成交明细。
- **预测方法**：当前估值 × 近 180 天成交动量外推（日漂移 ±0.2% 上限、按样本量衰减），冷门卡走平、置信带更宽；页面内附方法说明。

### API

| 接口 | 说明 |
| --- | --- |
| `GET /api/overview` | 统计 + 主流卡片榜单 + 系列分布 |
| `GET /api/sets` | 系列列表（含卡片/成交数） |
| `GET /api/cards?q=&set_id=&limit=` | 检索卡片（含估值与预测） |
| `GET /api/cards/{id}` | 卡片详情（成交、V0/V1 估值、预测序列） |

### 已知显示问题（数据层，非前端）

榜单「均价」与「当前估值」可能差距大（如梅西 Prizm WC 基卡均价 $401 vs 中位价 $19）：
原因是基卡身份里混入了插入卡/平行成交（标题未标注）。中位价与当前估值更接近真实水平，
彻底解决需评级归因 + 完整平行/插入卡系列入库（见路线图）。

## Apify 实测结论（2026-08-16）

- 使用的 actor：`caffein.dev/ebay-sold-listings`（只返回真实已售，含成交价/结束时间/成交方式/运费/卖家信誉）。
- 实测查询 `Lamine Yamal 2023 Topps Chrome UEFA Refractor`，30 条成交，价格 $22–$1,462，全部为近 30 天真实成交。
- 数据已验证入库并跑通 V0 估价。原始数据保存在 `data/raw/yamal_refractor.json`。
- **重要教训**：同一搜索词混着大量平行（Silver/Pulsar/Aqua Prism/Neon Green Wave…）和评级（PSA 9/10/裸卡），混合估价中位数 $305、区间 $35–$925 基本无意义；按「Silver Refractor + PSA 9」分组后（2 条：$337/$411）估值为 $374。**卡片身份主数据（TCDB）是下一步的必做项**。
- 另一个真实数据质量问题：很多标题只有证书号后缀（如 `&07231`）不带评级，评级需靠证书号反查 PSA。

## TCDB 卡片主数据实测（2026-08-16）

- **命名差异**：eBay 俗称 "2023 Topps Chrome UEFA" 在 TCDB 里是 `2023-24 Topps Chrome UEFA Club Competitions`（sid=434800），需要别名映射（见 `identity.py` 的 `SET_ALIASES`）。
- checklist 结构：`/Checklist.cfm/sid/{sid}/{set-name}`，每页 300 张，`?PageIndex=N` 翻页；卡片链接含 `cid` + 卡号 + 球员名。
- 实测：抓取 2023-24 Topps Chrome UEFA Club Competitions 共 235 条（含变体），入库 211 张卡。
- **匹配结果**：30 条真实 eBay 成交全部匹配到 Lamine Yamal #64（19 条高置信 / 11 条中置信），自动按平行建身份并入库 11 个变体，分平行估价：Silver Refractor 6 笔 → $293.5，Pulsar Refractor 4 笔 → $284。
- **已知边界**：插入卡（如 Wonderkids #WK-3）和跨系列标题（Merlin/NSCC）会匹配到基础卡 #64，需后续接入 TCDB 插入卡系列 + 系列识别层解决。

## 无密钥替代路径怎么选

| 路径 | 成本 | 可靠性 | 适用 |
| --- | --- | --- | --- |
| Apify 云端采集 | 免费额度起，按次计费 | 高（平台托管反爬） | **推荐**：正式采集前的主力 |
| Playwright 本机爬取 | 免费，装浏览器 | 中（反爬升级会失效） | 低频、个人试用 |
| 手动导入 CSV | 免费 | 高（人工） | 先跑通估价闭环 |
| Card Ladder / Market Movers | 付费订阅 | 高 | 产品成型后买基准数据 |

## 目录结构

```text
src/soccercards/
├── cli.py              # 命令行入口
├── config.py           # 配置加载
├── db.py               # SQLite schema 与访问层
├── poc.py              # 端到端 PoC
├── adapters/
│   ├── transfermarkt.py  # 球员数据 ✅
│   ├── ebay.py           # 成交/挂单数据（官方 API）
│   ├── apify.py          # Apify 云端 eBay 已售 ✅
│   ├── tcdb.py           # TCDB 卡片主数据 ✅
│   ├── psa.py            # 人口报告（占位）
│   └── thirteen_point.py # 130point（禁用）
├── identity.py         # eBay 标题 → 卡片身份（匹配器）
├── forecast.py         # 预测引擎（动量外推 + 置信区间）
├── api.py              # FastAPI 后端
└── valuation/
    ├── v0.py           # V0 参考价引擎
    └── v1.py           # V1 特征回归 + 混合估价

static/
├── index.html          # 估价台页面
├── app.js              # 前端逻辑（检索/图表/详情）
└── style.css           # 样式
```

## 路线图

1. ✅ PoC 骨架 + Transfermarkt 数据线验证
2. ✅ Apify 成交数据线 + 真实数据入库
3. ✅ TCDB 卡片主数据 + 标题匹配器（2023-24 Chrome UEFA 已验证）
4. ⏳ 覆盖更多系列（Merlin / Prizm WC / Prizm EPL）+ 插入卡系列
5. ✅ 系列识别层（跨系列自动归位）
6. ✅ V1 特征回归 + V0/模型混合估价（MVP 精度，待数据质量提升）
7. ✅ Web 估价台（检索/榜单/详情/预测图）
8. ⏳ 评级归因（PSA 证书号反查）→ 完整平行/插入卡入库 → 精度提升
