"""eBay 标题 → 卡片身份 的归一化与匹配。

MVP 策略（规则优先，后续可加模型）：
1. 从标题提取 评级 / 限量号 / 平行关键词。
2. 在指定系列内，用「球员名 + 卡号」双重信号匹配 checklist 卡片。
3. 输出统一身份：{set, card_number, player, parallel, grade, serial}。
"""

from __future__ import annotations

import re
import unicodedata

# eBay 俗称 → TCDB 系列名（核心映射，可随覆盖系列扩充）
SET_ALIASES: dict[str, str] = {
    "2023 topps chrome uefa": "2023-24 Topps Chrome UEFA Club Competitions",
    "2023 topps chrome uefa champions league": "2023-24 Topps Chrome UEFA Club Competitions",
    "topps chrome uefa 2023": "2023-24 Topps Chrome UEFA Club Competitions",
    "2023-24 topps chrome uefa": "2023-24 Topps Chrome UEFA Club Competitions",
    "2023-24 merlin uefa": "2023-24 Merlin UEFA Club Competitions",
    "topps chrome merlin uefa": "2023-24 Merlin UEFA Club Competitions",
    "2022 panini prizm world cup": "2022 Panini Prizm FIFA World Cup",
    "2022 panini prizm fifa world cup": "2022 Panini Prizm FIFA World Cup",
    "prizm world cup": "2022 Panini Prizm FIFA World Cup",
    "2023-24 panini prizm premier league": "2023-24 Panini Prizm Premier League",
    "prizm premier league": "2023-24 Panini Prizm Premier League",
    "prizm epl": "2023-24 Panini Prizm Premier League",
    "2023-24 topps chrome bundesliga": "2023-24 Topps Chrome Bundesliga",
    "chrome bundesliga": "2023-24 Topps Chrome Bundesliga",
}

# 从系列名提取的强区分关键词（用于标题 → 系列识别）
# 优先级：插入卡/子系列(10) > 具体产品(5)，同优先级取最长匹配
SET_KEYWORDS: dict[str, tuple[str, int]] = {
    "wonderkid": ("2023-24 Topps Chrome UEFA Club Competitions - Wonderkids", 10),
    "merlin": ("2023-24 Merlin UEFA Club Competitions", 5),
    "prizm premier": ("2023-24 Panini Prizm Premier League", 5),
    "prizm": ("2022 Panini Prizm FIFA World Cup", 5),
    "bundesliga": ("2023-24 Topps Chrome Bundesliga", 5),
    "chrome uefa": ("2023-24 Topps Chrome UEFA Club Competitions", 5),
}

PARALLEL_KEYWORDS = [
    "silver refractor", "pulsar refractor", "aqua prism refractor",
    "neon green wave refractor", "aqua wave refractor", "pink lava refractor",
    "blue lava refractor", "neon green lava refractor", "pink geo refractor",
    "refractor", "hyper prism", "mojo refractor", "gold wave",
    "aqua hyper prism", "red lava", "orange lava", "yellow mojo",
    # Prizm / 通用平行
    "red mosaic", "orange mosaic", "blue mosaic", "green mosaic",
    "silver wave", "red wave", "blue wave", "green wave",
    "disco", "zebra", "cracked ice", "shimmer", "stained glass",
    "gold", "silver", "red", "blue", "green", "purple", "pink", "black",
]

INSERT_HINT_KEYWORDS = [
    "connections", "scorers club", "global reach", "wonderkids", "wonderkid",
    "complete your set", "you pick", "pick your",
    "instant", "heroes", "rising stars", "future stars",
]

# 中文球员别名 → 英文名（标题翻译 + 检索共用）
PLAYER_ZH_ALIASES: dict[str, str] = {
    "亚马尔": "Lamine Yamal", "梅西": "Lionel Messi", "姆巴佩": "Kylian Mbappé",
    "哈兰德": "Erling Haaland", "贝林厄姆": "Jude Bellingham",
    "罗纳尔多": "Cristiano Ronaldo", "维茨": "Florian Wirtz",
    "穆西亚拉": "Jamal Musiala", "恩德里克": "Endrick", "阿尔瓦雷斯": "Julián Alvarez",
    "福登": "Phil Foden", "萨卡": "Bukayo Saka", "帕奎塔": "Lucas Paquetá",
}

GRADE_RE = re.compile(r"\b(PSA|BGS|SGC|CGC)\s*(\d{1,2}(?:\.5)?)\b", re.I)
SERIAL_RE = re.compile(r"#?\s*(\d{1,4})\s*/\s*(\d{1,4})")
# "#/399" 表示限量 399 张；"135/150" 表示第 135 / 共 150 张
PRINT_RUN_RE = re.compile(r"#\s*/\s*(\d{1,4})")
CARD_NO_RE = re.compile(r"#\s*(\d{1,3}[a-z]?)\b", re.I)


def normalize(name: str) -> str:
    """小写 + 去重音符号 + 只留字母数字。"""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def translate_title(title: str) -> str:
    """把标题里的中文球员别名替换成英文名，便于后续匹配。"""
    for zh, en in PLAYER_ZH_ALIASES.items():
        if zh in title:
            title = title.replace(zh, en)
    return title


def extract_grade(title: str) -> str | None:
    m = GRADE_RE.search(title)
    return f"{m.group(1).upper()} {m.group(2)}" if m else None


def extract_serial(title: str) -> str | None:
    m = SERIAL_RE.search(title)
    if m:
        # 防止把赛季年份 "2023/24" 误当限量号
        if int(m.group(1)) >= 1900:
            return None
        return f"{m.group(1)}/{m.group(2)}"
    m2 = PRINT_RUN_RE.search(title)
    if m2:
        return f"/{m2.group(1)}"
    return None


def extract_parallel(title: str) -> str | None:
    t = title.lower()
    for kw in PARALLEL_KEYWORDS:
        if kw in t:
            return kw.title()
    return None


def extract_insert_hint(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in INSERT_HINT_KEYWORDS)


def _last_name(player: str) -> str:
    parts = player.split()
    return parts[-1] if parts else player


def detect_set(title: str, sets: list[dict]) -> dict | None:
    """从标题识别所属系列。

    sets: [{id, name, aliases}]。策略：别名/关键词命中，取最长匹配；
    同时命中多个时按 sets 顺序取第一个（可后续加权重）。
    """
    nt = normalize(title)
    best: dict | None = None
    best_pri = -1
    best_len = 0
    for s in sets:
        candidates = [s["name"]]
        if s.get("aliases"):
            candidates += s["aliases"]
        for name in candidates:
            nn = normalize(name)
            if nn and nn in nt and (5, len(nn)) > (best_pri, best_len):
                best = s
                best_pri = 5
                best_len = len(nn)
        # 系列名简写关键词（含优先级）
        for kw, (target, pri) in SET_KEYWORDS.items():
            if normalize(target) == normalize(s["name"]) and normalize(kw) in nt:
                k = normalize(kw)
                if (pri, len(k)) > (best_pri, best_len):
                    best = s
                    best_pri = pri
                    best_len = len(k)
    return best


def match_card(title: str, set_id: int, cards: list[dict]) -> dict:
    """在给定系列的 checklist 卡片里匹配一张卡。

    cards: [{id, card_number, player_name}]（player 已归一化）。
    返回 {card_id, confidence, matched_by}。
    """
    title = translate_title(title)
    nt = normalize(title)
    grade = extract_grade(title)
    serial = extract_serial(title)
    parallel = extract_parallel(title)

    # 候选：球员名出现在标题中 或 卡号出现在标题中
    best = None
    best_score = 0
    matched_by = []
    for c in cards:
        score = 0
        by = []
        norm_player = normalize(c["player_name"])
        if norm_player and norm_player in nt:
            score += 3
            by.append("player")
        elif _last_name(c["player_name"]) and normalize(_last_name(c["player_name"])) in nt:
            score += 2
            by.append("last_name")
        num = c["card_number"]
        if num:
            base = re.sub(r"[a-z]$", "", num)
            # 词边界：避免 "#2" 误匹配 "#27"
            if re.search(rf"#\s*{re.escape(base)}(?!\d)", title.lower()) or (
                num != base and re.search(rf"#\s*{re.escape(num)}(?!\d)", title.lower())
            ):
                score += 3
                by.append("card_no")
            elif re.search(rf"(?<!\d){re.escape(base)}(?!\d)", title):
                score += 1
                by.append("card_no_loose")
        # 同分时优先更明确的信号：球员全名 > 卡号 > 姓氏 > 宽松卡号
        signal_rank = {"player": 4, "card_no": 3, "last_name": 2, "card_no_loose": 1}
        cur_rank = max((signal_rank.get(b, 0) for b in by), default=0)
        best_rank = max((signal_rank.get(b, 0) for b in matched_by), default=0)
        if score > best_score or (score == best_score and cur_rank > best_rank):
            best_score = score
            best = c
            matched_by = by

    confidence = "high" if best_score >= 4 else ("medium" if best_score >= 3 else "low")
    return {
        "card_id": best["id"] if best else None,
        "card_number": best["card_number"] if best else None,
        "player_name": best["player_name"] if best else None,
        "confidence": confidence,
        "matched_by": matched_by,
        "grade": grade,
        "serial": serial,
        "parallel": parallel,
        "score": best_score,
    }
