# -*- coding: utf-8 -*-
"""
10_kinship_prescan.py
------------------------
和 00 是同一套方法论：古典文本里的亲属称谓几乎都是固定词汇/句式，正则能
覆盖大部分，零模型、零幻觉风险、秒级跑完全书。

覆盖的模式（可以按实际效果继续扩充）：
    "生得一女/子，乳名XX"      -> 说话人物的子女
    "头胎生的公子，名唤XX"      -> 长子
    "XX之女/之子YY"            -> 直接的"某某的儿子/女儿是某某"
    "XX与YY，是姊弟/姐弟/兄妹"   -> 平辈关系
    "XX乃YY之父/母/妻/夫"       -> 直接判定句

用法：
    python 10_kinship_prescan.py
"""

import json
import os
import re

from character_alias import SORTED_ALIAS_TUPLES, ALIAS_MAP, clean_character_name

INPUT_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/10_kinship_candidates.json"

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？；\n]")

# (正则, 关系标签, 说明) —— 关系标签统一写成 "A_relation_B" 的模板，
# 具体填谁进A/B在下面的处理函数里做
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


def _split_sentences(text: str):
    return [s for s in SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]


def _find_nearby_characters(sentence: str, exclude_spans=()):
    """复用00的思路：在句子里找候选人物称呼"""
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
    """检查一段文字是不是像人名，而不是动词短语。'之子/之女'后面接的经常是
    谓语（比如"旺儿之子酗酒赌博"），而不是名字，之前的正则会把动词短语
    误当成人名，这里做一层过滤：要么在别名表里能查到，要么明显带有起名
    句式的标记词。"""
    if not text:
        return False
    if text in ALIAS_MAP:
        return True
    # 常见的"不是名字"信号：包含明显的动词/描述性词汇
    non_name_markers = ["酗酒", "赌博", "顽劣", "读书", "娶", "嫁", "病", "死",
                          "不知", "容颜", "生的", "为人", "性情", "喜欢", "爱"]
    if any(kw in text for kw in non_name_markers):
        return False
    return len(text) <= 4  # 人名一般很短，超长的大概率是句子片段


def scan_segment(seg: dict) -> dict:
    narrative = seg.get("narrative", "") or seg.get("text", "")
    seg_id = seg.get("segment_id")
    chapter = seg.get("chapter", "")

    kinship_candidates = []
    for sentence in _split_sentences(narrative):
        nearby = _find_nearby_characters(sentence)

        for pattern, rel_type, desc in KINSHIP_PATTERNS:
            for m in pattern.finditer(sentence):
                groups = list(m.groups())
                # 对"之子/之女"这类模式做人名合理性校验，避免把动词短语当成人名
                if rel_type in ("parent_of_explicit",) and len(groups) >= 2:
                    if not _looks_like_name(groups[-1]):
                        continue  # 后面接的不像人名，跳过，不产生虚假候选

                kinship_candidates.append({
                    "sentence": sentence.strip(),
                    "pattern_desc": desc,
                    "relation_type_hint": rel_type,
                    "regex_groups": groups,
                    "candidate_characters_in_sentence": [c for _, c, _ in nearby],
                })

    return {"segment_id": seg_id, "chapter": chapter, "kinship_candidates": kinship_candidates}


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    results = [scan_segment(seg) for seg in segments]
    results = [r for r in results if r["kinship_candidates"]]  # 只保留有命中的segment

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = sum(len(r["kinship_candidates"]) for r in results)
    print(f"✅ 亲属关系预扫描完成：{len(results)} 个 segment 命中，共 {total} 处候选 -> {output_file}")
    return results


if __name__ == "__main__":
    run()
