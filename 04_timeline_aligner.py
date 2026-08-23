# -*- coding: utf-8 -*-
"""
04_timeline_aligner.py
把 02 抽取出的"人物/事件/时间词"，通过 network_graph.py 的锚点匹配 + 时间词
增量推理，对齐到一条全局时间轴，并从真实的 age_mentions 数据里自动建立
人物出生年登记表。

本文件不重新定义任何锚点表或别名映射——那些都在 network_graph.py 和
character_alias.py 里，这里只 import 复用。

【和纯锚点匹配相比，这一版补的是什么】
锚点匹配只能告诉你"这一段对应第几年"，但没法告诉你"这一段里的人物当时几岁"。
之前那版要么完全没算年龄，要么我手滑写成了手动填一张年龄表（等于把你已经
在 02/03 里跑出来的真实数据晾在一边，自己编数据，被你正确地说是"脱裤子放
屁"）。

这一版改成：年龄登记表完全从 02 真实抽取出的 age_mentions 反推——
  出生年 = 该段计算出的年份 - 提到的年龄 + 1（虚岁计法）
只有【锚点直接命中】的段落（year_source == "anchor"，即有文本关键词实锤
证据支撑的年份）才用来【建立】出生年；"时间词推算"和"顺延上段"这两种
低置信度的年份只用来做【交叉校验】，如果算出来的出生年和已经建立的对不上，
记录成冲突，不会用来覆盖已经建立的结果。

出生年一旦确定，就能反过来给【所有】段落（不管是不是锚点命中）里出现的
已知人物自动算出当时年龄，不需要每段都有 age_mentions。
"""
import json
import os

from character_alias import clean_character_list, is_character_grounded
from network_graph import align_segment_to_graph, infer_year_delta_from_markers, ANCHOR_GRAPH


def _register_or_validate_birth_year(registry, conflicts, canon_name, implied_birth,
                                      chapter, segment_id, confidence, tolerance=1):
    """
    implied_birth 这里是"参照年"（不是虚岁意义上的出生年，而是 t=0 时这个人物
    应该是几岁的等效基准——具体换算方式由 ANCHOR_GRAPH 自己的计年方式决定，
    这里不额外强加"出生当年算1岁"之类的假设，保持和 network_graph.py 的
    year_offset 定义完全一致：implied_birth = t - age）。

    confidence == 'high'（锚点命中）：没有记录就建立；已有记录则做容差校验，
      在容差内取平均微调收敛，超出容差记录冲突（不覆盖已有值）。
    confidence == 'low'（时间词推算/顺延）：只用来交叉校验已有记录，不建立
      新记录、不修改已有值——避免用低置信度的年份反过来污染登记表。
    """
    if canon_name not in registry:
        if confidence == "high":
            registry[canon_name] = {
                "birth_year": implied_birth,
                "first_seen_chapter": chapter,
                "evidence": [],
            }
        return

    existing = registry[canon_name]["birth_year"]
    diff = abs(existing - implied_birth)
    if diff <= tolerance:
        if confidence == "high":
            registry[canon_name]["birth_year"] = round((existing + implied_birth) / 2, 1)
        return

    conflicts.append({
        "chapter": chapter,
        "segment_id": segment_id,
        "character": canon_name,
        "confidence": confidence,
        "existing_birth_year": existing,
        "implied_birth_year": implied_birth,
        "detail": f"{canon_name} 在此处反推出生年为 {implied_birth}，与已确立的 {existing} "
                  f"相差 {diff} 年（此条年份来源置信度：{confidence}）。",
    })


def align_and_clean_timeline(
    input_file="./processed_data/02_llm_extractions.json",
    output_file="./processed_data/04_final_timeline.json",
    registry_file=None,
    conflicts_file=None,
    chronology_md_file=None,
    min_anchor_hits=2,
):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    out_dir = os.path.dirname(output_file) or "."
    if registry_file is None:
        registry_file = os.path.join(out_dir, "04_character_registry.json")
    if conflicts_file is None:
        conflicts_file = os.path.join(out_dir, "04_conflicts.json")
    if chronology_md_file is None:
        chronology_md_file = os.path.join(out_dir, "红楼纪年表.md")

    with open(input_file, "r", encoding="utf-8") as f:
        extractions = json.load(f)

    extractions = sorted(extractions, key=lambda x: x.get("segment_id", 0))

    registry = {}
    conflicts = []
    cleaned_results = []
    current_year = 0
    anchor_hits = delta_hits = carried_hits = 0

    for item in extractions:
        if item.get("error"):
            item["cleaned_characters"] = []
            item["calculated_year_num"] = current_year
            item["calculated_year"] = f"红楼第 {current_year} 年（推理失败，沿用上一段年份）"
            item["year_source"] = "error"
            item["character_ages"] = {}
            cleaned_results.append(item)
            continue

        raw_chars = item.get("characters_present", [])
        core_events = item.get("core_events", []) or []
        time_markers = item.get("time_markers", []) or []
        full_event_text = "；".join(core_events)

        mapped_chars = clean_character_list(raw_chars)
        grounded_chars = [c for c in mapped_chars if is_character_grounded(c, full_event_text)]

        # ---- 三层时间推理（复用 network_graph.py，不重写） ----
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
            confidence = "high"
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
            confidence = "low"

        item["cleaned_characters"] = grounded_chars
        item["calculated_year_num"] = current_year
        source_label = {"anchor": "锚点校准", "inferred_delta": "时间词推算",
                         "carried_forward": "顺延上段"}[item["year_source"]]
        item["calculated_year"] = f"红楼第 {current_year} 年（{source_label}）"

        # ---- 从真实 age_mentions 反推/校验出生年（这是本次新增的部分） ----
        for am in item.get("age_mentions", []) or []:
            char_raw = am.get("character")
            age_num = am.get("age_num")
            if not char_raw or age_num is None:
                continue
            canon = clean_character_list([char_raw])
            if not canon:
                continue
            canon = canon[0]
            implied_birth = current_year - age_num  # 与 ANCHOR_GRAPH 的计年方式保持一致，不额外加虚岁修正
            _register_or_validate_birth_year(
                registry, conflicts, canon, implied_birth,
                item.get("chapter"), item.get("segment_id"), confidence,
            )
            if canon in registry:
                registry[canon]["evidence"].append({
                    "chapter": item.get("chapter"), "segment_id": item.get("segment_id"),
                    "age_mentioned": age_num, "reference_year": current_year,
                    "year_source": item["year_source"],
                })

        cleaned_results.append(item)

    # ---- 用最终收敛的出生年，反过来给每条记录标注在场人物当时年龄 ----
    birth_years = {name: info["birth_year"] for name, info in registry.items()}
    for item in cleaned_results:
        ref_year = item.get("calculated_year_num")
        ages = {}
        if ref_year is not None:
            for c in item.get("cleaned_characters", []):
                if c in birth_years and ref_year >= birth_years[c]:
                    ages[c] = round(ref_year - birth_years[c], 1)
        item["character_ages"] = ages

    os.makedirs(out_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(cleaned_results, f, ensure_ascii=False, indent=2)

    registry_out = {
        name: {"birth_year": info["birth_year"], "first_seen_chapter": info["first_seen_chapter"],
               "evidence_count": len(info["evidence"]), "evidence": info["evidence"]}
        for name, info in registry.items()
    }
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(registry_out, f, ensure_ascii=False, indent=2)

    with open(conflicts_file, "w", encoding="utf-8") as f:
        json.dump(conflicts, f, ensure_ascii=False, indent=2)

    # ---- 生成"锚点年表"：只挑锚点命中的段落，附上自动算出的人物年龄 ----
    anchor_rows = [item for item in cleaned_results if item.get("year_source") == "anchor"]
    md_lines = ["# 《红楼梦》核心锚点年表（数据来自真实抽取结果，非手工填写）\n"]
    md_lines.append("| 红楼纪年 (t) | 章节 | 命中锚点 | 核心人物年龄 |")
    md_lines.append("|---|---|---|---|")
    for r in anchor_rows:
        age_str = "、".join(f"{c} {a}岁" for c, a in r["character_ages"].items()) or "-"
        md_lines.append(f"| 第 {r['calculated_year_num']} 年 | {r['chapter']} | "
                         f"{r.get('matched_anchor_desc', '')} | {age_str} |")

    md_lines.append("\n---\n## 人物出生年登记（由真实 age_mentions 反推）\n")
    md_lines.append("| 人物 | 出生年 (红楼纪年) | 证据条数 |")
    md_lines.append("|---|---|---|")
    for name, info in sorted(registry_out.items(), key=lambda x: x[1]["birth_year"]):
        md_lines.append(f"| {name} | 第 {info['birth_year']} 年 | {info['evidence_count']} |")

    with open(chronology_md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    total = len(cleaned_results)
    print(f"✅ 04 对齐完成！共 {total} 条记录，其中：")
    print(f"   🔗 锚点直接校准 {anchor_hits} 条")
    print(f"   📈 时间词推算加年 {delta_hits} 条")
    print(f"   ➡️ 顺延上一段年份 {carried_hits} 条")
    print(f"   👤 人物出生年登记 {len(registry)} 人（来自真实 age_mentions，非手工填写）")
    print(f"   ⚠️ 检测到 {len(conflicts)} 条出生年冲突，见 {conflicts_file}")
    print(f"   📄 锚点年表：{chronology_md_file}")
    if anchor_hits < total * 0.05:
        print(f"   ⚠️ 锚点命中率低于 5%，建议往 network_graph.ANCHOR_GRAPH 里补充更多锚点事件。")


if __name__ == "__main__":
    align_and_clean_timeline()
