# -*- coding: utf-8 -*-
"""
03_aggregate.py
将逐段推理结果按章节聚合成时间线（JSON + 可读 Markdown）。
"""

import os
import re
import json

CHAPTER_NUM_PATTERN = re.compile(r'第([一二三四五六七八九十百零两]+)\s*回')
CN_DIGITS = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def cn_to_int(s: str):
    if not s:
        return None
    s = s.replace('两', '二')
    total = 0
    if '百' in s:
        left, s = s.split('百', 1)
        total += (CN_DIGITS.get(left, 1) if left else 1) * 100
    if '十' in s:
        left, s = s.split('十', 1)
        total += (CN_DIGITS.get(left, 1) if left else 1) * 10
    if s:
        total += CN_DIGITS.get(s, 0)
    return total


def chapter_sort_key(chapter_name: str):
    """序言/凡例排在最前面（order -1），其余按回目数字排序，识别不了的排最后"""
    name = chapter_name or ''
    if '序' in name or '凡例' in name:
        return -1
    m = CHAPTER_NUM_PATTERN.search(name)
    if not m:
        return 9999
    num = cn_to_int(m.group(1))
    return num if num is not None else 9999


def aggregate_timeline(input_json: str, output_json: str, output_md: str):
    if not os.path.exists(input_json):
        print(f"❌ 找不到 {input_json}，请先运行推理步骤。")
        return

    with open(input_json, 'r', encoding='utf-8') as f:
        records = json.load(f)

    if not records:
        print("❌ 输入的推理 JSON 文件为空！请检查步骤 1 与步骤 2 的运行日志。")
        return

    valid_records = [r for r in records if r and not r.get("error")]
    problem_records = [r for r in records if r and r.get("error")]

    by_chapter = {}
    for r in valid_records:
        chapter = r.get("chapter", "未知章节")
        by_chapter.setdefault(chapter, []).append(r)

    sorted_chapters = sorted(by_chapter.keys(), key=chapter_sort_key)

    timeline_summary = []
    for chapter in sorted_chapters:
        items = by_chapter[chapter]
        events, zhi_notes, lineage_notes, seasons = [], [], [], []
        offset_years_in_chapter = []

        for it in items:
            events.extend(it.get("narrative_events", []) or [])
            zhi_notes.extend(it.get("zhi_corroborations", []) or [])
            lineage_notes.extend(it.get("background_and_lineage", []) or [])

            season = it.get("season_or_festival")
            if season and season != "未明确提及" and season not in seasons:
                seasons.append(season)

            if "offset_years" in it:
                offset_years_in_chapter.append(it["offset_years"])

        timeline_summary.append({
            "chapter": chapter,
            "chapter_order": chapter_sort_key(chapter),
            "offset_years_range": (
                [min(offset_years_in_chapter), max(offset_years_in_chapter)]
                if offset_years_in_chapter else None
            ),
            "season_or_festival": seasons or ["未明确提及"],
            "background_and_lineage": list(dict.fromkeys(lineage_notes)),
            "events": list(dict.fromkeys(events)),
            "zhi_corroborations": list(dict.fromkeys(zhi_notes)),
            "segment_count": len(items),
        })

    os.makedirs(os.path.dirname(output_json) or '.', exist_ok=True)
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(timeline_summary, f, ensure_ascii=False, indent=2)

    lines = ["# 《红楼梦》时间线梳理\n"]
    for c in timeline_summary:
        lines.append(f"## {c['chapter']}")

        meta_bits = []
        if c["offset_years_range"]:
            lo, hi = c["offset_years_range"]
            meta_bits.append(f"累计年份 {lo}~{hi}" if lo != hi else f"累计年份 第{lo}年")
        meta_bits.append(f"节令：{' / '.join(c['season_or_festival'])}")
        lines.append(f"**{'　'.join(meta_bits)}**\n")

        if c["background_and_lineage"]:
            lines.append("**世系/年龄背景**：")
            for b in c["background_and_lineage"]:
                lines.append(f"- {b}")
            lines.append("")

        if c["events"]:
            lines.append("**事件**：")
            for e in c["events"]:
                lines.append(f"- {e}")

        if c["zhi_corroborations"]:
            lines.append("\n**脂批印证**：")
            for z in c["zhi_corroborations"]:
                lines.append(f"- {z}")

        lines.append("")

    if problem_records:
        lines.append("---\n## ⚠️ 推理失败记录")
        lines.append(f"共 {len(problem_records)} 条推理失败，未计入以上时间线，"
                      f"重新运行 02_pipeline.py 会自动只重跑这些：\n")
        for p in problem_records[:50]:
            lines.append(f"- {p.get('chapter', '?')}：{p.get('error', '未知错误')}")
        if len(problem_records) > 50:
            lines.append(f"- ...（其余 {len(problem_records) - 50} 条见 JSON 结果文件）")

    os.makedirs(os.path.dirname(output_md) or '.', exist_ok=True)
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"✅ 聚合完成：处理 {len(sorted_chapters)} 个章节，{len(valid_records)} 条有效推理记录，"
          f"{len(problem_records)} 条失败待复核。")
    print(f"   结构化结果：{output_json}")
    print(f"   可读摘要：{output_md}")


if __name__ == "__main__":
    aggregate_timeline(
        input_json="./output/timeline_analysis_result.json",
        output_json="./output/timeline_summary.json",
        output_md="./output/timeline_summary.md",
    )
