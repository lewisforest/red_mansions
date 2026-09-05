# -*- coding: utf-8 -*-
"""
02_prescan_anchors.py
----------------------
纯正则 + 词表匹配，完全不调用任何语言模型，对 01_cleaned_segments.json
里的全部 segment 做年龄/季节线索预扫描。
"""

import json
import os
import re

from character_alias import ALIAS_MAP, SORTED_ALIAS_TUPLES, clean_character_name

INPUT_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/02_prescan_anchors.json"

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# ⭐️ 1. 清洗脂批与注释
COMMENTARY_PATTERN = re.compile(r"\[脂批.*?\\]|\[.*?\]|【.*?】|（.*?）")

# ⭐️ 2. 局部身份/称谓短语匹配（抓取匹配点前 10 个字符中的特定称谓）
TITLE_PATTERNS = re.compile(
    r"([A-Z\u4e00-\u9fa5]{1,4}(?:小姐|姑娘|丫鬟|小厮|老尼|道士|和尚|奶妈|老嬷嬷|哥儿|姐儿|老爷|夫人|太太))"
)

def _strip_commentary(text: str) -> str:
    """清洗文本中的脂批与注释，剔除伪线索干扰"""
    if not text:
        return ""
    return COMMENTARY_PATTERN.sub(" ", text)


def _cn_num_to_int(cn_str: str):
    """支持：个位数字、'十'、'十X'、'X十'、'X十X'、'百/一百'、'八十有五'"""
    if not cn_str:
        return None
    if cn_str.isdigit():
        return int(cn_str)

    if "有" in cn_str:
        parts = cn_str.split("有")
        base = _cn_num_to_int(parts[0]) or 0
        addition = _cn_num_to_int(parts[1]) or 0
        return base + addition

    if cn_str in CN_DIGIT:
        return CN_DIGIT[cn_str]
    if cn_str == "十":
        return 10
    if cn_str in ("百", "一百"):
        return 100
    if len(cn_str) == 2 and cn_str[0] == "十":
        return 10 + CN_DIGIT.get(cn_str[1], 0)
    if len(cn_str) == 2 and cn_str[1] == "十":
        return CN_DIGIT.get(cn_str[0], 0) * 10
    if len(cn_str) == 3 and cn_str[1] == "十":
        return CN_DIGIT.get(cn_str[0], 0) * 10 + CN_DIGIT.get(cn_str[2], 0)
    if "百" in cn_str:
        parts = cn_str.split("百")
        hundreds = CN_DIGIT.get(parts[0], 1) * 100
        rest = _cn_num_to_int(parts[1]) if len(parts) > 1 and parts[1] else 0
        return hundreds + (rest or 0)
    return None


AGE_PATTERN = re.compile(
    r"(?<![比大小长幼])"
    r"(?:年方|方今|方|今年|这年|那年|已|才|正是|年已|年约|年近|年纪|生得)?"
    r"([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})"
    r"\s*岁"
)

AGE_NO_SUI_PATTERN = re.compile(
    r"(?:年已|行年|春秋|享年|年近|年方)"
    r"([0-9]{1,3}|[〇零一二三四五六七八九十两百]{1,4})"
)

COMPARATIVE_PATTERN = re.compile(
    r"(?:比([^，。！？；\s]{1,8}?)|([^，。！？；\s]{1,8}?))"
    r"(大|小|长|幼|长于|幼于)"
    r"([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})\s*岁"
)

PAST_RELATIVE_KEYWORDS = ["去岁", "去年", "前年", "旧年", "早年", "当年", "那年"]

ELAPSED_YEARS_PATTERN = re.compile(
    r"(?:过了|隔了|又过|已过|将有|将近)\s*([0-9]{1,2}|[〇零一二三四五六七八九十两]{1,3})\s*[年载]"
)

IDIOM_AGE_KEYWORDS = {
    "垂髫": (4, True), "总角": (8, True), "豆蔻": (14, True), "及笄": (15, False),
    "束发": (15, False), "弱冠": (20, False), "而立": (30, False), "不惑": (40, False),
    "知天命": (50, False), "半百": (50, False), "知非之年": (50, False), "花甲": (60, False),
    "耳顺": (60, False), "古稀": (70, False), "耄耋": (85, True), "期颐": (100, False),
}

SEASON_KEYWORDS = {
    "元宵": "冬", "上元": "冬", "中秋": "秋", "端午": "夏", "端阳": "夏",
    "重阳": "秋", "腊月": "冬", "腊八": "冬", "除夕": "冬", "新春": "春",
    "新正": "春", "清明": "春", "立春": "春", "立夏": "夏", "立秋": "秋",
    "立冬": "冬", "三伏": "夏", "严冬": "冬", "初雪": "冬", "落雪": "冬", "梅雨": "夏"
}

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？；\n]")
BOUND_QUALIFIER_PATTERN = re.compile(r"(大还不过|还不过|不过|至多|最多|不到|将近|足|已满|不满|才|堪堪)\s*$")
MILESTONE_KEYWORDS = [
    "进学", "及笄", "弱冠", "出阁", "出嫁", "娶妻", "娶了妻", "生子", "生了子",
    "病死", "病故", "亡故", "下世", "夭亡", "早逝", "登第", "中举", "及第"
]

HAIR_ACCESSORY_SUFFIXES = ["冠", "巾", "簪", "带", "网", "紫金冠", "银冠"]


def _extract_subject_context(sentence: str, match_start: int):
    """提取匹配项前 10 个字符内的局部称谓短语（如 '夏家小姐'、'单身小厮'），辅助 LLM 判定"""
    prefix = sentence[max(0, match_start - 10):match_start]
    m = TITLE_PATTERNS.search(prefix)
    if m:
        return m.group(1)
    return None


def _is_clothing_or_accessory(sentence: str, kw: str, start_pos: int) -> bool:
    if kw == "束发":
        after_text = sentence[start_pos + len(kw):start_pos + len(kw) + 3]
        if any(after_text.startswith(suf) for suf in HAIR_ACCESSORY_SUFFIXES):
            return True
        prefix_text = sentence[max(0, start_pos - 4):start_pos]
        if any(v in prefix_text for v in ["戴", "戴着", "顶着", "顶"]):
            return True
    return False


def _is_valid_idiom_age(sentence: str, kw: str, start_pos: int) -> bool:
    if kw == "而立":
        prefix = sentence[max(0, start_pos - 2):start_pos]
        if any(w in prefix for w in ["面", "南", "北", "东", "西", "前", "后", "肃", "屹", "挺", "站", "自"]):
            return False
        suffix = sentence[start_pos + len(kw):start_pos + len(kw) + 1]
        if suffix in ["于", "在", "着"]:
            return False

    if kw == "不惑":
        prefix = sentence[max(0, start_pos - 2):start_pos]
        if any(w in prefix for w in ["了然", "解", "明", "大", "无"]):
            return False
        suffix = sentence[start_pos + len(kw):start_pos + len(kw) + 1]
        if suffix in ["于", "之"]:
            return False

    if "天命" in kw:
        prefix = sentence[max(0, start_pos - 2):start_pos]
        if any(w in prefix for w in ["不", "听", "顺", "尽"]):
            return False

    return True


def _detect_bound_qualifier(sentence: str, match_start: int) -> str:
    prefix = sentence[max(0, match_start - 4):match_start]
    m = BOUND_QUALIFIER_PATTERN.search(prefix)
    if not m:
        return "exact"
    kw = m.group(1)
    if kw in ("不到", "不满"):
        return "less_than"
    if kw in ("大还不过", "还不过", "不过", "至多", "最多"):
        return "at_most"
    if kw in ("将近", "堪堪"):
        return "about"
    if kw in ("足", "已满"):
        return "at_least"
    return "exact"


def _split_sentences(text: str):
    return [s.strip() for s in SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]


def _find_nearby_characters(sentence: str, match_start: int):
    candidates = []
    for alias, canon in SORTED_ALIAS_TUPLES:
        if len(alias) < 2:
            continue
        pos = sentence.find(alias)
        while pos != -1:
            candidates.append((alias, canon, pos))
            pos = sentence.find(alias, pos + 1)
    candidates.sort(key=lambda x: abs(x[2] - match_start))
    seen = set()
    dedup = []
    for raw, canon, pos in candidates:
        if canon in seen:
            continue
        seen.add(canon)
        dedup.append((raw, canon, pos))
    return dedup


def scan_segment(seg: dict) -> dict:
    raw_narrative = seg.get("narrative", "") or seg.get("text", "")
    narrative = _strip_commentary(raw_narrative)

    seg_id = seg.get("segment_id")
    chapter = seg.get("chapter", "")

    age_candidates = []
    relation_candidates = []

    for sentence in _split_sentences(narrative):
        occupied_spans = []

        # ⭐️ 统计该句中所有可能包含的年龄线索总数量（判断单句多主语/多年龄）
        all_matches_in_sent = (
            len(list(AGE_PATTERN.finditer(sentence))) +
            len(list(AGE_NO_SUI_PATTERN.finditer(sentence))) +
            sum(1 for kw in IDIOM_AGE_KEYWORDS if kw in sentence)
        )
        is_multi_age_sentence = all_matches_in_sent > 1

        # ----------------------------------------------------
        # 1. 优先提取：比较级年龄 (COMPARATIVE_PATTERN)
        # ----------------------------------------------------
        for m in COMPARATIVE_PATTERN.finditer(sentence):
            raw_target = m.group(1) or m.group(2) or ""
            direction_str = m.group(3)
            diff_val = _cn_num_to_int(m.group(4))
            if diff_val is None:
                continue

            occupied_spans.append(m.span())
            nearby = _find_nearby_characters(sentence, m.start())
            relation_candidates.append({
                "clue_type": "comparative",
                "type": "comparative",
                "sentence": sentence.strip(),
                "matched_text": m.group(0),
                "raw_target_phrase": raw_target,
                "direction": "大" if direction_str in ("大", "长", "长于") else "小",
                "age_diff": diff_val,
                "candidate_characters_in_sentence": [c for _, c, _ in nearby],
                "needs_llm_review": True,
            })

        # ----------------------------------------------------
        # 2. 提取：跨度 ("过了几年")
        # ----------------------------------------------------
        for m in ELAPSED_YEARS_PATTERN.finditer(sentence):
            years_val = _cn_num_to_int(m.group(1))
            if years_val is None:
                continue
            occupied_spans.append(m.span())
            nearby = _find_nearby_characters(sentence, m.start())
            relation_candidates.append({
                "clue_type": "elapsed_years",
                "type": "elapsed_years",
                "sentence": sentence.strip(),
                "matched_text": m.group(0),
                "elapsed_years": years_val,
                "candidate_characters_in_sentence": [c for _, c, _ in nearby],
                "needs_llm_review": True,
            })

        # ----------------------------------------------------
        # 3. 提取：绝对年龄 ("X岁")
        # ----------------------------------------------------
        for m in AGE_PATTERN.finditer(sentence):
            m_start, m_end = m.span()
            if any(s <= m_start and m_end <= e for s, e in occupied_spans):
                continue

            age_val = _cn_num_to_int(m.group(1))
            if age_val is None or not (0 <= age_val <= 120):
                continue

            occupied_spans.append((m_start, m_end))
            nearby = _find_nearby_characters(sentence, m.start())
            raw_title = _extract_subject_context(sentence, m.start())

            has_past_marker = any(kw in sentence for kw in PAST_RELATIVE_KEYWORDS)
            has_milestone_kw = any(kw in sentence for kw in MILESTONE_KEYWORDS)
            bound_type = _detect_bound_qualifier(sentence, m.start())

            needs_review = (
                is_multi_age_sentence or
                has_past_marker or
                has_milestone_kw or
                len(nearby) != 1 or
                raw_title is not None
            )

            confidence = "high"
            if is_multi_age_sentence:
                confidence = "multi_age_ambiguous"
            elif len(nearby) == 0:
                confidence = "no_character_found"
            elif len(nearby) > 1:
                confidence = "multiple_characters_found"

            age_candidates.append({
                "clue_type": "absolute",
                "sentence": sentence.strip(),
                "stated_age": age_val,
                "matched_text": m.group(0),
                "bound_type": bound_type,
                "raw_subject_phrase": raw_title,
                "candidate_characters": [c for _, c, _ in nearby],
                "confidence": confidence,
                "needs_llm_review": needs_review,
                "past_time_marker_detected": has_past_marker,
                "milestone_keyword_detected": has_milestone_kw,
            })

        # ----------------------------------------------------
        # 4. 提取：古文惯用语 ("年已四十")
        # ----------------------------------------------------
        for m in AGE_NO_SUI_PATTERN.finditer(sentence):
            m_start, m_end = m.span()
            if any(s <= m_start and m_end <= e for s, e in occupied_spans):
                continue

            age_val = _cn_num_to_int(m.group(1))
            if age_val is None or not (0 <= age_val <= 120):
                continue

            occupied_spans.append((m_start, m_end))
            nearby = _find_nearby_characters(sentence, m.start())
            raw_title = _extract_subject_context(sentence, m.start())

            has_past_marker = any(kw in sentence for kw in PAST_RELATIVE_KEYWORDS)
            has_milestone_kw = any(kw in sentence for kw in MILESTONE_KEYWORDS)

            needs_review = (
                is_multi_age_sentence or
                has_past_marker or
                has_milestone_kw or
                len(nearby) != 1 or
                raw_title is not None
            )

            confidence = "high"
            if is_multi_age_sentence:
                confidence = "multi_age_ambiguous"
            elif len(nearby) == 0:
                confidence = "no_character_found"
            elif len(nearby) > 1:
                confidence = "multiple_characters_found"

            age_candidates.append({
                "clue_type": "no_sui_idiom",
                "sentence": sentence.strip(),
                "stated_age": age_val,
                "matched_text": m.group(0),
                "bound_type": "exact",
                "raw_subject_phrase": raw_title,
                "candidate_characters": [c for _, c, _ in nearby],
                "confidence": confidence,
                "needs_llm_review": needs_review,
                "past_time_marker_detected": has_past_marker,
                "milestone_keyword_detected": has_milestone_kw,
            })

        # ----------------------------------------------------
        # 5. 提取：成语年龄 ("半百", "弱冠" 等)
        # ----------------------------------------------------
        for kw, (age_val, is_approx) in IDIOM_AGE_KEYWORDS.items():
            start_pos = sentence.find(kw)
            while start_pos != -1:
                end_pos = start_pos + len(kw)

                if _is_clothing_or_accessory(sentence, kw, start_pos) or not _is_valid_idiom_age(sentence, kw, start_pos):
                    start_pos = sentence.find(kw, start_pos + 1)
                    continue

                if not any(s <= start_pos and end_pos <= e for s, e in occupied_spans):
                    nearby = _find_nearby_characters(sentence, start_pos)
                    raw_title = _extract_subject_context(sentence, start_pos)

                    has_past_marker = any(k in sentence for k in PAST_RELATIVE_KEYWORDS)
                    has_milestone_kw = any(k in sentence for k in MILESTONE_KEYWORDS)

                    needs_review = (
                        is_multi_age_sentence or
                        has_past_marker or
                        has_milestone_kw or
                        len(nearby) != 1 or
                        raw_title is not None
                    )

                    confidence = "high"
                    if is_multi_age_sentence:
                        confidence = "multi_age_ambiguous"
                    elif len(nearby) == 0:
                        confidence = "no_character_found"
                    elif len(nearby) > 1:
                        confidence = "multiple_characters_found"

                    age_candidates.append({
                        "clue_type": "idiom_age",
                        "sentence": sentence.strip(),
                        "stated_age": age_val,
                        "matched_text": kw,
                        "bound_type": "about" if is_approx else "exact",
                        "is_idiom_age": True,
                        "raw_subject_phrase": raw_title,
                        "candidate_characters": [c for _, c, _ in nearby],
                        "confidence": confidence,
                        "needs_llm_review": needs_review,
                        "past_time_marker_detected": has_past_marker,
                        "milestone_keyword_detected": has_milestone_kw,
                    })
                start_pos = sentence.find(kw, start_pos + 1)

    season_candidates = [{"keyword": kw, "season": s} for kw, s in SEASON_KEYWORDS.items() if kw in narrative]

    return {
        "segment_id": seg_id,
        "chapter": chapter,
        "age_candidates": age_candidates,
        "relation_candidates": relation_candidates,
        "season_candidates": season_candidates,
    }


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    results = [scan_segment(seg) for seg in segments]

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"✅ 预扫描完成：共扫描 {len(results)} 个 segment -> {output_file}")
    return results


if __name__ == "__main__":
    run()
