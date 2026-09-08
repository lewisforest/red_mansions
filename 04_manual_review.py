# -*- coding: utf-8 -*-
"""
04_manual_review.py (完全重构版)
-------------------
解决“以机器结果为主线导致漏掉正则候选”的架构缺陷。

关键改动：
1. 主线变更：改为【遍历 inputs 下的所有 age_candidates 和 kinship_candidates】。
2. 防漏机制：若机器 resolution 遗漏了某条候选，自动显示 [⚠️ 机器遗漏此线索]，按下 'e' 即可直接根据正则结果一键救回。
3. 交互优化：e (Edit) 模式全面采用正则匹配组 (regex_groups, stated_age 等) 作为默认输入提示。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from typing import Any, Dict, List, Optional

DEFAULT_INPUT = "./processed_data/04_fused_corrected.json"
DEFAULT_OUTPUT = "./processed_data/04_manual.json"


def load_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_save(path: str, data: Any):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def make_key(segment_id: int, item_type: str, candidate_index: int) -> str:
    return f"{segment_id}:{item_type}:{candidate_index}"


def prompt_text(label: str, default: Optional[str] = None) -> Optional[str]:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{label}{suffix}: ").strip()
    if not value:
        return default
    return value


def prompt_int(label: str, default: Any = None) -> Optional[int]:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{label}{suffix}: ").strip()
        if raw == "":
            if default is None:
                return None
            try:
                return int(default)
            except ValueError:
                return None
        try:
            return int(raw)
        except ValueError:
            print("请输入整数，或直接回车保留默认值。")


def base_get(machine: dict, candidate: dict, key: str) -> Any:
    """优先提取 candidate (正则)，不存在则退回 machine。"""
    return candidate.get(key) if candidate.get(key) is not None else machine.get(key)


def show_common(segment: dict, item_type: str, idx: int, candidate: dict, machine: Optional[dict]):
    print("\n" + "=" * 88)
    print(f"Segment #{segment.get('segment_id')} | {segment.get('chapter', '')}")
    print(f"条目类型: 【{item_type.upper()}】 | Candidate Index: [{idx}]")
    print("-" * 88)
    print("【原文句子】")
    print(candidate.get("sentence") or "")
    print("\n【物理线索 (Inputs Candidate - 正则解析结果)】")
    print(json.dumps(candidate, ensure_ascii=False, indent=2))

    print("\n【机器推理 (Machine Resolution)】")
    if machine:
        print(json.dumps(machine, ensure_ascii=False, indent=2))
    else:
        print("⚠️  [警告]: 机器推理 (Resolution) 遗漏了此条线索！(按下 'e' 可直接提取正则结果强行救回)")


def prompt_age_edit(machine: Optional[dict], candidate: dict) -> dict:
    """【修正/救回模式】强行捞取正则抓到的年龄差/绝对年龄物理数值。"""
    print("\n--- 正在修正/捞回【年龄数据】(优先使用正则物理字段打底) ---")
    machine = machine or {}

    matched_text = candidate.get("matched_text")
    clue_type = candidate.get("clue_type") or candidate.get("type")
    raw_target = candidate.get("raw_target_phrase")
    stated_age = candidate.get("stated_age")
    age_diff = candidate.get("age_diff")
    direction = candidate.get("direction")
    chars = candidate.get("candidate_characters_in_sentence") or candidate.get("candidate_characters") or []

    print(f"  [正则匹配片段]: {matched_text}")
    print(f"  [正则年龄/差值]: stated_age={stated_age}, age_diff={age_diff}")

    final = copy.deepcopy(candidate)
    final.update(machine)
    final["is_valid"] = True

    fact_type = prompt_text("年龄事实类型 (absolute/comparative)", "comparative" if clue_type == "comparative" else "absolute")
    final["type"] = fact_type

    default_subj = machine.get("subject") or (chars[0] if chars else None)

    if fact_type == "comparative":
        final["subject"] = prompt_text("主体人物", default_subj)
        final["target_person"] = prompt_text("参照人物", machine.get("target_person") or raw_target)
        final["direction"] = prompt_text("相对方向 (大/小)", machine.get("direction") or direction or "大")
        final["age_diff"] = prompt_int("年龄差数值", age_diff or machine.get("age_diff") or machine.get("value") or 1)
        final["value"] = final["age_diff"]
    else:
        final["subject"] = prompt_text("主体人物", default_subj)
        final["value"] = prompt_int("绝对年龄数值", stated_age or machine.get("value"))
        final["bound_type"] = prompt_text("年龄边界 (exact/about/less_than/at_least)", "exact")

    final["event_context"] = prompt_text("事件/情境", machine.get("event_context") or "年龄叙写")
    final["temporal_anchor"] = prompt_text("时态 (PRESENT/PAST/FUTURE)", machine.get("temporal_anchor") or "PRESENT")
    final["error_type"] = None

    return final


def prompt_kinship_edit(machine: Optional[dict], candidate: dict) -> dict:
    """【修正/救回模式】解构 regex_groups，自动生成默认人物关系。"""
    print("\n--- 正在修正/捞回【亲属关系】(优先解构正则捕获组 regex_groups) ---")
    machine = machine or {}

    regex_groups = candidate.get("regex_groups") or []
    pattern_desc = candidate.get("pattern_desc") or ""
    relation_hint = candidate.get("relation_type_hint") or ""
    chars = candidate.get("candidate_characters_in_sentence") or candidate.get("candidate_characters") or []

    print(f"  [正则匹配模式]: {pattern_desc}")
    print(f"  [正则捕获分组]: {regex_groups}")

    final = copy.deepcopy(candidate)
    final.update(machine)
    final["is_valid"] = True

    default_a = None
    default_b = None

    if len(regex_groups) >= 2:
        default_a = regex_groups[0]
        default_b = regex_groups[1]
    elif len(regex_groups) == 1:
        default_a = regex_groups[0]
        default_b = chars[0] if chars else None

    if default_a and "姨母" in default_a:
        default_a = default_a.replace("薛家姨母", "薛姨妈")

    default_relation = "parent"
    if "parent" in relation_hint:
        default_relation = "parent"
    elif "sibling" in relation_hint or "cousin" in relation_hint:
        default_relation = "cousin"

    final["relation"] = prompt_text("亲属关系类型", machine.get("relation") or default_relation)
    final["person_a"] = prompt_text("人物 A (尊长/主体)", machine.get("person_a") or default_a)
    final["person_b"] = prompt_text("人物 B (晚辈/客体)", machine.get("person_b") or default_b)
    final["temporal_anchor"] = prompt_text("时态 (PRESENT/PAST/FUTURE)", machine.get("temporal_anchor") or "PRESENT")
    final["error_type"] = None

    return final


def next_review_items(corrected: List[dict], reviewed: Dict[str, dict]):
    """
    核心重构：【以 INPUTS CANDIDATES 为主线】进行拉网式遍历！
    彻底防止机器遗漏数据导致人工无法校对。
    """
    for segment in corrected:
        inputs = segment.get("inputs") or {}
        resolution = segment.get("resolution") or {}
        seg_id = segment.get("segment_id")

        if seg_id is None:
            continue

        # 配置 (条目类型, inputs的key, resolution的key)
        type_mappings = [
            ("age", "age_candidates", "resolved_ages"),
            ("kinship", "kinship_candidates", "resolved_kinships")
        ]

        for item_type, in_key, res_key in type_mappings:
            candidates = inputs.get(in_key) or []
            resolved_list = resolution.get(res_key) or []

            # 建立以 candidate_index 为 key 的机器推理结果表
            machine_map = {}
            for m in resolved_list:
                if isinstance(m, dict) and isinstance(m.get("candidate_index"), int):
                    machine_map[m["candidate_index"]] = m

            # 遍历每一个正则 CANDIDATE！而不是机器结果！
            for idx, candidate in enumerate(candidates):
                review_key = make_key(int(seg_id), item_type, idx)
                if review_key in reviewed:
                    continue

                machine = machine_map.get(idx)  # 可能为 None (即机器漏掉)
                yield review_key, segment, item_type, idx, candidate, machine


def run(input_file: str = DEFAULT_INPUT, output_file: str = DEFAULT_OUTPUT):
    corrected = load_json(input_file, [])
    if not corrected:
        raise FileNotFoundError(f"找不到或无法读取 04 文件: {input_file}")

    raw_manual = load_json(output_file, {"schema_version": "04.manual.1", "source": input_file, "reviews": {}})
    reviews = raw_manual.get("reviews") if isinstance(raw_manual, dict) else {}
    if not isinstance(reviews, dict):
        reviews = {}

    items = list(next_review_items(corrected, reviews))
    print(f"当前已有人工记录：{len(reviews)} 条；待处理：{len(items)} 条。")
    if not items:
        print("✅ 没有新的待校对条目。")
        return raw_manual

    for offset, (review_key, segment, item_type, idx, candidate, machine) in enumerate(items, 1):
        show_common(segment, item_type, idx, candidate, machine)
        print(f"\n【进度】本次剩余 {len(items) - offset + 1} 条")

        if machine:
            print(" [y] 认可机器判断")
            print(" [e] 修正/捞回数据 (机器做错了或信息不全，由此重新填充)")
        else:
            print(" [e] 强行捞回数据 (机器漏掉了此条正则候选，直接提取物理线索)")

        print(" [d] 彻底废弃 (确认此条非有效数据, is_valid=False)")
        print(" [q] 保存并退出")

        while True:
            action = input("请选择操作 [y/e/d/q]: ").strip().lower()
            if action in {"y", "e", "d", "q"}:
                # 如果机器漏掉了，输入 'y' 自动提醒用户改按 'e'
                if not machine and action == "y":
                    print("⚠️ 机器没有针对此条给出判断，无法认可 'y'，请按 'e' 强行捞回或按 'd' 废弃。")
                    continue
                break
            print("非法指令，请输入 y / e / d / q。")

        if action == "q":
            atomic_save(output_file, {
                "schema_version": "04.manual.1",
                "source": input_file,
                "reviews": reviews,
            })
            print(f"已保存，退出：{output_file}")
            return reviews

        if action == "y" and machine:
            final_data = copy.deepcopy(candidate)
            final_data.update(machine)
            reason = "人工认可机器判断"
            status = "confirmed"

        elif action == "e":
            if item_type == "age":
                final_data = prompt_age_edit(machine, candidate)
            else:
                final_data = prompt_kinship_edit(machine, candidate)

            default_reason = "救回机器遗漏的正则物理线索" if not machine else "修正机器误判，人工重新录入有效实体与关系"
            reason = prompt_text("修改理由/备注", default_reason)
            status = "overridden"

        elif action == "d":
            final_data = copy.deepcopy(machine or candidate)
            final_data["is_valid"] = False
            final_data["relation"] = None
            final_data["person_a"] = None
            final_data["person_b"] = None
            final_data["error_type"] = "human_rejected"
            reason = prompt_text("废弃理由", "确认非有效事实/噪音数据")
            status = "overridden"

        review = {
            "segment_id": int(segment["segment_id"]),
            "chapter": segment.get("chapter", ""),
            "item_type": item_type,
            "candidate_index": idx,
            "status": status,
            "machine": machine,
            "final": final_data,
            "reason": reason,
        }

        reviews[review_key] = review
        atomic_save(output_file, {
            "schema_version": "04.manual.1",
            "source": input_file,
            "reviews": reviews,
        })
        print(f"✅ 已保存 {review_key} -> status: {status}, is_valid: {final_data.get('is_valid')}")

    print(f"\n✅ 人工校对完成，共 {len(reviews)} 条：{output_file}")
    return {
        "schema_version": "04.manual.1",
        "source": input_file,
        "reviews": reviews,
    }


def main():
    parser = argparse.ArgumentParser(description="对 04_fused_corrected.json 做拉网式人工校对")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
