# -*- coding: utf-8 -*-
"""
03_aggregate.py
将逐段推理结果按章节聚合成时间线（JSON + 可读 Markdown）。

本版改动：新 schema 里 year_transition 多了 META_BACKGROUND（楔子/家族前史等元叙事），
这类内容不属于任何具体年份，聚合时单独放进"背景与世系"区块，不和正文时间线混在一起，
避免"楔子"这种段落被硬套上一个 offset_years 数字造成误导。
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
    name = chapter_name or ''
    if '序' in name or '凡例' in name or '楔子' in name:
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

    # META_BACKGROUND 的内容不参与线性年份时间轴，单独归类展示
    timeline_records = [r for r in valid_records if r.get("year_transition") != "META_BACKGROUND"]
    meta_records = [r for r in valid_records if r.get("year_transition") == "META_BACKGROUND"]

    def _group_by_chapter(records_list):
        by_chapter = {}
        for r in records_list:
            chapter = r.get("chapter", "未知章节")
            by_chapter.setdefault(chapter, []).append(r)
        return by_chapter

    def _build_summary(by_chapter):
        summary = []
        for chapter in sorted(by_chapter.keys(), key=chapter_sort_key):
            items = by_chapter[chapter]
            events, zhi_notes, lineage_notes, seasons, markers = [], [], [], [], []
            offset_years_in_chapter = []

            for it in items:
                events.extend(it.get("narrative_events", []) or [])
                zhi_notes.extend(it.get("zhi_corroborations", []) or [])
                lineage_notes.extend(it.get("background_and_lineage", []) or [])
                markers.extend(it.get("time_markers_found", []) or [])

                season = it.get("season_or_festival")
                if season and season not in seasons:
                    seasons.append(season)

                if "offset_years" in it:
                    offset_years_in_chapter.append(it["offset_years"])

            summary.append({
                "chapter": chapter,
                "chapter_order": chapter_sort_key(chapter),
                "offset_years_range": (
                    [min(offset_years_in_chapter), max(offset_years_in_chapter)]
                    if offset_years_in_chapter else None
                ),
                "season_or_festival": seasons or ["未明确提及"],
                "time_markers_found": list(dict.fromkeys(markers)),
                "background_and_lineage": list(dict.fromkeys(lineage_notes)),
                "events": list(dict.fromkeys(events)),
                "zhi_corroborations": list(dict.fromkeys(zhi_notes)),
                "segment_count": len(items),
            })
        return summary

    timeline_summary = _build_summary(_group_by_chapter(timeline_records))
    meta_summary = _build_summary(_group_by_chapter(meta_records))

    output_data = {
        "timeline": timeline_summary,
        "meta_background": meta_summary,
    }
    os.makedirs(os.path.dirname(output_json) or '.', exist_ok=True)
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    lines = ["# 《红楼梦》时间线梳理\n"]

    if meta_summary:
        lines.append("## 📜 背景与世系（元叙事，非线性年份情节）\n")
        for c in meta_summary:
            lines.append(f"### {c['chapter']}")
            if c["background_and_lineage"]:
                for b in c["background_and_lineage"]:
                    lines.append(f"- {b}")
            if c["events"]:
                lines.append("**相关内容**：")
                for e in c["events"]:
                    lines.append(f"- {e}")
            lines.append("")
        lines.append("---\n")

    lines.append("## 📖 正文时间线\n")
    for c in timeline_summary:
        lines.append(f"### {c['chapter']}")

        meta_bits = []
        if c["offset_years_range"]:
            lo, hi = c["offset_years_range"]
            meta_bits.append(f"累计年份 第{lo}年" if lo == hi else f"累计年份 第{lo}~{hi}年")
        meta_bits.append(f"节令：{' / '.join(c['season_or_festival'])}")
        lines.append(f"**{'　'.join(meta_bits)}**")
        if c["time_markers_found"]:
            lines.append(f"时间指示词：{' / '.join(c['time_markers_found'])}")
        lines.append("")

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

    print(f"✅ 聚合完成：正文时间线 {len(timeline_summary)} 个章节，"
          f"背景/元叙事 {len(meta_summary)} 个章节，{len(problem_records)} 条失败待复核。")
    print(f"   结构化结果：{output_json}")
    print(f"   可读摘要：{output_md}")


if __name__ == "__main__":
    aggregate_timeline(
        input_json="./output/timeline_analysis_result.json",
        output_json="./output/timeline_summary.json",
        output_md="./output/timeline_summary.md",
    )
