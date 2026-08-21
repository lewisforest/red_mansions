# -*- coding: utf-8 -*-
"""
03_character_network.py
基于段落人物共现自动构建人物关系网络图谱。

本版改动：
1. 别名映射改为从 character_alias.py 导入共享的 ALIAS_MAP/NOISE_WORDS，
   不再自己维护一份——避免和 04_timeline_aligner.py 用的映射表不一致，
   导致同一人物在网络和时间线里被算成两个不同的名字。
2. 每条边（人物关系）额外记录几条"共同出现时的具体事件"作为示例，
   这样这份网络不只是一堆抽象的数字权重，而是能直接给 04 提供"这两个人
   在什么情境下产生关联"的证据，也是人在看报告时判断关系是否靠谱的依据。
3. 记录每个人物"首次出场"的章节和 segment_id，供后续排查/展示用。
"""
import json
import os
from collections import Counter, defaultdict

from character_alias import clean_character_list, is_character_grounded


def build_character_network(input_file="./processed_data/02_llm_extractions.json",
                             output_file="./processed_data/03_character_network.json",
                             min_cooccurrence=2,
                             max_sample_events=3):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        extractions = json.load(f)

    # 按 segment_id 排序，保证"首次出场"的判断是按真实阅读顺序来的
    extractions = sorted(extractions, key=lambda x: x.get("segment_id", 0))

    char_freq = Counter()
    first_seen = {}  # canonical_name -> {"chapter":..., "segment_id":...}
    co_occurrence = defaultdict(int)
    co_occurrence_events = defaultdict(list)  # pair -> [事件描述, ...]

    for item in extractions:
        if item.get("error"):
            continue

        cleaned_chars = clean_character_list(item.get("characters_present", []))
        events = item.get("core_events", []) or []
        event_text = "；".join(events)

        # 逆向校验：和 04_timeline_aligner.py 用的是同一套逻辑——如果 LLM 把某个
        # 人物挂到了这一段，但事件文本里根本没提到这个人（也没提到任何别名），
        # 就不计入网络统计。这一步如果不做，03 统计出来的网络会包含一些 04 最终
        # 过滤掉的"虚假挂载"人物，两边人物集合对不上，就是"网络和时间线不契合"
        # 的直接原因之一。
        cleaned_chars = [c for c in cleaned_chars if is_character_grounded(c, event_text)]

        for c in cleaned_chars:
            char_freq[c] += 1
            if c not in first_seen:
                first_seen[c] = {
                    "chapter": item.get("chapter", "未知章节"),
                    "segment_id": item.get("segment_id"),
                }

        for i in range(len(cleaned_chars)):
            for j in range(i + 1, len(cleaned_chars)):
                pair = tuple(sorted([cleaned_chars[i], cleaned_chars[j]]))
                co_occurrence[pair] += 1
                if event_text and len(co_occurrence_events[pair]) < max_sample_events:
                    if event_text not in co_occurrence_events[pair]:
                        co_occurrence_events[pair].append(event_text)

    nodes = [
        {
            "id": name,
            "label": name,
            "degree": count,
            "first_seen_chapter": first_seen.get(name, {}).get("chapter"),
            "first_seen_segment_id": first_seen.get(name, {}).get("segment_id"),
        }
        for name, count in char_freq.items()
    ]

    edges = []
    for (source, target), weight in co_occurrence.items():
        if weight >= min_cooccurrence:
            edges.append({
                "source": source,
                "target": target,
                "weight": weight,
                "sample_events": co_occurrence_events.get((source, target), []),
            })

    network_data = {
        "stats": {
            "total_characters": len(nodes),
            "total_relations": len(edges),
        },
        "nodes": sorted(nodes, key=lambda x: x["degree"], reverse=True),
        "edges": sorted(edges, key=lambda x: x["weight"], reverse=True),
    }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(network_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 人物网络构建完成！清洗后剩余 {len(nodes)} 个核心角色，{len(edges)} 条有效关系边。")


if __name__ == "__main__":
    build_character_network()
