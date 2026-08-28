# -*- coding: utf-8 -*-
"""
08_bind_age_to_context.py
----------------------------
重新设计后的"02"：不再对全部567个切片盲目做"从零列举这段有哪些事件"这种
重活，而是反过来——拿着 00(正则)+06(LLM分类)+07(算术缝合)已经确认为真的
年龄锚点，回查 01 的【完整原文】（不再像老02那样二次切成300字小块，
信息不会因为二次切割而丢失或错位），只做一件很窄的事：

    "这个已知的年龄事实，对应全书的哪个坐标（第几回、这一回的哪个场景），
     此刻故事在讲什么（是倒叙介绍，还是正在发生的场景），
     有没有和上下文明显矛盾的地方？"

这是"确认"，不是"生成"——模型只需要在一段已经给定的原文里查找、判断，
不需要凭空列举一整段有哪些事件，任务难度和输出长度都远小于老02，理论上
会快很多，而且因为没有二次切割，不会因为切块边界切断线索而丢失信息。

产出的结果同时具备"切片坐标"（segment_id + chapter）和"人物年龄坐标"
（谁、几岁），可以直接喂给 04 做时间轴的硬校准点。

用法：
    python 08_bind_age_to_context.py
"""

import json
import os
import re
import requests

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:12b"

MERGED_AGE_FILE = "./processed_data/07_synthesized_age_mentions.json"
REASONING_TRAIL_FILE = "./processed_data/07_synthesized_age_mentions_reasoning_trail.json"
MILESTONES_FILE = "./processed_data/07_synthesized_age_mentions_biography_milestones.json"
NARRATIVE_SOURCE_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/08_age_context_bindings.json"

TIMEOUT_SECONDS = 600
MAX_RETRIES = 2

BINDING_SYSTEM_PROMPT = """你是一个精确的中文古典文本核对助手。你会收到一段完整的
原文，以及若干条【已经通过其他方式确认为真】的年龄事实。你的任务不是重新分析这段
文字有哪些情节，而是只做核对：

1. 用一句话说明这段原文此刻在讲什么（是在倒叙介绍某人生平，还是正在发生的现场场景）。
2. 对每一条给定的年龄事实，判断它是否能在这段原文里找到依据、是否与原文其他描述
   矛盾（比如某人被断言现在是40岁，但同一段原文又把他描写成在读书的孩童，就是矛盾）。
3. 不要编造任何原文没有的新信息，也不要给出这段原文之外的年龄或人物判断。

返回严格 JSON：
{
  "scene_type": "exposition" 或 "live_scene" 或 "mixed",
  "one_line_context": "一句话概括这段原文在讲什么，不超过30字",
  "fact_checks": [
    {"fact_summary": "复述其中一条给定事实", "supported_by_text": true/false,
     "contradiction_note": "如果矛盾，一句话说明；不矛盾则填空字符串"}
  ]
}
"""


def call_ollama_json(prompt_text: str, model_name: str = DEFAULT_MODEL_NAME) -> dict:
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "system": BINDING_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": 2048},
    }
    resp = requests.post(DEFAULT_OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    res_json = resp.json()
    raw = res_json.get("response", "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    eval_count = res_json.get("eval_count")
    eval_duration_ns = res_json.get("eval_duration")
    if eval_count and eval_duration_ns:
        print(f"      ⏱ {eval_count} token / {eval_duration_ns/1e9:.1f}s")
    return json.loads(raw)


def _collect_segment_facts():
    """把 07 的三份产出按真实 segment_id 归组，合成facts列表，附带原始句子"""
    facts_by_segment = {}

    def add_fact(seg_id, text):
        facts_by_segment.setdefault(seg_id, []).append(text)

    if os.path.exists(MERGED_AGE_FILE):
        with open(MERGED_AGE_FILE, "r", encoding="utf-8") as f:
            for rec in json.load(f):
                seg_id = rec.get("segment_id")
                if not isinstance(seg_id, int) or seg_id < 0:
                    continue  # 负数是07合成的历史锚点，没有对应的真实segment，跳过
                for am in rec.get("age_mentions", []):
                    add_fact(seg_id, f"{am['character']} 在此刻是 {am['stated_age']} 岁")

    if os.path.exists(REASONING_TRAIL_FILE):
        with open(REASONING_TRAIL_FILE, "r", encoding="utf-8") as f:
            for t in json.load(f):
                seg_id = t.get("source_segment_id")
                add_fact(seg_id, t["note"])

    if os.path.exists(MILESTONES_FILE):
        with open(MILESTONES_FILE, "r", encoding="utf-8") as f:
            for m in json.load(f):
                seg_id = m.get("segment_id")
                add_fact(seg_id, f"{m['character']} 在人生履历中的「{m['note']}」，年龄 {m['milestone_age']} 岁"
                                 f"（原句：{m['sentence']}）")

    return facts_by_segment


def run():
    if not os.path.exists(NARRATIVE_SOURCE_FILE):
        print(f"❌ 找不到 {NARRATIVE_SOURCE_FILE}")
        return

    facts_by_segment = _collect_segment_facts()
    if not facts_by_segment:
        print("⚠️ 没有找到任何可核对的年龄事实，请先跑 00 → 06 → 07")
        return

    with open(NARRATIVE_SOURCE_FILE, "r", encoding="utf-8") as f:
        segments = json.load(f)
    seg_by_id = {s.get("segment_id"): s for s in segments}

    results = []
    seg_ids = sorted(facts_by_segment.keys())
    print(f"🚀 需要核对 {len(seg_ids)} 个 segment（远少于全书567个，只处理有年龄证据的部分）\n" + "-" * 50)

    for i, seg_id in enumerate(seg_ids, 1):
        seg = seg_by_id.get(seg_id)
        if not seg:
            print(f"[{i}/{len(seg_ids)}] ⚠️ segment {seg_id} 在01数据里找不到，跳过")
            continue

        narrative = seg.get("narrative", "") or seg.get("text", "")
        chapter = seg.get("chapter", "")
        facts = facts_by_segment[seg_id]

        print(f"[{i}/{len(seg_ids)}] 核对 segment {seg_id}（{chapter[:20]}）| {len(facts)} 条待核实事实")

        facts_text = "\n".join(f"- {fact}" for fact in facts)
        prompt = f"完整原文：\n{narrative}\n\n需要核对的年龄事实：\n{facts_text}\n\n请核对。"

        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = call_ollama_json(prompt)
                break
            except Exception as e:
                print(f"      ⚠️ [尝试 {attempt}/{MAX_RETRIES}] 失败: {e}")

        if result is None:
            result = {"scene_type": "unknown", "one_line_context": "核对失败", "fact_checks": []}

        results.append({
            "segment_id": seg_id,
            "chapter": chapter,
            "facts_provided": facts,
            "binding_result": result,
        })

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成，共核对 {len(results)} 个 segment -> {OUTPUT_FILE}")

    contradictions = [
        (r["segment_id"], r["chapter"], fc)
        for r in results
        for fc in r["binding_result"].get("fact_checks", [])
        if not fc.get("supported_by_text", True)
    ]
    if contradictions:
        print(f"\n--- ⚠️ 发现 {len(contradictions)} 处矛盾，需要人工检查 ---")
        for seg_id, chapter, fc in contradictions:
            print(f"   seg {seg_id} ({chapter[:20]}): {fc['fact_summary']} —— {fc.get('contradiction_note', '')}")

    return results


if __name__ == "__main__":
    run()
