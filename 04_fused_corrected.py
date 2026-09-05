# -*- coding: utf-8 -*-
"""
04_fused_corrected.py
----------------------------------------------------------------------------------
融合版 V4.3（完整推理链与强制结构全映射版）：
1. 优化 System Prompt：强制 CoT 按照【句法还原 -> 实体校验 -> 结论推导】三步完备推理。
2. 增加代码层 Index 兜底机制：若 LLM 遗漏了 Candidate，自动补全 null 占位，保证 1:1 强映射。
3. 扩展模型输出 Token 上限并优化 JSON 解析解析容错。
"""

import json
import os
import re
import time
from typing import Any, Dict, List

import requests

try:
    from character_alias import SORTED_ALIAS_TUPLES
except ImportError:
    SORTED_ALIAS_TUPLES = []

# ==================== 配置区 ====================
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma3:12b"

INPUT_SEGMENTS = "./processed_data/01_cleaned_segments.json"
INPUT_AGE = "./processed_data/02_prescan_anchors.json"
INPUT_KINSHIP = "./processed_data/03_kinship_candidates.json"
OUTPUT_FILE = "./processed_data/04_fused_corrected.json"

TIMEOUT_SECONDS = 300
MAX_RETRIES = 3

ZHI_PI_PATTERN = re.compile(r"\[脂批\d*.*?\]|\[.*?\]|【.*?】|（.*?）")
session = requests.Session()

# ==================== 极简高容错 System Prompt ====================
VERIFICATION_SYSTEM_PROMPT = """你是一个精通中国历代白话文（明清小说、三言二拍、近代公文等）的【严谨语法与语义解析引擎】。

你的任务是：读取给定的白话文段落及候选线索（Candidates），在【绝对不产生逻辑幻觉】的前提下，完成实体识别、句法解构与事实裁决。

==================================================
【核心解构与判定法则】：

1. 1:1 候选索引强制严格映射（绝对禁止遗漏！）：
   - 【极其重要】：输入 inputs 中 age_candidates 的数量为 N，输出 resolved_ages 数组必须精确包含 N 项，按 candidate_index (0, 1, ..., N-1) 依次审查！
   - 同理，kinship_candidates 的数量为 M，resolved_kinships 也必须精确包含 M 项 (0, 1, ..., M-1)！
   - 每一个 candidate_index 都必须独立生成一条对应的 verification 对象，绝对禁止跳过、合并或覆盖！

2. 完备推理链格式要求（Reasoning Requirements）：
   - reasoning 字段必须**完整包含以下三步推理过程**，严禁使用一句话概括或省略：
     * [句法还原]：分析本句主语/代词（如“他”、“这丫头”、“主子”）在上下文中的实际指代对象，分析动作与修饰语的归属。
     * [实体校验]：核对提取出的实体是否为具体人物，剥离形容词/动作，确认是否为规则误抓（如数字误判为年龄、语气词误判为亲属）。
     * [结论推导]：结合叙事时态判定 PRESENT / PAST / FUTURE，说明最终判定 is_valid 为 true/false 的充分理由。

3. 多年龄线索指代与阶段解构 (Multi-Clue General Resolution)：
   - 当同一文本段落中出现多个年龄线索时，必须首先判定这些线索指代的是【同一人】还是【不同人】：
     * 【若为同一人】：表示该人物的【不同生平阶段/履历】。每个年龄 Candidate 均有效，需在 event_context 中提炼其对应的事件或状态。
     * 【若为不同人】：表示分别介绍【不同人物的情况】。必须严格把年龄绑定给其直接修饰的具体人物，严禁错挂主语。

4. 实体清洗与隐式称谓消歧 (Entity Standardisation & Disambiguation)：
   - 实体净化：剥离伴随的动态修饰词、状态副词或叙事动词，仅保留纯粹的人物名称或身份代号。
   - 代词还原：结合上下文，将人称代词、指示代词、相对称谓精准还原为明确人物实体。
   - 匿名实体标准化：若无真实姓名，使用结构：“[已知关联实体]之[关系/身份]”。

5. 零容忍伪线索裁决 (Zero-Tolerance False Match)：
   - 规则误匹配拦截：若 Candidate 属于误抓，必须判定 is_valid: false。
   - 无效数据清空：判定 is_valid: false 时，实体名称、关系类型及数值等 Key 强行归零（置为 null），严禁残留无效或推测性文本。

6. 时态与时空锚定 (Temporal State & Mortality Evaluation)：
   - PRESENT：仅用于描述当前叙事时间节点下【确凿成立且人物处于存活状态】的属性或关系。
   - PAST：用于描述过往生平里程碑、回忆性事件，或【人物已被明确证实身故或关系已终止】的情形。
   - FUTURE：用于描述尚未发生、假设性或预测性的状态。

==================================================
【输出 JSON 严格结构】：
{
  "resolved_ages": [
    {
      "candidate_index": 0,
      "reasoning": "[句法还原] ... [实体校验] ... [结论推导] ...",
      "is_valid": true,
      "type": "absolute | idiom_age | bounded | null",
      "subject": "清洗后的确定实体或标准抽象结构（无效时为 null）",
      "value": 数值年龄或 null,
      "event_context": "事件/阶段描述或 null",
      "temporal_anchor": "PRESENT | PAST | FUTURE | null",
      "error_type": null | "regex_false_positive" | "subject_unclear" | "out_of_context"
    }
  ],
  "resolved_kinships": [
    {
      "candidate_index": 0,
      "reasoning": "[句法还原] ... [实体校验] ... [结论推导] ...",
      "is_valid": true,
      "relation": "配偶 | 亲子 | 姐弟 | 兄妹 | 姐妹 | 兄弟 | 祖孙 | 主仆 | unclear | null",
      "person_a": "清洗后的主体A（确定实体，无效时为 null）",
      "person_b": "清洗后的主体B（确定实体，无效时为 null）",
      "temporal_anchor": "PRESENT | PAST | FUTURE | null",
      "error_type": null | "regex_false_positive" | "context_insufficient"
    }
  ]
}
"""

# ==================== 工具函数 ====================

def clean_text_noise(text: str) -> str:
    if not text:
        return ""
    return ZHI_PI_PATTERN.sub("", text).strip()


def scan_full_segment_characters(text: str) -> List[str]:
    found = set()
    for alias, canon in SORTED_ALIAS_TUPLES:
        if len(alias) >= 2 and alias in text:
            found.add(canon)
    return sorted(list(found))


def deduplicate_candidates(candidates: list) -> list:
    seen = set()
    deduped = []
    for c in candidates:
        key = c.get("sentence", "").strip()
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def locate_and_build_context(clean_narrative: str, candidates: list) -> str:
    focused_contexts = []
    for cand in candidates:
        idx = cand.get("candidate_index", 0)
        raw_sentence = cand.get("sentence", "")
        clean_sentence = clean_text_noise(raw_sentence)
        if not clean_sentence:
            continue

        pos = clean_narrative.find(clean_sentence)
        if pos == -1 and len(clean_sentence) > 6:
            pos = clean_narrative.find(clean_sentence[:6])

        if pos != -1:
            start = max(0, pos - 80)
            end = min(len(clean_narrative), pos + len(clean_sentence) + 80)
            snippet = clean_narrative[start:end]
            focused_contexts.append(f'[Index {idx} 上下文]: "...{snippet}..."')
        else:
            focused_contexts.append(f'[Index {idx} 文本]: "{clean_sentence}"')

    return "\n".join(focused_contexts) if focused_contexts else "（无定位片段）"


def safe_parse_json(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


def call_llm(prompt: str) -> Dict[str, Any]:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": VERIFICATION_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "keep_alive": "15m",
        "options": {
            "temperature": 0.0,
            "num_predict": 4096,  # 扩展至 4096 以防止完整的推理被截断
            "num_ctx": 8192,
        },
    }
    resp = session.post(OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return safe_parse_json(raw)


def enforce_candidate_coverage(
    res_list: List[Dict[str, Any]], expected_count: int, is_age: bool
) -> List[Dict[str, Any]]:
    """代码兜底层：确保输出的 Candidate 数组在 index 上 1:1 精确映射，缺少的自动用失败模板补齐"""
    existing_map = {
        item.get("candidate_index"): item
        for item in res_list
        if isinstance(item, dict) and "candidate_index" in item
    }

    complete_list = []
    for idx in range(expected_count):
        if idx in existing_map:
            complete_list.append(existing_map[idx])
        else:
            # LLM 漏掉了该索引，进行代码自动保底填充
            if is_age:
                complete_list.append({
                    "candidate_index": idx,
                    "reasoning": "[模型跳过/推理未覆盖] 缺失输出，由代码兜底补齐归零。",
                    "is_valid": False,
                    "type": None,
                    "subject": None,
                    "value": None,
                    "event_context": None,
                    "temporal_anchor": None,
                    "error_type": "out_of_context"
                })
            else:
                complete_list.append({
                    "candidate_index": idx,
                    "reasoning": "[模型跳过/推理未覆盖] 缺失输出，由代码兜底补齐归零。",
                    "is_valid": False,
                    "relation": None,
                    "person_a": None,
                    "person_b": None,
                    "temporal_anchor": None,
                    "error_type": "context_insufficient"
                })
    return complete_list


def resolve_segment(
    clean_prefix: str,
    clean_narrative: str,
    age_candidates: list,
    kinship_candidates: list,
    char_list: list,
) -> Dict[str, Any]:

    age_candidates = deduplicate_candidates(age_candidates)
    kinship_candidates = deduplicate_candidates(kinship_candidates)

    if not age_candidates and not kinship_candidates:
        return {
            "resolved_ages": [],
            "resolved_kinships": [],
            "supplementary_findings": [],
            "_error": False,
            "_note": "无 Candidates，跳过 LLM"
        }

    indexed_age_cands = []
    for idx, c in enumerate(age_candidates):
        item = dict(c)
        item["candidate_index"] = idx
        indexed_age_cands.append(item)

    indexed_kinship_cands = []
    for idx, c in enumerate(kinship_candidates):
        item = dict(c)
        item["candidate_index"] = idx
        indexed_kinship_cands.append(item)

    all_cands = indexed_age_cands + indexed_kinship_cands
    location_highlights = locate_and_build_context(clean_narrative, all_cands)

    prompt = f"""
【前文背景摘要】：
...{clean_prefix[-300:] if clean_prefix else "无"}

【当前正文片段】：
{clean_narrative}

【已知人物列表】：{char_list}

【定位上下文】：
{location_highlights}

【待审查年龄候选 (age_candidates) - 共 {len(indexed_age_cands)} 项】：
{json.dumps(indexed_age_cands, ensure_ascii=False, indent=2)}

【待审查亲属候选 (kinship_candidates) - 共 {len(indexed_kinship_cands)} 项】：
{json.dumps(indexed_kinship_cands, ensure_ascii=False, indent=2)}

请务必按顺序审查候选（Index 从 0 到 N-1/M-1）。每一项均需给出完整的三段式 reasoning 推理过程。
严格返回 JSON 校验结构。
"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = call_llm(prompt)
            if isinstance(res, dict) and any(k in res for k in ["age_verifications", "kinship_verifications", "resolved_ages", "resolved_kinships"]):
                ages_raw = res.get("age_verifications") or res.get("resolved_ages") or []
                kinships_raw = res.get("kinship_verifications") or res.get("resolved_kinships") or []

                # 执行 1:1 候选覆盖强校验
                resolved_ages = enforce_candidate_coverage(ages_raw, len(indexed_age_cands), is_age=True)
                resolved_kinships = enforce_candidate_coverage(kinships_raw, len(indexed_kinship_cands), is_age=False)

                return {
                    "resolved_ages": resolved_ages,
                    "resolved_kinships": resolved_kinships,
                    "supplementary_findings": [],
                    "_error": False,
                }
            print(f"      ⚠️ [尝试 {attempt}/{MAX_RETRIES}] LLM 输出格式未命中目标 Key，重试...")
        except Exception as e:
            print(f"      ⚠️ [尝试 {attempt}/{MAX_RETRIES}] 请求异常: {e}")
            time.sleep(attempt * 2)

    return {
        "resolved_ages": [],
        "resolved_kinships": [],
        "supplementary_findings": [],
        "_error": True,
    }


def atomic_save(filepath: str, data: List[Dict[str, Any]]):
    tmp = f"{filepath}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)


# ==================== 主流程 ====================

def run():
    if not os.path.exists(INPUT_SEGMENTS):
        raise FileNotFoundError(f"找不到输入文件: {INPUT_SEGMENTS}")

    with open(INPUT_SEGMENTS, "r", encoding="utf-8") as f:
        segments = {item["segment_id"]: item for item in json.load(f)}

    age_by_seg = {}
    if os.path.exists(INPUT_AGE):
        with open(INPUT_AGE, "r", encoding="utf-8") as f:
            for item in json.load(f):
                seg_id = item["segment_id"]
                cands = [a for a in item.get("age_candidates", []) if a.get("needs_llm_review")]
                cands.extend(item.get("relation_candidates", []))
                if cands:
                    age_by_seg[seg_id] = cands

    kinship_by_seg = {}
    if os.path.exists(INPUT_KINSHIP):
        with open(INPUT_KINSHIP, "r", encoding="utf-8") as f:
            for item in json.load(f):
                if item.get("kinship_candidates"):
                    kinship_by_seg[item["segment_id"]] = item["kinship_candidates"]

    all_seg_ids = sorted(segments.keys())

    results_map = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_list = json.load(f)
                results_map = {r["segment_id"]: r for r in existing_list}
        except Exception as e:
            print(f"⚠️ 读取现有输出文件失败，将重新建立索引: {e}")

    pending_ids = [
        s for s in all_seg_ids
        if s not in results_map or results_map[s].get("resolution", {}).get("_error")
    ]

    print(
        f"🚀 总计待分析 {len(all_seg_ids)} 个 segment，本次待执行 {len(pending_ids)} 个\n"
        + "-" * 70
    )

    for i, seg_id in enumerate(pending_ids, 1):
        seg = segments.get(seg_id, {})
        chapter = seg.get("chapter", "")

        raw_prefix = seg.get("prefix", "")
        raw_narrative = seg.get("narrative", "")
        clean_prefix = clean_text_noise(raw_prefix)
        clean_narrative = clean_text_noise(raw_narrative)

        age_cands = age_by_seg.get(seg_id, [])
        kinship_cands = kinship_by_seg.get(seg_id, [])

        for c in age_cands:
            if "sentence" in c:
                c["sentence"] = clean_text_noise(c["sentence"])
        for c in kinship_cands:
            if "sentence" in c:
                c["sentence"] = clean_text_noise(c["sentence"])

        full_context_for_chars = f"{clean_prefix}\n{clean_narrative}"
        char_list = scan_full_segment_characters(full_context_for_chars)

        print(
            f"[{i}/{len(pending_ids)}] Seg #{seg_id}（{chapter[:12]}...）| {len(age_cands)}年龄 + {len(kinship_cands)}亲属线索 | 识别人物: {char_list}"
        )

        res = resolve_segment(
            clean_prefix,
            clean_narrative,
            age_cands,
            kinship_cands,
            char_list,
        )

        results_map[seg_id] = {
            "segment_id": seg_id,
            "chapter": chapter,
            "inputs": {
                "age_candidates": age_cands,
                "kinship_candidates": kinship_cands,
            },
            "resolution": res,
        }

        output_list = [results_map[sid] for sid in sorted(results_map.keys())]
        atomic_save(OUTPUT_FILE, output_list)

    print(f"\n✅ 质检纠错全部完成！最终结果存至 -> {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
