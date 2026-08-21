# -*- coding: utf-8 -*-
"""
04_timeline_aligner.py
把 02 抽取出的"人物/事件/时间词"，通过关键词锚点匹配 + 时间词增量推理，
对齐到一条全局时间轴上。

【和上一版的关键区别】
上一版用的是 CHAPTER_YEAR_BOUNDS——一张"第几回大概是第几年"的静态区间表，
完全不看这一段实际提到了谁、发生了什么事、有没有时间词，只看章节号落在哪个
区间。这样"网络"（03 统计出的人物关系）和"时间线"（04 算出的年份）之间没有
任何数据关联，看起来是两条互不相干的流水线，自然会觉得"不契合"。

这一版改成三层推理，全部基于这一段实际抽取出的内容，且都在 Python 里跑，
不需要 LLM 参与判断：

  第一层（高置信度）：关键词锚点匹配。用 network_graph.ANCHOR_GRAPH 里的
    关键词表，看这一段命中的人物+事件+时间词是否对应某个已知锚点事件
    （比如"贾敏""扬州""进京"→黛玉进府）。命中就把年份直接"钉"在锚点上，
    这一步会覆盖掉之前可能已经累积漂移的估计值，起纠偏作用。

  第二层（中置信度）：时间词增量推理。没命中锚点，但 time_markers 里有
    "次年""数年""十载"这类词，就在上一段的年份基础上加相应的年数
    （network_graph.TIME_DELTA_KEYWORDS）。

  第三层（低置信度）：都没命中，沿用上一段的年份（默认还在同一年）。

每一段都会记录 year_source 字段（anchor / inferred_delta / carried_forward），
方便你在最终报告里一眼看出哪些年份是有实锤证据的，哪些只是顺延猜测的。

同时保留了"逆向校验"——如果 LLM 把某个人物挂到了这一段，但这一段的
core_events 文本里根本没提到这个人（也没提到任何别名），就认为是 LLM 的
虚假挂载，直接从这一段的人物名单里剔除。
"""
import json
import os

from character_alias import clean_character_list, is_character_grounded
from network_graph import align_segment_to_graph, infer_year_delta_from_markers


def align_and_clean_timeline(
    input_file="./processed_data/02_llm_extractions.json",
    output_file="./processed_data/04_final_timeline.json",
    min_anchor_hits=2,
):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        extractions = json.load(f)

    # 必须按 segment_id（= 阅读顺序）处理，前向填充和锚点校准都依赖这个顺序
    extractions = sorted(extractions, key=lambda x: x.get("segment_id", 0))

    cleaned_results = []
    current_year = 0
    anchor_hits = 0
    delta_hits = 0
    carried_hits = 0

    for item in extractions:
        if item.get("error"):
            item["cleaned_characters"] = []
            item["calculated_year_num"] = current_year
            item["calculated_year"] = f"红楼第 {current_year} 年（推理失败，沿用上一段年份）"
            item["year_source"] = "error"
            cleaned_results.append(item)
            continue

        raw_chars = item.get("characters_present", [])
        core_events = item.get("core_events", []) or []
        time_markers = item.get("time_markers", []) or []
        full_event_text = "；".join(core_events)

        # 1. 别名归一化
        mapped_chars = clean_character_list(raw_chars)

        # 2. 逆向校验：事件文本里完全没提到的人物，剔除（防止 LLM 虚假挂载）
        grounded_chars = [c for c in mapped_chars if is_character_grounded(c, full_event_text)]

        # 3. 三层时间推理
        matches = align_segment_to_graph(grounded_chars, core_events, time_markers,
                                          min_hits=min_anchor_hits)
        if matches:
            best = matches[0]
            current_year = best["year_offset"]
            item["matched_anchor"] = best["anchor_id"]
            item["matched_anchor_desc"] = best["desc"]
            item["anchor_hit_count"] = best["hit_count"]
            item["year_source"] = "anchor"
            anchor_hits += 1
        else:
            delta = infer_year_delta_from_markers(time_markers)
            item["matched_anchor"] = None
            item["matched_anchor_desc"] = None
            item["anchor_hit_count"] = 0
            if delta > 0:
                current_year += delta
                item["year_source"] = "inferred_delta"
                delta_hits += 1
            else:
                item["year_source"] = "carried_forward"
                carried_hits += 1

        item["cleaned_characters"] = grounded_chars
        item["calculated_year_num"] = current_year
        source_label = {
            "anchor": "锚点校准",
            "inferred_delta": "时间词推算",
            "carried_forward": "顺延上段",
        }[item["year_source"]]
        item["calculated_year"] = f"红楼第 {current_year} 年（{source_label}）"

        cleaned_results.append(item)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(cleaned_results, f, ensure_ascii=False, indent=2)

    total = len(cleaned_results)
    print(f"✅ 04 对齐完成！共 {total} 条记录，其中：")
    print(f"   🔗 锚点直接校准 {anchor_hits} 条")
    print(f"   📈 时间词推算加年 {delta_hits} 条")
    print(f"   ➡️ 顺延上一段年份 {carried_hits} 条")
    if anchor_hits < total * 0.05:
        print(f"   ⚠️ 锚点命中率低于 5%，时间轴大部分依赖顺延/推算，建议往 "
              f"network_graph.ANCHOR_GRAPH 里补充更多锚点事件来提高精度。")


if __name__ == "__main__":
    align_and_clean_timeline()
