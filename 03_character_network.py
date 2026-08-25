# -*- coding: utf-8 -*-
"""
03_character_network.py (升级版：支持事件级 active/mentioned 关联计算)
"""

import json
import os
from collections import Counter, defaultdict
from itertools import combinations
from character_alias import is_character_grounded

EVENT_ACTIVE_WEIGHT = 3    # 同一微事件内同时出场（强互动）
EVENT_MENTION_WEIGHT = 1   # 在对话/思考中被提及（弱关联）
MAX_EVIDENCE_PER_EDGE = 5

def _extract_leading_number(filename: str):
    m = re.match(r"^0*(\d+)", filename)
    return int(m.group(1)) if m else None

def build_network(records: list) -> dict:
    node_freq = Counter()
    edge_weight = Counter()
    segment_co_count = Counter()
    event_co_count = Counter()
    edge_evidence = defaultdict(list)

    for r in records:
        if r.get("error"):
            continue

        events = r.get("events", [])

        # 如果有事件列表，走精细化事件级统计；若无，降级走顶层汇总统计
        if events:
            for ev in events:
                actives = ev.get("active_characters", [])
                mentions = ev.get("mentioned_characters", [])

                # 1. 统计节点频次（仅计算真实出场角色）
                for c in actives:
                    node_freq[c] += 1

                # 2. 强关联：同一事件中同时出场的人物 (Active - Active)
                for pair in combinations(dict.fromkeys(actives), 2):
                    key = tuple(sorted(pair))
                    edge_weight[key] += EVENT_ACTIVE_WEIGHT
                    event_co_count[key] += 1

                    if len(edge_evidence[key]) < MAX_EVIDENCE_PER_EDGE:
                        edge_evidence[key].append({
                            "segment_id": r.get("segment_id"),
                            "chapter": r.get("chapter"),
                            "event_summary": ev.get("summary")
                        })

                # 3. 弱关联：出场人物提及第三方 (Active - Mentioned)
                for a in actives:
                    for m in mentions:
                        if a != m:
                            key = tuple(sorted([a, m]))
                            edge_weight[key] += EVENT_MENTION_WEIGHT
                            event_co_count[key] += 1

        else:
            # 降级备用逻辑：兼容旧格式
            chars_present = r.get("characters_present", [])
            for c in chars_present:
                node_freq[c] += 1
            for pair in combinations(dict.fromkeys(chars_present), 2):
                key = tuple(sorted(pair))
                edge_weight[key] += 1
                segment_co_count[key] += 1

    edges = []
    for key, weight in edge_weight.items():
        edges.append({
            "source": key[0],
            "target": key[1],
            "weight": weight,
            "event_comention": event_co_count.get(key, 0),
            "segment_cooccurrence": segment_co_count.get(key, 0),
            "evidence": edge_evidence.get(key, []),
        })

    edges.sort(key=lambda e: e["weight"], reverse=True)
    nodes = [{"name": name, "appearance_count": cnt}
             for name, cnt in sorted(node_freq.items(), key=lambda x: -x[1])]

    return {"nodes": nodes, "edges": edges}


def _try_export_graphml(network: dict, output_file: str):
    try:
        import networkx as nx
    except ImportError:
        return

    g = nx.Graph()
    for node in network["nodes"]:
        g.add_node(node["name"], appearance_count=node["appearance_count"])
    for edge in network["edges"]:
        g.add_edge(edge["source"], edge["target"], weight=edge["weight"],
                   event_comention=edge["event_comention"])

    graphml_path = os.path.splitext(output_file)[0] + ".graphml"
    nx.write_graphml(g, graphml_path)
    print(f"  📈 已额外导出 GraphML: {graphml_path}")

def clean_batch_files(input_dir, output_file, min_chars=800, max_chars=1500):
    raw_files = [f for f in os.listdir(input_dir) if f.endswith(".txt")]
    files = sorted(
        raw_files,
        key=lambda f: (_extract_leading_number(f) is None, _extract_leading_number(f) or 0, f)
    )
    # 建议加一行自检打印，方便你人工确认顺序对不对
    print("文件处理顺序：", files)


def build_and_save_network(input_file="./processed_data/02_llm_extractions.json",
                           output_file="./processed_data/03_character_network.json"):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    network = build_network(records)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(network, f, ensure_ascii=False, indent=2)

    print(f"✅ 人物关系网络已生成：{len(network['nodes'])} 个人物节点，"
          f"{len(network['edges'])} 条关系边 -> {output_file}")

    _try_export_graphml(network, output_file)
    return network


if __name__ == "__main__":
    build_and_save_network()
