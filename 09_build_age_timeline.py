# -*- coding: utf-8 -*-
"""
09_build_age_timeline.py
--------------------------
两件事：

1. 纠偏：06 有个系统性偏差——只要句子周围有"介绍某人生平"的叙事语气，就
   倾向于把年龄判成 milestone_age，哪怕句子里明明写着"现在""今年"这种
   强烈的"当前时刻"信号（比如"现在才十九岁""今年十五岁"）。这些被误判的
   案例，恰恰是全书最有价值的锚点（薛宝钗15岁生日那条就是被误判的典型），
   不修正会白白浪费。这里用确定性规则纠偏，不需要重新调用模型：只要
   milestone_age 对应的原句里，年龄数字前面紧邻着"现在/如今/今年/目今"，
   就重新归类为"当前年龄"，参与年龄差图谱。

2. 汇总：把 07（同框年龄+历史换算）和纠偏后的"当前年龄"，按 segment_id
   排序，重建年龄差图谱，再对每一个有锚点的 segment，用图遍历推算出
   全部关联人物在那个"坐标点"上的年龄，产出一张可读的时间线表：
   第几回 -> {人物: 年龄, ...}（标明哪些是原文直接写的，哪些是推算的）。

用法：
    python 09_build_age_timeline.py
"""

import json
import os
import re
from collections import defaultdict, deque

from character_alias import RAW_CHARACTER_MAP, clean_character_name

SAME_SCENE_FILE = "./processed_data/07_synthesized_age_mentions.json"
MILESTONES_FILE = "./processed_data/07_synthesized_age_mentions_biography_milestones.json"
NARRATIVE_SOURCE_FILE = "./processed_data/01_cleaned_segments.json"  # chapter信息的唯一权威来源
OUTPUT_FILE = "./processed_data/09_age_timeline.json"

# "现在/如今/今年/目今"——只要年龄数字前面几个字里出现这些词，说明这是
# "当前叙事时刻"的年龄，应该覆盖掉"milestone_age"这个误判。
CURRENT_TIME_OVERRIDE = ["现在", "如今", "今年", "目今", "而今"]

# 泛称/代词——不是具体人物，不应该进入年龄差图谱（比如"我们""孙子""一位
# 小姐"这种没有指向具体人名的主语，留着也没有交叉引用价值，反而可能制造
# 错误的图节点）。
GENERIC_PLACEHOLDERS = {
    "我们", "我", "你", "他", "她", "咱们",
    "一位小姐", "孙子", "三岁孩子", "小姐", "孩子", "女婿", "女孩子",
    "小丫头", "老太太", "少爷", "小丫头的", "小旦", "小丑",
}


def _is_known_or_proper_name(name: str) -> bool:
    """只保留看起来像具体人名的主语：要么在别名表的canonical列表里，要么
    至少不是我们列出的泛称/代词。"""
    if not name or name in GENERIC_PLACEHOLDERS:
        return False
    if name in RAW_CHARACTER_MAP:
        return True
    # 不在别名表里的，只要不是泛称，也放行（可能是张华、嫣红这类小角色，
    # 没有别名条目但确实是具体人名）
    return len(name) >= 2


def _check_current_time_override(sentence: str, age_str_hint: str) -> bool:
    """检查句子里年龄表达附近是否有'现在/今年'等强信号"""
    return any(kw in sentence for kw in CURRENT_TIME_OVERRIDE)


def _load_chapter_lookup() -> dict:
    """chapter 字段容易在中间环节漏传（这次就是07的biography_milestones漏了），
    与其让每个脚本都各自透传，不如统一以01（唯一权威来源）为准，按
    segment_id 查，从根上避免这类 KeyError。"""
    if not os.path.exists(NARRATIVE_SOURCE_FILE):
        print(f"⚠️ 找不到 {NARRATIVE_SOURCE_FILE}，chapter 信息将无法补全")
        return {}
    with open(NARRATIVE_SOURCE_FILE, "r", encoding="utf-8") as f:
        segments = json.load(f)
    return {s.get("segment_id"): s.get("chapter", "") for s in segments}


def load_and_reclassify(chapter_lookup: dict):
    same_scene_records = []
    if os.path.exists(SAME_SCENE_FILE):
        with open(SAME_SCENE_FILE, "r", encoding="utf-8") as f:
            same_scene_records = json.load(f)
        # same_scene_records里的chapter字段本身应该是齐的，但保险起见，
        # 如果为空也用01的数据补一次
        for r in same_scene_records:
            if not r.get("chapter"):
                r["chapter"] = chapter_lookup.get(r.get("segment_id"), "")

    reclassified_count = 0
    still_milestone = []

    if os.path.exists(MILESTONES_FILE):
        with open(MILESTONES_FILE, "r", encoding="utf-8") as f:
            milestones = json.load(f)

        for m in milestones:
            char = m["character"]
            if not _is_known_or_proper_name(char):
                continue  # 泛称/代词，直接丢弃，不进入任何后续统计

            chapter = chapter_lookup.get(m.get("segment_id"), "")  # 用01查，不再依赖m自带chapter字段

            if _check_current_time_override(m["sentence"], str(m["milestone_age"])):
                # 纠偏：重新归类为"当前年龄"，塞进 same_scene_records
                same_scene_records.append({
                    "segment_id": m["segment_id"],
                    "chapter": chapter,
                    "age_mentions": [{"character": char, "stated_age": m["milestone_age"]}],
                    "reclassified_from_milestone": True,
                    "original_note": m["note"],
                })
                reclassified_count += 1
            else:
                m["chapter"] = chapter  # 顺手把chapter补进履历记录里，方便你查阅
                still_milestone.append(m)

    print(f"🔧 纠偏：{reclassified_count} 条被06误判为履历年龄的'当前年龄'已重新归类")
    print(f"   仍保留为履历年龄（不参与当前年龄图谱）：{len(still_milestone)} 条")
    return same_scene_records, still_milestone


def build_graph(records: list):
    """和05的逻辑一致：同段多锚点 -> 年龄差边。
    顺手做冲突检测：同一对人物如果在不同 segment 算出的年龄差不一致
    （超过1岁），记下来供人工核查——这个功能原本在05里，05依赖已经放弃的
    02作为默认输入，属于孤儿脚本了，这里直接把这个功能合并进来，05可以
    不用再维护。"""
    graph = defaultdict(dict)
    anchors_by_char = defaultdict(list)  # 只收真实segment（正数id），用于展示
    same_scene_evidence = defaultdict(list)  # (a,b) -> [(segment_id, diff), ...]，用于冲突检测

    for r in records:
        seg_id = r.get("segment_id")
        seg_ages = {}
        for am in r.get("age_mentions", []):
            char = clean_character_name(am["character"]) or am["character"]
            if not _is_known_or_proper_name(char):
                continue
            seg_ages[char] = am["stated_age"]
            if isinstance(seg_id, int) and seg_id > 0:
                anchors_by_char[char].append((seg_id, r.get("chapter", ""), am["stated_age"]))

        names = list(seg_ages.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                diff = seg_ages[a] - seg_ages[b]
                graph[a][b] = diff
                graph[b][a] = -diff
                same_scene_evidence[(a, b)].append((seg_id, diff))

    conflicts = []
    for (a, b), evid in same_scene_evidence.items():
        diffs = [d for _, d in evid]
        if max(diffs) - min(diffs) > 1:
            conflicts.append({
                "pair": [a, b],
                "evidence": [{"segment_id": s, "age_diff": d} for s, d in evid],
                "note": "同一对人物在不同片段算出的年龄差不一致，可能是抽取错误，也可能是原文本身前后矛盾",
            })

    return graph, anchors_by_char, conflicts


def build_timeline(records: list, graph: dict):
    """对每个真实（正数）segment_id，用图遍历推算所有关联人物在那一刻的年龄"""
    timeline = []
    real_records = [r for r in records if isinstance(r.get("segment_id"), int) and r["segment_id"] > 0]
    real_records.sort(key=lambda r: r["segment_id"])

    for r in real_records:
        known = {}
        for am in r.get("age_mentions", []):
            char = clean_character_name(am["character"]) or am["character"]
            if _is_known_or_proper_name(char):
                known[char] = am["stated_age"]
        if not known:
            continue

        inferred = dict(known)
        queue = deque(known.keys())
        visited = set(known.keys())
        while queue:
            cur = queue.popleft()
            for neighbor, diff in graph.get(cur, {}).items():
                if neighbor not in visited:
                    inferred[neighbor] = inferred[cur] - diff
                    visited.add(neighbor)
                    queue.append(neighbor)

        extra_inferred = {k: v for k, v in inferred.items() if k not in known}

        timeline.append({
            "segment_id": r["segment_id"],
            "chapter": r.get("chapter", ""),
            "directly_stated": known,
            "inferred_from_graph": extra_inferred,
        })

    return timeline


def run():
    chapter_lookup = _load_chapter_lookup()
    same_scene_records, still_milestone = load_and_reclassify(chapter_lookup)
    graph, anchors_by_char, conflicts = build_graph(same_scene_records)
    timeline = build_timeline(same_scene_records, graph)

    output = {
        "timeline": timeline,
        "age_anchors_by_character": {
            char: [{"segment_id": s, "chapter": c, "stated_age": a} for s, c, a in entries]
            for char, entries in anchors_by_char.items()
        },
        "conflicts": conflicts,
        "unresolved_biography_milestones": still_milestone,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 时间线构建完成，共 {len(timeline)} 个有年龄锚点的坐标点 -> {OUTPUT_FILE}\n")

    if conflicts:
        print(f"--- ⚠️ 发现 {len(conflicts)} 处年龄差冲突，需要人工核查 ---")
        for c in conflicts:
            print(f"   {c['pair']}: {c['evidence']}")
        print()

    print("--- 按切片坐标排列的人物年龄时间线 ---")
    for item in timeline:
        stated_str = "、".join(f"{k}={v}岁" for k, v in item["directly_stated"].items())
        inferred_str = "、".join(f"{k}≈{v}岁(推算)" for k, v in item["inferred_from_graph"].items())
        line = f"[seg {item['segment_id']:>3}] {item['chapter'][:22]:<22} | 原文：{stated_str}"
        if inferred_str:
            line += f" | 推算：{inferred_str}"
        print(line)

    return output


if __name__ == "__main__":
    run()
