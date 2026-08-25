# -*- coding: utf-8 -*-
"""
04_timeline_aligner.py
----------------------
阶段 04：事件驱动的全局时间轴推演与对齐脚本。
优先提取 02 阶段 events 列表中的细粒度时间标记，实现天数推算与锚点对齐。
"""

import json
import os
import re

# 汉字数字映射表，用于解析相对天数
CN_NUM = {
    '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
}


def _parse_cn_num(cn_str: str) -> int:
    """解析简单的中文数字字符串（如：三、十五）"""
    if not cn_str:
        return 1
    if cn_str in CN_NUM:
        return CN_NUM[cn_str]
    if len(cn_str) == 2 and cn_str.startswith('十'):
        return 10 + CN_NUM.get(cn_str[1], 0)
    return 1


def _classify_marker(marker_str: str) -> tuple:
    """
    对单个时间标记进行正则匹配与分类解析。

    返回 (kind, value):
      - "anchor": 宏观/节日时间锚点（如：中秋佳节、不知过了几世几劫）
      - "delta_days": 明确或可估算的天数增量（如：次日 +1, 三日后 +3, 一月后 +30）
      - "same_day": 日内时间推移（如：少顷、至晚、茶毕）
      - "unresolved": 无法定量的修饰性词汇（如：看罢诗后、忽一日）
    """
    if not marker_str or marker_str in ("未明确", "无"):
        return ("unresolved", None)

    text = marker_str.strip()

    # 1. 宏观锚点/时代变迁词/特定节日
    anchor_keywords = ["几世几劫", "元宵", "中秋", "端午", "重阳", "当年", "后来的事", "开篇"]
    for kw in anchor_keywords:
        if kw in text:
            return ("anchor", text)

    # 2. 日内时间推移（同一天）
    same_day_patterns = [
        r"少顷", r"须臾", r"片刻", r"说话间", r"即刻", r"茶毕", r"饭毕",
        r"至晚", r"晚间", r"当日", r"同日", r"一时", r"半响", r"半晌"
    ]
    for pat in same_day_patterns:
        if re.search(pat, text):
            return ("same_day", 0)

    # 3. 明确天数增量识别
    if re.search(r"次日|第二日|明日|越日|明儿", text):
        return ("delta_days", 1)
    if re.search(r"后天|第三日", text):
        return ("delta_days", 2)
    if "半月" in text:
        return ("delta_days", 15)

    # 正则匹配：[X]日后 / [X]天后
    m_day = re.search(r"([一二两三四五六七八九十]+)\s*[天日]后?", text)
    if m_day:
        days = _parse_cn_num(m_day.group(1))
        return ("delta_days", days)

    # 正则匹配：[X]个月后 / 次月
    if "次月" in text:
        return ("delta_days", 30)
    m_mon = re.search(r"([一二两三四五六七八九十]+)\s*个?月后?", text)
    if m_mon:
        mons = _parse_cn_num(m_mon.group(1))
        return ("delta_days", mons * 30)

    # 正则匹配：[X]年后 / [X]载 / 次年
    if "次年" in text:
        return ("delta_days", 365)
    m_yr = re.search(r"([一二两三四五六七八九十]+)\s*[年载]后?", text)
    if m_yr:
        yrs = _parse_cn_num(m_yr.group(1))
        return ("delta_days", yrs * 365)

    # 模糊天数估计
    if re.search(r"数日|过几日|几日后|没几天", text):
        return ("delta_days", 3)

    return ("unresolved", text)

from character_alias import clean_character_name, get_primary_characters
PRIMARY_CHARACTERS = get_primary_characters(min_aliases=4)

def align_timeline(records: list) -> list:
    """核心算法：按照 Segment 物理顺序串联事件，推算全局相对时间轴"""
    records_sorted = sorted(records, key=lambda r: r.get("segment_id", 0))

    timeline = []
    cumulative_days = 0
    last_anchor_label = "开篇初始"

    # {canonical_name: (anchor_cumulative_days, anchor_age)}
    age_anchors = {}

    for r in records_sorted:
        seg_id = r.get("segment_id")
        chapter = r.get("chapter")
        events = r.get("events", [])

        # 1. 时间标记提取：优先抽取事件级 time_marker，若无则使用顶层 time_markers 降级补充
        if events:
            markers = [ev["time_marker"] for ev in events if ev.get("time_marker") and ev["time_marker"] != "未明确"]
        else:
            markers = r.get("time_markers", []) or []

        # 去重并保持原有出现的先后顺序
        markers = list(dict.fromkeys(markers))

        # 2. 分类匹配与天数推演
        anchor_hit = None
        delta_hit = None
        same_day_hit = False

        for raw_marker in markers:
            kind, value = _classify_marker(raw_marker)
            if kind == "anchor" and anchor_hit is None:
                anchor_hit = (raw_marker, value)
            elif kind == "delta_days" and delta_hit is None:
                delta_hit = (raw_marker, value)
            elif kind == "same_day":
                same_day_hit = True

        matched_marker = None
        matched_kind = "none"
        applied_delta = 0

        # 处理锚点变动
        if anchor_hit:
            matched_marker, last_anchor_label = anchor_hit
            matched_kind = "anchor"

        # 处理相对天数增量
        if delta_hit:
            raw_marker, val = delta_hit
            cumulative_days += val
            applied_delta = val
            if not matched_marker:
                matched_marker = raw_marker
                matched_kind = "delta_days"
        elif same_day_hit and not matched_marker:
            matched_marker = "日内推移"
            matched_kind = "same_day"

        # 3. 置信度判定 (explicit / inferred / inherited)
        if matched_kind in ("anchor", "delta_days"):
            confidence = "explicit"
        elif matched_kind == "same_day":
            confidence = "inferred"
        else:
            confidence = "inherited"

        # --- 新增：吸收本段的显式年龄锚点 ---
        for ev in events:
            for am in ev.get("age_mentions", []):
                name = clean_character_name(am.get("character"))
                age = am.get("stated_age")
                if name and isinstance(age, (int, float)):
                    age_anchors[name] = (cumulative_days, age)

        # --- 新增：为在场的主要人物推算当前年龄 ---
        character_ages = {}
        for c in r.get("characters_present", []):
            if c in PRIMARY_CHARACTERS and c in age_anchors:
                anchor_day, anchor_age = age_anchors[c]
                estimated = anchor_age + (cumulative_days - anchor_day) / 365
                character_ages[c] = round(estimated, 1)
            # 不在 age_anchors 里的主要人物先留空，而不是瞎猜——
            # 后面一旦出现锚点，会自动补上，不需要现在编造

        # 4. 构建该 Segment 的对齐时间轴记录
        timeline_item = {
            "segment_id": seg_id,
            "chapter": chapter,
            "raw_time_markers": markers,
            "matched_marker": matched_marker,
            "matched_kind": matched_kind,
            "applied_delta_days": applied_delta,
            "cumulative_day_estimate": cumulative_days,
            "current_anchor": last_anchor_label,
            "confidence": confidence,
            "locations": r.get("locations", []),
            "characters_present": r.get("characters_present", []),
            "core_events": r.get("core_events", []),
            "event_details": events,  # 完整保留底层事件结构，供后续可视化或更细粒度分析使用
            "character_ages": character_ages,  # 只包含有锚点依据的人物
        }

        timeline.append(timeline_item)

    return timeline


def align_and_save_timeline(
    input_file="./processed_data/02_llm_extractions.json",
    output_file="./processed_data/04_timeline_aligned.json"
) -> list:
    """读取 02 结果，推算并保存全局时间轴 JSON"""
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return []

    with open(input_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    timeline = align_timeline(records)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

    print(f"✅ 全局时间轴对齐完成！共处理 {len(timeline)} 个文本块 -> {output_file}")
    return timeline


if __name__ == "__main__":
    align_and_save_timeline()
