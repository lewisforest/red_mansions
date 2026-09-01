# -*- coding: utf-8 -*-
"""
03_kinship_prescan.py
------------------------
和 02 是同一套方法论：古典文本里的亲属称谓几乎都是固定词汇/句式，正则能
覆盖大部分，零模型、零幻觉风险、秒级跑完全书。

结合 02 脚本优化策略：
1. 过滤脂批注释，防止噪声干扰；
2. 提取局部主语/称谓短语 (raw_subject_phrase)，方便 LLM 补全零指代；
3. 输出 needs_llm_review 与 confidence 标记，将主语消歧下放给 LLM。

用法：
    python 03_kinship_prescan.py
"""

import json
import os
import re

from character_alias import SORTED_ALIAS_TUPLES, ALIAS_MAP, clean_character_name

INPUT_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/03_kinship_candidates.json"

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？；\n]")

# ⭐️ 1. 清洗脂批与注释
COMMENTARY_PATTERN = re.compile(r"\[脂批.*?\\]|\[.*?\]|【.*?】|（.*?）")

# ⭐️ 2. 局部身份/称谓短语匹配（抓取匹配点前 10 个字符中的特定称谓/人名）
TITLE_PATTERNS = re.compile(
    r"([A-Z\u4e00-\u9fa5]{1,4}(?:小姐|丫鬟|小厮|老尼|道士|和尚|奶妈|老嬷嬷|哥儿|姐儿|老爷|夫人|太太|长子|次子|长女|次女|表兄|表弟|表姐|表妹))"
)

# (正则, 关系标签, 说明)
KINSHIP_PATTERNS = [
    (re.compile(r"生得?一?[女子]，?乳名([^，。！？]{2,4})"), "parent_of", "生子/生女，乳名XX"),
    (re.compile(r"头胎生的公子，?名唤([^，。！？]{2,4})"), "parent_of", "头胎公子"),
    (re.compile(r"([^，。！？的]{2,4})之[女子]([^，。！？]{2,4})"), "parent_of_explicit", "XX之女/之子YY"),
    (re.compile(r"([^，。！？的]{2,4})[的]?[女子]，?乳名([^，。！？]{2,4})"), "parent_of_explicit", "XX的女儿/儿子，乳名YY"),
    (re.compile(r"([^，。！？]{2,6})[与和]([^，。！？]{2,6})[，,]?\s*(?:是|乃|为)?\s*(姊弟|姐弟|兄妹|兄弟|姐妹)"), "siblings", "XX与YY是姊弟/兄妹"),
    (re.compile(r"([^，。！？]{2,4})乃([^，。！？]{2,4})之(父|母|妻|夫|女|子)"), "direct_statement", "XX乃YY之父/母/妻/夫"),
    (re.compile(r"(?:嫡妻|元配|续弦|正室|继室|填房)([^，。！？]{2,4})"), "spouse_of", "嫡妻/续弦XX（配偶方需靠上下文补全）"),
    (re.compile(r"([^，。！？的]{2,4})之妻([^，。！？]{2,4})"), "spouse_of_explicit", "XX之妻YY"),
]


def _strip_commentary(text: str) -> str:
    """清洗文本中的脂批与注释，剔除伪线索干扰"""
    if not text:
        return ""
    return COMMENTARY_PATTERN.sub(" ", text)


def _split_sentences(text: str):
    return [s.strip() for s in SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]


def _extract_subject_context(sentence: str, match_start: int):
    """提取匹配项前 10 个字符内的局部称谓/主语短语"""
    prefix = sentence[max(0, match_start - 10):match_start]
    m = TITLE_PATTERNS.search(prefix)
    if m:
        return m.group(1)
    return None


def _find_nearby_characters(sentence: str):
    """在句子里查找候选人物称呼（按字符出现顺序排列）"""
    candidates = []
    for alias, canon in SORTED_ALIAS_TUPLES:
        if len(alias) < 2:
            continue
        pos = sentence.find(alias)
        while pos != -1:
            candidates.append((alias, canon, pos))
            pos = sentence.find(alias, pos + 1)
    candidates.sort(key=lambda x: x[2])
    return candidates


def _looks_like_name(text: str) -> bool:
    """校验人名合理性，过滤非人名动词短语"""
    if not text:
        return False
    text = text.strip()
    if text in ALIAS_MAP:
        return True

    # 扩展非人名特征词
    non_name_markers = [
        "酗酒", "赌博", "顽劣", "读书", "娶", "嫁", "病", "死",
        "不知", "容颜", "生的", "为人", "性情", "喜欢", "爱", "极",
        "甚", "十分", "非常", "并不", "早已", "近来", "如今"
    ]
    if any(kw in text for kw in non_name_markers):
        return False
    return len(text) <= 4


def scan_segment(seg: dict) -> dict:
    raw_narrative = seg.get("narrative", "") or seg.get("text", "")
    narrative = _strip_commentary(raw_narrative)

    seg_id = seg.get("segment_id")
    chapter = seg.get("chapter", "")

    kinship_candidates = []
    for sentence in _split_sentences(narrative):
        nearby = _find_nearby_characters(sentence)
        unique_characters = list(dict.fromkeys([c for _, c, _ in nearby]))

        for pattern, rel_type, desc in KINSHIP_PATTERNS:
            for m in pattern.finditer(sentence):
                groups = [g.strip() if g else "" for g in m.groups()]

                # 对 "parent_of_explicit" 等类型做二次校验
                if rel_type in ("parent_of_explicit", "spouse_of_explicit") and len(groups) >= 2:
                    if not _looks_like_name(groups[-1]):
                        continue

                raw_title = _extract_subject_context(sentence, m.start())

                # 评估置信度与 LLM 复核标志
                needs_review = (
                    rel_type in ("parent_of", "spouse_of") or  # 隐去一方主语的句式必须二审
                    len(unique_characters) < 2 or
                    raw_title is not None
                )

                confidence = "high"
                if len(unique_characters) == 0:
                    confidence = "no_character_found"
                elif rel_type in ("parent_of", "spouse_of"):
                    confidence = "implicit_subject"  # 隐式主语，需 LLM 根据上下文补全
                elif len(unique_characters) > 2:
                    confidence = "multiple_characters_ambiguous"

                kinship_candidates.append({
                    "sentence": sentence.strip(),
                    "pattern_desc": desc,
                    "relation_type_hint": rel_type,
                    "regex_groups": groups,
                    "raw_subject_phrase": raw_title,
                    "candidate_characters_in_sentence": unique_characters,
                    "confidence": confidence,
                    "needs_llm_review": needs_review
                })

    return {
        "segment_id": seg_id,
        "chapter": chapter,
        "kinship_candidates": kinship_candidates
    }


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    results = [scan_segment(seg) for seg in segments]
    results = [r for r in results if r["kinship_candidates"]]  # 仅保留命中项

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = sum(len(r["kinship_candidates"]) for r in results)
    print(f"✅ 亲属关系预扫描完成：{len(results)} 个 segment 命中，共 {total} 处候选 -> {output_file}")
    return results


if __name__ == "__main__":
    run()
