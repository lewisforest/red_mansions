# -*- coding: utf-8 -*-
"""
07_synthesize_age_facts.py
----------------------------
06 的设计原则是"只结构化，不推理"——每次只看一处孤立的年龄信息，绝不跨事实
做计算。这带来的后果是：即使同一段话里同时出现了"如海现在40岁"和
"儿子去年死时3岁"，06 也不会主动把这两条事实联系起来算出"如海39岁时儿子
死了、两人相差36岁"——这是对的，06 不该赌模型会不会算对这道减法题。

这一步就是专门做这件事的：读 06 的输出，用确定性的 Python 算术（不是模型）
把散落的事实缝合成两类可用数据：

1. 【同段共现】：同一个 segment 里出现的多个 "absolute" 锚点（比如如海=40，
   黛玉=5），直接输出成 05 能识别的 age_mentions 格式，05 会自动把它们
   当作"同框"证据建立年龄差边。

2. 【历史锚点换算】：past_relative 类型的事实（比如"儿子去年死时3岁"），
   如果同一 segment 里能找到一个 absolute 锚点作为"现在"的参照
   （如海=40），且时间关键词能换算出明确的偏移量（"去岁/去年"=1年，
   "前年"=2年；"早年/当年/那年"这种模糊词没法量化，直接跳过，不瞎猜），
   就能算出历史那个时间点的参照人年龄（40-1=39），再和 past_relative
   里的年龄（3）配成一对"历史同框"证据，一样喂给 05 建立年龄差边
   （如海 39 岁 vs 儿子 3 岁 → 相差36岁）。这类合成的"同框"没有真实的
   segment_id/日期归属，只作为年龄差图谱的证据，不参与04的天数时间轴。

每一步推理都会记录 reasoning trail，方便你审查这条边到底是怎么算出来的，
而不是变成一个不透明的黑箱数字。

用法：
    python 07_synthesize_age_facts.py
    然后把输出喂给 05：
    python 05_age_network.py --input processed_data/07_synthesized_age_mentions.json
    （或者用 05 的 --extra-input 把这份数据和02的正式输出合并一起跑，见05的更新）
"""

import json
import os
from collections import defaultdict

from character_alias import clean_character_name

INPUT_FILE = "./processed_data/06_age_relations_resolved.json"
OUTPUT_FILE = "./processed_data/07_synthesized_age_mentions.json"

# 能明确量化的"过去时间"偏移量（年）。凑不出准确数字的（早年/当年/那年这种
# 模糊表达）宁可跳过，也不瞎猜——这些留在原始事实里，不参与年龄差计算。
KNOWN_OFFSETS = {
    "去岁": 1, "去年": 1, "前年": 2, "旧年": 1,
}

_NEG_ID_COUNTER = -1_000_000  # 合成的"历史同框"用负数id，和真实segment_id区分开


def _next_synthetic_id():
    global _NEG_ID_COUNTER
    _NEG_ID_COUNTER -= 1
    return _NEG_ID_COUNTER


def _detect_offset(sentence: str):
    for kw, years in KNOWN_OFFSETS.items():
        if kw in sentence:
            return years, kw
    return None, None


def synthesize(resolved_items: list) -> dict:
    # 按 segment 分组，方便找"同段内的其他锚点"
    by_segment = defaultdict(list)
    for item in resolved_items:
        by_segment[item["segment_id"]].append(item)

    same_scene_records = []       # 直接同框的 absolute 锚点，按真实 segment_id 归组
    derived_historical_records = []  # past_relative 换算出来的历史同框，用合成id
    reasoning_trail = []          # 每一条历史换算的推理过程记录，供审查
    biography_milestones = []     # milestone_age：某人一生履历中的年龄节点，
                                   # 不参与"当前年龄"冲突判断，单独存档供人工查阅

    for seg_id, items in by_segment.items():
        absolute_facts = []
        for it in items:
            res = it["llm_resolution"]

            if res.get("type") == "milestone_age":
                canon = clean_character_name(res.get("subject"))
                val = res.get("value")
                if canon and isinstance(val, (int, float)):
                    biography_milestones.append({
                        "segment_id": seg_id,
                        "chapter": it.get("chapter", ""),  # 之前漏了这个字段，09要用
                        "character": canon,
                        "milestone_age": int(val),
                        "sentence": it["sentence"],
                        "note": res.get("reasoning_note", ""),
                    })
                continue  # milestone_age 不进入 absolute_facts，不参与同框/冲突判断

            if res.get("type") != "absolute":
                continue
            canon = clean_character_name(res.get("subject"))
            val = res.get("value")
            if canon and isinstance(val, (int, float)):
                absolute_facts.append({"character": canon, "stated_age": int(val), "raw_subject": res.get("subject")})

        if absolute_facts:
            # 安全检查：同一 segment 里，同一个人不该有两个不同的"当前年龄"。
            # 如果出现了，说明06分类还是判断错了（该判成milestone_age却判成
            # absolute），直接跳过这个人在本段的记录并报出来，而不是让05
            # 静默地用"最后一个值覆盖前一个值"，那样会悄悄丢信息还不自知。
            by_char_ages = defaultdict(set)
            for f in absolute_facts:
                by_char_ages[f["character"]].add(f["stated_age"])

            clean_facts = []
            for f in absolute_facts:
                if len(by_char_ages[f["character"]]) > 1:
                    print(f"    ⚠️ segment {seg_id} 内 {f['character']} 出现多个不同的'当前年龄'"
                          f"{by_char_ages[f['character']]}，可能是06把milestone_age误判成了absolute，"
                          f"本段该人物的年龄暂不采用，请人工检查")
                else:
                    clean_facts.append(f)

            if clean_facts:
                same_scene_records.append({
                    "segment_id": seg_id,
                    "chapter": items[0].get("chapter", ""),
                    "age_mentions": [{"character": f["character"], "stated_age": f["stated_age"]} for f in clean_facts],
                })

        # past_relative 换算：需要同段内至少一个 absolute 锚点作为"现在"的参照
        for it in items:
            res = it["llm_resolution"]
            if res.get("type") != "past_relative":
                continue
            sentence = it["sentence"]
            offset_years, offset_keyword = _detect_offset(sentence)
            if offset_years is None:
                continue  # 量化不出偏移量，跳过，不瞎猜

            past_subject_canon = clean_character_name(res.get("subject"))
            past_age = res.get("value")
            if not past_subject_canon or not isinstance(past_age, (int, float)):
                continue

            # 找同段内"现在"的参照锚点：优先选和 past_subject 不同的人物
            # （比如儿子的过去年龄，参照如海现在的年龄）
            reference = next((f for f in absolute_facts if f["character"] != past_subject_canon), None)
            if reference is None:
                continue

            historical_ref_age = reference["stated_age"] - offset_years
            synthetic_id = _next_synthetic_id()
            derived_historical_records.append({
                "segment_id": synthetic_id,
                "chapter": it.get("chapter", ""),
                "age_mentions": [
                    {"character": reference["character"], "stated_age": historical_ref_age},
                    {"character": past_subject_canon, "stated_age": int(past_age)},
                ],
            })
            reasoning_trail.append({
                "synthetic_segment_id": synthetic_id,
                "source_segment_id": seg_id,
                "sentence": sentence,
                "reference_character": reference["character"],
                "reference_now_age": reference["stated_age"],
                "offset_keyword": offset_keyword,
                "offset_years": offset_years,
                "computed_historical_age": historical_ref_age,
                "past_subject": past_subject_canon,
                "past_subject_age": int(past_age),
                "age_gap_derived": historical_ref_age - int(past_age),
                "note": (f"{reference['character']}现在{reference['stated_age']}岁，"
                         f"「{offset_keyword}」即{offset_years}年前，"
                         f"故推算{reference['character']}当时{historical_ref_age}岁，"
                         f"与{past_subject_canon}（{past_age}岁）相差"
                         f"{historical_ref_age - int(past_age)}岁"),
            })

    return {
        "same_scene_records": same_scene_records,
        "derived_historical_records": derived_historical_records,
        "reasoning_trail": reasoning_trail,
        "biography_milestones": biography_milestones,
    }


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}，请先跑 06_age_llm_correction.py")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        resolved_items = json.load(f)

    result = synthesize(resolved_items)

    # 供05直接使用的合并列表（真实同框 + 合成的历史同框）
    merged_for_05 = result["same_scene_records"] + result["derived_historical_records"]

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged_for_05, f, ensure_ascii=False, indent=2)

    trail_file = output_file.replace(".json", "_reasoning_trail.json")
    with open(trail_file, "w", encoding="utf-8") as f:
        json.dump(result["reasoning_trail"], f, ensure_ascii=False, indent=2)

    milestone_file = output_file.replace(".json", "_biography_milestones.json")
    with open(milestone_file, "w", encoding="utf-8") as f:
        json.dump(result["biography_milestones"], f, ensure_ascii=False, indent=2)

    print(f"✅ 缝合完成：")
    print(f"   {len(result['same_scene_records'])} 个 segment 内发现多锚点同框")
    print(f"   {len(result['derived_historical_records'])} 条历史年龄差是靠 past_relative + 偏移量换算出来的")
    print(f"   {len(result['biography_milestones'])} 条人生履历年龄节点（不参与当前年龄比对，单独存档）")
    print(f"   -> {output_file}（可直接喂给05）")
    print(f"   -> {trail_file}（每条历史换算的完整推理过程，供审查）")
    print(f"   -> {milestone_file}（人生履历年龄节点，供单独查阅）")

    if result["reasoning_trail"]:
        print("\n--- 历史换算推理过程 ---")
        for t in result["reasoning_trail"]:
            print(f"   [来自seg{t['source_segment_id']}] {t['note']}")

    return result


if __name__ == "__main__":
    run()
