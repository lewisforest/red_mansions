# -*- coding: utf-8 -*-
"""
test_partial_pipeline.py
-------------------------
用 02_checkpoint.json（目前已经处理完的那部分 segment，哪怕只有 60 条）
直接喂给 03（人物关系网）和 04（时间轴对齐），提前验证这两段算法逻辑对不对，
不用等全部 567 条跑完。

原理：run_pipeline 每处理完一条 segment 就把当前 results 整体写入
CHECKPOINT_FILE，checkpoint 里每条记录的结构和最终 02_llm_extractions.json
完全一样（同一个 dict，同一套字段）。所以可以直接把 checkpoint 路径当作
input_file 传给 03/04 的函数，不用等主流程跑完生成正式输出。

注意：
- 这只是用来验证“算法逻辑对不对”，不是最终结果。60/567 条数据量小，
  统计出来的人物关系权重、时间跨度都只反映故事最开头这一小段，
  不能当成全书的结论。
- 04 的时间轴推演依赖 segment_id 的顺序，checkpoint 里哪怕只有前 60 条，
  顺序也是连续的（1~60 左右），所以“相对时间关系”在这一小段内部是有效的，
  这正是适合先验证的部分。

用法：
    python test_partial_pipeline.py
"""

import importlib.util
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "processed_data")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "02_checkpoint.json")


def _load_module(filename: str):
    """和 main.py 里一模一样的动态加载方式（因为文件名数字开头，不能直接 import）"""
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到脚本文件: {path}")
    module_name = filename[:-3].replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main():
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"❌ 找不到 checkpoint 文件: {CHECKPOINT_FILE}")
        print("   说明 02 阶段还一条都没处理完，没有可以测试的数据。")
        return

    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        checkpoint_data = json.load(f)

    print(f"📦 读取到 checkpoint 中 {len(checkpoint_data)} 条已处理的 segment")
    seg_ids = sorted(r.get("segment_id") for r in checkpoint_data)
    print(f"   segment_id 范围：{seg_ids[0]} ~ {seg_ids[-1]}")
    print(f"   ⚠️ 这只覆盖故事最开头一小段，人物关系权重/时间跨度都不是最终结论，"
          f"只用来验证 03/04 的算法逻辑对不对。\n")

    # --- 03：人物关系网络（用 checkpoint 直接当输入）---
    print("=" * 60)
    print("▶ 用 checkpoint 测试 03（人物关系网络）")
    print("=" * 60)
    m3 = _load_module("03_character_network.py")
    network = m3.build_and_save_network(
        input_file=CHECKPOINT_FILE,
        output_file=os.path.join(DATA_DIR, "03_character_network_PARTIAL_TEST.json"),
    )
    if network:
        print("\n--- 人物出场频次 Top 10（仅这部分数据）---")
        for node in network["nodes"][:10]:
            print(f"   {node['name']}: {node['appearance_count']} 次")
        print("\n--- 关系权重 Top 10（仅这部分数据）---")
        for edge in network["edges"][:10]:
            print(f"   {edge['source']} — {edge['target']}: 权重 {edge['weight']}"
                  f"（事件共现 {edge['event_comention']} 次）")

    # --- 04：时间轴对齐（用 checkpoint 直接当输入）---
    print("\n" + "=" * 60)
    print("▶ 用 checkpoint 测试 04（时间轴对齐）")
    print("=" * 60)
    m4 = _load_module("04_timeline_aligner.py")
    timeline = m4.align_and_save_timeline(
        input_file=CHECKPOINT_FILE,
        output_file=os.path.join(DATA_DIR, "04_timeline_PARTIAL_TEST.json"),
    )
    if timeline:
        print("\n--- 时间轴前 15 条（检查 matched_kind / confidence 是否合理）---")
        for item in timeline[:15]:
            print(f"   seg {item['segment_id']:>3} | {item['matched_kind']:<10} | "
                  f"累计第{item['cumulative_day_estimate']}天 | "
                  f"锚点={item['current_anchor']} | "
                  f"置信度={item['confidence']} | "
                  f"标记词={item['raw_time_markers']}")

    print(f"\n✅ 测试完成。完整结果已写入：")
    print(f"   {os.path.join(DATA_DIR, '03_character_network_PARTIAL_TEST.json')}")
    print(f"   {os.path.join(DATA_DIR, '04_timeline_PARTIAL_TEST.json')}")
    print("   （文件名带 PARTIAL_TEST，不会覆盖正式的 03/04 输出）")


if __name__ == "__main__":
    main()
