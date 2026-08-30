# -*- coding: utf-8 -*-
"""
00_prescan_anchors.py
----------------------
纯正则 + 词表匹配，完全不调用任何语言模型，对 01_cleaned_segments.json
里的全部 segment（不管有多少个）做一次年龄/季节线索预扫描，秒级跑完。

目的：
    02 阶段慢，是因为“事件抽取”（谁做了什么、地点、引文）这种需要语言理解
    的任务必须用模型。但“年龄”“节日”这类信息，本质是固定的字面模式
    （数字+岁、中秋/元宵这种关键词），根本不需要模型介入，正则就能做，
    而且没有幻觉风险——只要字面出现在原文里，就是100%可信的证据。

    这个脚本先把这部分“骨架”搭出来，你不用等 02 跑完就能看到一部分
    人物年龄的横向关系；02/05 阶段跑完后，还可以用这份数据去交叉验证
    模型抽出来的 age_mentions 是否有遗漏或幻觉。

方法：
    1. 用正则找出所有“数字/中文数字 + 岁”的年龄表达式。
    2. 对每处年龄表达式，在其所在的句子内，用人物别名词表（character_alias）
       找最近的人物称呼作为归属对象（同句内如果有多个候选人物，标记为
       "ambiguous"，人物列表都记下来，不擅自猜是哪个）。
    3. 用固定节日/时令关键词表匹配季节线索（中秋->秋，元宵->冬末春初，
       端午->夏，重阳->秋，腊月->冬，等等），比 02 里模型自己判断更可靠，
       因为这是纯词表查找，不存在理解偏差。

用法：
    python 00_prescan_anchors.py
"""

import json
import os
import re

from character_alias import ALIAS_MAP, SORTED_ALIAS_TUPLES, clean_character_name

INPUT_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/00_prescan_anchors.json"

# --- 中文数字 -> 阿拉伯数字（支持到99，够用了，没人活到几百岁）---
CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_num_to_int(cn_str: str):
    """支持：个位数字、'十'、'十X'、'X十'、'X十X'"""
    if not cn_str:
        return None
    if cn_str.isdigit():
        return int(cn_str)
    if cn_str in CN_DIGIT:
        return CN_DIGIT[cn_str]
    if cn_str == "十":
        return 10
    if len(cn_str) == 2 and cn_str[0] == "十":
        return 10 + CN_DIGIT.get(cn_str[1], 0)
    if len(cn_str) == 2 and cn_str[1] == "十":
        return CN_DIGIT.get(cn_str[0], 0) * 10
    if len(cn_str) == 3 and cn_str[1] == "十":
        return CN_DIGIT.get(cn_str[0], 0) * 10 + CN_DIGIT.get(cn_str[2], 0)
    return None


# 年龄表达式：阿拉伯数字或中文数字紧跟"岁"
AGE_PATTERN = re.compile(
    r"(?:年方|方今|方|今年|这年|那年|已|才|正是|年已)?"
    r"([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})"
    r"\s*岁"
)

# 古文里"年已四十""行年五十""春秋三十"这类惯用语，年龄数字后面不带"岁"字，
# 之前的 AGE_PATTERN 会漏掉（比如"今如海年已四十"里的"四十"就完全没被抓到）。
AGE_NO_SUI_PATTERN = re.compile(
    r"(?:年已|行年|春秋|享年)"
    r"([0-9]{1,3}|[〇零一二三四五六七八九十两百]{1,4})"
)

# 比较级年龄表达式："比XX大/小N岁"——这种不是绝对年龄，是两人的年龄差，
# 需要模型来判断句中代词/称呼指向谁，正则只负责标出候选，不擅自下结论。
COMPARATIVE_PATTERN = re.compile(
    r"比([^，。！？；\s]{1,8}?)(大|小)([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})\s*岁"
)

# 句子中如果同时出现年龄词和这些"相对过去时间"词，说明这个年龄很可能不是
# "当前叙事时刻"的年龄，而是某个过去时间点的年龄（比如"去岁死了"指的是死
# 亡那一刻的年龄，不是现在），需要模型判断参照点，正则本身判断不了。
PAST_RELATIVE_KEYWORDS = ["去岁", "去年", "前年", "旧年", "早年", "当年", "那年"]

# 明确写出"过了几年"这种跨度词——这是唯一能支撑跨越很远的 segment 做年龄
# 衔接的证据，原文没写就无法可靠推算，不要让模型凭空编。
ELAPSED_YEARS_PATTERN = re.compile(
    r"(?:过了|隔了|又过|已过|将有|将近)\s*([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})\s*[年载]"
)

# 古文里用固定成语表达年龄，不带任何数字（比如"半百""弱冠""花甲"），
# 之前的两个AGE_PATTERN都要求数字，完全覆盖不到这类表达——这正是甄士隐
# "如今年已半百"完全没被抓到候选的原因。这类成语本质上和季节关键词一样，
# 是固定词表查找，不需要模型判断，正则查表即可，零幻觉风险。
# 部分成语年龄跨度较大（如"耄耋"），标记 is_approximate=True，供下游区别对待。
IDIOM_AGE_KEYWORDS = {
    "垂髫": (4, True),      # 幼儿，约3-8岁，取中位近似值
    "总角": (8, True),      # 童年，约8-14岁
    "豆蔻": (14, True),     # 女子十三四岁
    "及笄": (15, False),    # 女子15岁，古代明确年龄标准
    "束发": (15, False),    # 男子15岁
    "弱冠": (20, False),    # 男子20岁
    "而立": (30, False),
    "不惑": (40, False),
    "知天命": (50, False),
    "半百": (50, False),
    "知非之年": (50, False),
    "花甲": (60, False),
    "耳顺": (60, False),
    "古稀": (70, False),
    "耄耋": (85, True),     # 80-90岁，取中位近似值
    "期颐": (100, False),
}

# 固定节日/时令关键词 -> 粗粒度季节（纯词表匹配，不需要模型判断）
SEASON_KEYWORDS = {
    "元宵": "冬",   # 正月十五，农历冬末，习惯上归入"冬"
    "上元": "冬",
    "中秋": "秋",
    "端午": "夏",
    "端阳": "夏",
    "重阳": "秋",
    "腊月": "冬",
    "腊八": "冬",
    "除夕": "冬",
    "新春": "春",
    "新正": "春",
    "清明": "春",
    "立春": "春",
    "立夏": "夏",
    "立秋": "秋",
    "立冬": "冬",
    "三伏": "夏",
    "严冬": "冬",
    "初雪": "冬",
    "落雪": "冬",
    "梅雨": "夏",
}

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？；\n]")


# "不到/将近/才/足/已满"这类限定词——出现在年龄数字前面时，说明这不是精确
# 年龄，而是一个近似值/上下界，之前的正则会把"不到二十岁"直接简化成
# "二十岁"，丢掉了"不到"这个关键限定，需要单独识别出来。
BOUND_QUALIFIER_PATTERN = re.compile(r"(不到|将近|足|已满|不满|才|堪堪)\s*$")

# 履历/人生节点关键词——出现这些词，说明句子描述的是某人"一生中的某个阶段"
# （进学、及笄、出阁、生子、病故等），而不是"当前叙事时刻"的年龄，这种
# 年龄不能拿来和别的"当前年龄"互相比较冲突，需要单独标记出来交给06分类。
MILESTONE_KEYWORDS = [
    "进学", "及笄", "弱冠", "出阁", "出嫁", "娶妻", "娶了妻", "生子", "生了子",
    "病死", "病故", "亡故", "下世", "夭亡", "早逝", "登第", "中举", "及第",
]


def _detect_bound_qualifier(sentence: str, match_start: int) -> str:
    """检查年龄数字前面紧邻的文字是否有限定词，返回 exact/less_than/about/at_least"""
    prefix = sentence[max(0, match_start - 4):match_start]
    m = BOUND_QUALIFIER_PATTERN.search(prefix)
    if not m:
        return "exact"
    kw = m.group(1)
    if kw in ("不到", "不满"):
        return "less_than"
    if kw in ("将近", "堪堪"):
        return "about"
    if kw in ("足", "已满"):
        return "at_least"
    return "exact"


def _split_sentences(text: str):
    return [s for s in SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]


def _find_nearby_characters(sentence: str, match_start: int):
    """在句子内找候选人物称呼，返回 [(raw_name, canonical_name, position), ...]
    按离年龄表达式的距离从近到远排序。"""
    candidates = []
    for alias, canon in SORTED_ALIAS_TUPLES:
        if len(alias) < 2:
            continue
        pos = sentence.find(alias)
        while pos != -1:
            candidates.append((alias, canon, pos))
            pos = sentence.find(alias, pos + 1)
    candidates.sort(key=lambda x: abs(x[2] - match_start))
    # 去重（同一个 canonical 只保留离得最近的一次）
    seen = set()
    dedup = []
    for raw, canon, pos in candidates:
        if canon in seen:
            continue
        seen.add(canon)
        dedup.append((raw, canon, pos))
    return dedup


def scan_segment(seg: dict) -> dict:
    narrative = seg.get("narrative", "") or seg.get("text", "")
    seg_id = seg.get("segment_id")
    chapter = seg.get("chapter", "")

    age_candidates = []
    relation_candidates = []

    for sentence in _split_sentences(narrative):
        # --- 绝对年龄候选（"X岁"形式）---
        for m in AGE_PATTERN.finditer(sentence):
            age_val = _cn_num_to_int(m.group(1))
            if age_val is None or not (0 <= age_val <= 99):
                continue
            nearby = _find_nearby_characters(sentence, m.start())
            has_past_marker = any(kw in sentence for kw in PAST_RELATIVE_KEYWORDS)
            has_milestone_kw = any(kw in sentence for kw in MILESTONE_KEYWORDS)
            bound_type = _detect_bound_qualifier(sentence, m.start())
            age_candidates.append({
                "sentence": sentence.strip(),
                "stated_age": age_val,
                "matched_text": m.group(0),
                "bound_type": bound_type,  # exact/less_than/about/at_least
                "candidate_characters": [c for _, c, _ in nearby],
                "confidence": "high" if len(nearby) == 1 else ("ambiguous" if len(nearby) > 1 else "no_character_found"),
                "needs_llm_review": has_past_marker or has_milestone_kw or len(nearby) != 1,
                "past_time_marker_detected": has_past_marker,
                "milestone_keyword_detected": has_milestone_kw,
            })

        # --- 绝对年龄候选（"年已X"这类不带"岁"字的惯用语）---
        for m in AGE_NO_SUI_PATTERN.finditer(sentence):
            age_val = _cn_num_to_int(m.group(1))
            if age_val is None or not (0 <= age_val <= 120):
                continue
            nearby = _find_nearby_characters(sentence, m.start())
            has_past_marker = any(kw in sentence for kw in PAST_RELATIVE_KEYWORDS)
            has_milestone_kw = any(kw in sentence for kw in MILESTONE_KEYWORDS)
            age_candidates.append({
                "sentence": sentence.strip(),
                "stated_age": age_val,
                "matched_text": m.group(0),
                "bound_type": "exact",
                "candidate_characters": [c for _, c, _ in nearby],
                "confidence": "high" if len(nearby) == 1 else ("ambiguous" if len(nearby) > 1 else "no_character_found"),
                "needs_llm_review": has_past_marker or has_milestone_kw or len(nearby) != 1,
                "past_time_marker_detected": has_past_marker,
                "milestone_keyword_detected": has_milestone_kw,
            })

        # --- 比较级候选："比XX大/小N岁" ---
        for m in COMPARATIVE_PATTERN.finditer(sentence):
            raw_target, direction, cn_diff = m.group(1), m.group(2), m.group(3)
            diff_val = _cn_num_to_int(cn_diff)
            if diff_val is None:
                continue
            nearby = _find_nearby_characters(sentence, m.start())
            relation_candidates.append({
                "type": "comparative",
                "sentence": sentence.strip(),
                "matched_text": m.group(0),
                "raw_target_phrase": raw_target,   # 可能是人名，也可能是"我"这种代词
                "direction": direction,             # "大" 或 "小"
                "age_diff": diff_val,
                "candidate_characters_in_sentence": [c for _, c, _ in nearby],
            })

        # --- 跨度候选："过了几年" ---
        for m in ELAPSED_YEARS_PATTERN.finditer(sentence):
            years_val = _cn_num_to_int(m.group(1))
            if years_val is None:
                continue
            nearby = _find_nearby_characters(sentence, m.start())
            relation_candidates.append({
                "type": "elapsed_years",
                "sentence": sentence.strip(),
                "matched_text": m.group(0),
                "elapsed_years": years_val,
                "candidate_characters_in_sentence": [c for _, c, _ in nearby],
            })

        # --- 成语年龄候选（"半百""弱冠""花甲"这类不带数字的固定表达）---
        # 之前只定义了 IDIOM_AGE_KEYWORDS 词表，忘了接入扫描循环，导致
        # "如今年已半百"这种表达完全没被抓到候选，这里补上。
        for kw, (age_val, is_approx) in IDIOM_AGE_KEYWORDS.items():
            start_pos = sentence.find(kw)
            while start_pos != -1:
                nearby = _find_nearby_characters(sentence, start_pos)
                has_past_marker = any(k in sentence for k in PAST_RELATIVE_KEYWORDS)
                has_milestone_kw = any(k in sentence for k in MILESTONE_KEYWORDS)
                age_candidates.append({
                    "sentence": sentence.strip(),
                    "stated_age": age_val,
                    "matched_text": kw,
                    "bound_type": "about" if is_approx else "exact",
                    "is_idiom_age": True,  # 标记这是成语推算的年龄，不是原文直接写的数字
                    "candidate_characters": [c for _, c, _ in nearby],
                    # 成语年龄经常没有主语在同一句里（比如"如今年已半百"前面
                    # 的主语"甄士隐"在上一句），这种情况下 candidate_characters
                    # 会是空的，标记为 no_character_found，交给13结合全段原文
                    # 去判断主语是谁，这里不用勉强
                    "confidence": "high" if len(nearby) == 1 else ("ambiguous" if len(nearby) > 1 else "no_character_found"),
                    "needs_llm_review": True,  # 成语年龄本身就不精确/常缺主语，一律送审
                    "past_time_marker_detected": has_past_marker,
                    "milestone_keyword_detected": has_milestone_kw,
                })
                start_pos = sentence.find(kw, start_pos + 1)

    season_candidates = []
    for keyword, season in SEASON_KEYWORDS.items():
        if keyword in narrative:
            season_candidates.append({"keyword": keyword, "season": season})

    return {
        "segment_id": seg_id,
        "chapter": chapter,
        "age_candidates": age_candidates,
        "relation_candidates": relation_candidates,
        "season_candidates": season_candidates,
    }


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}（请先跑完01阶段）")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    results = [scan_segment(seg) for seg in segments]

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_age_hits = sum(len(r["age_candidates"]) for r in results)
    total_relation_hits = sum(len(r["relation_candidates"]) for r in results)
    total_season_hits = sum(len(r["season_candidates"]) for r in results)
    high_conf = sum(1 for r in results for a in r["age_candidates"] if a["confidence"] == "high" and not a["needs_llm_review"])

    print(f"✅ 预扫描完成（未调用任何模型，纯正则）：")
    print(f"   共扫描 {len(results)} 个 segment")
    print(f"   年龄表达式命中 {total_age_hits} 处（其中 {high_conf} 处无需模型复核即可直接用）")
    print(f"   比较级/跨度关系候选命中 {total_relation_hits} 处（这些需要用06脚本交给模型判断）")
    print(f"   季节关键词命中 {total_season_hits} 处")
    print(f"   -> {output_file}")

    # 打印一份按人物汇总的年龄锚点，方便直接看横向关系
    from collections import defaultdict
    by_char = defaultdict(list)
    for r in results:
        for a in r["age_candidates"]:
            if a["confidence"] == "high" and not a["needs_llm_review"]:
                by_char[a["candidate_characters"][0]].append((r["segment_id"], a["stated_age"]))

    if by_char:
        print("\n--- 高置信度年龄锚点（按人物汇总） ---")
        for char, entries in sorted(by_char.items(), key=lambda x: -len(x[1])):
            print(f"   {char}: {entries}")

    return results


if __name__ == "__main__":
    run()
