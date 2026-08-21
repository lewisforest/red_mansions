# -*- coding: utf-8 -*-
"""
05_report_generator.py
生成人物履历轨迹与同纪年多线事件交集报告。

本版改动：每条记录带上 year_source 对应的图标（🔗 锚点校准 / 📈 时间词推算 /
➡️ 顺延上段），报告里直接可见，而不是把"这个年份到底有多可信"这件事藏起来。
"""
import json
import os
from collections import defaultdict

SOURCE_ICON = {
    "anchor": "🔗",
    "inferred_delta": "📈",
    "carried_forward": "➡️",
    "error": "⚠️",
}


def generate_biography_and_intersection_report(
    input_file="./processed_data/04_final_timeline.json",
    output_file="./output/红楼梦人物履历与事件交集年表.md",
    network_file="./processed_data/03_character_network.json",
):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        timeline_data = json.load(f)

    timeline_data = sorted(timeline_data, key=lambda x: x.get("segment_id", 0))

    char_bios = defaultdict(list)
    yearly_events = defaultdict(list)

    for seg in timeline_data:
        year = seg.get("calculated_year", "未确定时间")
        icon = SOURCE_ICON.get(seg.get("year_source"), "")
        chapter = seg.get("chapter", "未知章节")
        events_text = "；".join(seg.get("core_events", [])) or "无明确事件"
        valid_chars = seg.get("cleaned_characters", [])

        yearly_events[year].append({
            "chapter": chapter,
            "chars": valid_chars,
            "events": events_text,
            "icon": icon,
        })

        for c in valid_chars:
            other_chars = [o for o in valid_chars if o != c]
            char_bios[c].append({
                "year": year,
                "icon": icon,
                "chapter": chapter,
                "event": events_text,
                "cross_chars": other_chars,
            })

    md_lines = [
        "# 《红楼梦》人物命运履历与跨线事件交集报告\n",
        "> 图标含义：🔗 锚点直接校准（高置信度） / 📈 时间词推算（中置信度） / "
        "➡️ 顺延上一段年份（低置信度，仅供参考）\n",
        "---\n",
        "## 📌 视图一：核心人物编年履历轨迹\n",
    ]

    target_focus = ["香菱", "林黛玉", "贾宝玉", "薛宝钗", "贾雨村", "王熙凤", "贾母"]
    sorted_chars = sorted(char_bios.keys(), key=lambda k: len(char_bios[k]), reverse=True)
    ordered_chars = [c for c in target_focus if c in char_bios] + [c for c in sorted_chars if c not in target_focus]

    for char_name in ordered_chars:
        records = char_bios[char_name]
        if len(records) < 2 and char_name not in target_focus:
            continue
        md_lines.append(f"### 👤 人物：{char_name}（共涉及 {len(records)} 个关键段落）\n")
        md_lines.append("| 时间节点 | 所在章节 | 事件简析与人物轨迹 | 同场/交集人物 |")
        md_lines.append("|---|---|---|---|")
        for r in records:
            cross_str = "、".join(r["cross_chars"][:6]) if r["cross_chars"] else "无"
            md_lines.append(f"| {r['icon']} **{r['year']}** | {r['chapter']} | {r['event']} | {cross_str} |")
        md_lines.append("\n---\n")

    md_lines.append("## 📅 视图二：同纪年多线事件同步交集轴\n")
    for year, seg_list in yearly_events.items():
        md_lines.append(f"### ⏳ {year}\n")
        for s in seg_list:
            chars_str = "、".join(s["chars"]) if s["chars"] else "无明确人物"
            md_lines.append(f"* {s['icon']} **[{s['chapter']}]** {s['events']}")
            md_lines.append(f"  * *同场人物*：{chars_str}")
        md_lines.append("")

    # 如果人物关系网络文件存在，附上一个简要的关系网络摘要，让报告和网络数据对得上号
    if os.path.exists(network_file):
        with open(network_file, "r", encoding="utf-8") as f:
            network_data = json.load(f)
        top_edges = network_data.get("edges", [])[:15]
        if top_edges:
            md_lines.append("---\n## 🕸️ 视图三：核心人物关系网络（按共现频次排序前 15）\n")
            md_lines.append("| 人物 A | 人物 B | 共现次数 | 典型场景 |")
            md_lines.append("|---|---|---|---|")
            for e in top_edges:
                sample = e.get("sample_events", [])
                sample_str = sample[0] if sample else "无"
                md_lines.append(f"| {e['source']} | {e['target']} | {e['weight']} | {sample_str} |")
            md_lines.append("")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"🎉 报告生成成功！高可读性 Markdown 已存至: {output_file}")


if __name__ == "__main__":
    generate_biography_and_intersection_report()
