# -*- coding: utf-8 -*-
"""
extract_and_clean.py
--------------------
作用：清洗 04_manual.json，精准识别 absolute（绝对年龄）与 comparative/relative_diff（相对年龄差），
支持多类型事实动态导出，彻底解决类型混淆与字段丢弃问题。
"""

import json
from typing import Dict, List, Any

DEFAULT_INPUT = "./processed_data/04_manual.json"
DEFAULT_OUTPUT = "./processed_data/05_clean_facts.json"

def parse_facts_generically(input_file: str, output_file: str):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 兼容两种根结构：直接是 dict 包含 reviews，或者直接是 list/dict
    reviews = data.get("reviews", {}) if isinstance(data, dict) else {}
    if not reviews and isinstance(data, dict):
        reviews = data

    clean_records = []

    for item_key, review_body in reviews.items():
        if not isinstance(review_body, dict):
            continue

        final = review_body.get("final")
        if not final or not isinstance(final, dict):
            continue

        # 过滤无效提取
        if final.get("is_valid") is False:
            continue

        chapter = review_body.get("chapter", "")
        segment_id = review_body.get("segment_id")
        sentence = final.get("sentence", "")
        matched_text = final.get("matched_text", "")
        temporal_anchor = final.get("temporal_anchor", "PRESENT")

        # -------------------------------------------------------------
        # 1. 优先解析公共字段：主体人物 (real_subject) 与 候选人物 (candidates)
        # -------------------------------------------------------------
        candidates = final.get("candidate_characters") or final.get("candidate_characters_in_sentence") or []
        explicit_subject = final.get("subject")
        real_subject = explicit_subject or (candidates[0] if candidates else None)

        # 没有主体人物的脏数据直接跳过
        if not real_subject:
            continue

        # -------------------------------------------------------------
        # 2. 准确提取类型与判断条件
        # -------------------------------------------------------------
        clue_type_str = str(final.get("clue_type") or final.get("type") or "").lower()
        target_person = final.get("target_person") or final.get("raw_target_phrase")
        diff_val = final.get("age_diff") if final.get("age_diff") is not None else final.get("value")
        direction = final.get("direction", "大")

        is_comparative = (
            "comparative" in clue_type_str
            or "relative" in clue_type_str
            or (target_person is not None and final.get("age_diff") is not None)
        )

        # -------------------------------------------------------------
        # 3. 分支处理
        # -------------------------------------------------------------
        if is_comparative:
            # 相对年龄分支
            if diff_val is not None and target_person is not None:
                numeric_diff = int(diff_val) if direction == "大" else -int(diff_val)
                clean_records.append({
                    "source_key": item_key,
                    "chapter": chapter,
                    "segment_id": segment_id,
                    "sentence": sentence,
                    "matched_text": matched_text,
                    "clue_type": "relative_diff",
                    "subject": real_subject,       # 现在不会报错了
                    "target": target_person,
                    "diff_value": numeric_diff,
                    "temporal_anchor": temporal_anchor
                })

        else:
            # 绝对年龄分支
            stated_age = final.get("stated_age")
            raw_value = final.get("value")

            # 错位校验修复：数值冲突时优先以 stated_age 为准
            if stated_age is not None and raw_value is not None and stated_age != raw_value:
                age_val = stated_age
                if candidates:
                    real_subject = candidates[0]
            else:
                age_val = raw_value if raw_value is not None else stated_age

            if age_val is not None:
                clean_records.append({
                    "source_key": item_key,
                    "chapter": chapter,
                    "segment_id": segment_id,
                    "sentence": sentence,
                    "matched_text": matched_text,
                    "clue_type": "absolute",
                    "subject": real_subject,
                    "age_value": int(age_val),
                    "temporal_anchor": temporal_anchor
                })

    # 导出纯净 JSON 库
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=2)

    print(f"✅ 清洗完成！共处理输出 {len(clean_records)} 条有效线索至 {output_file}")

if __name__ == "__main__":
    parse_facts_generically(DEFAULT_INPUT, DEFAULT_OUTPUT)
