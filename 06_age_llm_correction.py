# -*- coding: utf-8 -*-
"""
06_age_llm_correction.py
--------------------------
只处理 00_prescan_anchors.py 标记出来的"需要判断关系"的候选：
    - age_candidates 里 needs_llm_review=True 的（比如同句多个候选人物、
      或者句子里有"去岁"这类过去时间参照词）
    - 所有 relation_candidates（比较级"比XX大/小N岁"、跨度"过了N年"）

和 02 的区别：02 每次要读几百字、理解整段情节、抽取一串事件，输出是一长串
JSON；这里每次只喂一句话，模型要做的只是"结构化这一句话本身已经写明的
关系"，不需要理解上下文情节，输出也就是几个字段的小 JSON。理论上单次
调用应该在几秒到几十秒量级，而不是02那种几分钟。

用法：
    python 06_age_llm_correction.py
"""

import json
import os
import re
import time
import requests

from character_alias import clean_character_name

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:12b"
INPUT_FILE = "./processed_data/00_prescan_anchors.json"
NARRATIVE_SOURCE_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/06_age_relations_resolved.json"
TIMEOUT_SECONDS = 300  # 单句极短任务，300s 足够，如果还超时说明有别的问题
MAX_RETRIES = 2

CORRECTION_SYSTEM_PROMPT = """你是一个精确的中文古典文本分析助手。你会收到：
1. 一整段原文（可能有好几句话），
2. 其中被正则表达式标注出来的一处年龄相关信息（用【】标出具体是哪一句、哪个词），
3. 一份"候选人物名单"（这段原文里出现过的人物称呼）。

你的任务只有一个：判断这处年龄信息表达的是什么关系，绝不能引入原文之外的知识或臆测。

【重要】关于人物归属：
- 如果候选人物名单里有具体人名，并且原文能看出这个年龄描述的就是这个人
  （哪怕描述用的是"小丫头""小旦"这种泛称，但原文紧接着点出了具体名字，
  比如"……的小丫头，名唤作雪雁"），你必须把 subject 填成具体人名"雪雁"，
  而不是泛称"小丫头"。
- 如果原文用"我"自称，且这一整段文字里能看出说话人是谁（比如前面有
  "黛玉道：""某某笑道："这类标记），把 subject 填成那个具体人名。
- 如果读完整段文字依然无法确定具体是谁，才可以填写原文里的泛称或代词，
  并在 reasoning_note 里说明"上下文不足，无法确定具体人物"。
- 绝对不要自己"计算"或"推理"出一个新的年龄数字（比如不要因为看到"某人比
  另一人大N岁"就去反推第三个人的年龄），你只负责把原文已经明确写出的这
  一处信息结构化，跨人物的年龄换算交给后续步骤处理。

可能的情况（type 字段必须是以下之一）：
1. "absolute" —— 这句话明确说某个具体人物在【当前叙事时刻】是几岁。判断
   依据：这个年龄能不能代表"故事讲到这里的此刻"，这个人此时还活着、正在
   这个时间点上。
2. "milestone_age" —— 这个年龄描述的是某人一生中某个特定阶段/事件发生时
   的年龄（比如"十四岁进学""不到二十岁娶妻生子""及笄""病故"），这类
   句子往往是在倒叙介绍一个人的生平履历，句子里常出现"进学""及笄""出阁"
   "娶妻""生子""病故""下世"这类词。【重要】：同一个人的生平如果一句话
   里连续出现好几个不同的年龄（比如"十四岁进学，不到二十岁就娶了妻生了
   子"），这些全部都是 milestone_age，不是互相矛盾的"当前年龄"——他们是
   同一个人生命线上先后发生的不同阶段，你需要对每个年龄分别输出一条判断
   （如果本次只问你其中一处，就只答这一处，不要把其他阶段的年龄也算进来）。
3. "past_relative" —— 这个年龄描述的是过去某个时间点（比如"去岁死了"），
   不是当前叙事时刻的年龄，也不是完整的人生履历介绍（区别于 milestone_age：
   past_relative 通常只提到一个时间点，milestone_age 往往是连续介绍好几个
   人生阶段）。
4. "comparative" —— 这是两个人之间的年龄差（"比XX大/小N岁"）。
5. "elapsed_years" —— 这是一个时间跨度（"过了N年"），不直接是某人的年龄。
6. "unclear" —— 通读整段文字后仍无法确定，比如代词指代不明。

返回严格的 JSON，不要任何解释文字：
{
  "type": "...",
  "subject": "这处年龄信息归属的人物，优先使用候选人物名单里的具体名字",
  "target_for_comparison": "如果是comparative，另一个人的称呼；否则为空字符串",
  "value": 数字（年龄，或年龄差，或跨度年数）,
  "reasoning_note": "一句话说明你为什么这样判断，不超过20字"
}
"""


def call_ollama_json(prompt_text: str, model_name: str = DEFAULT_MODEL_NAME) -> dict:
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "system": CORRECTION_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.0,   # 这是结构化判断任务，不需要创造性，温度压到最低更稳定
            "num_predict": 200,   # 输出很小，不需要给太多预算
            "num_ctx": 1024,      # 输入也很短，不需要大上下文
        },
    }
    response = requests.post(DEFAULT_OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    res_json = response.json()
    raw = res_json.get("response", "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    eval_count = res_json.get("eval_count")
    eval_duration_ns = res_json.get("eval_duration")
    if eval_count and eval_duration_ns:
        print(f"      ⏱ {eval_count} token / {eval_duration_ns/1e9:.1f}s")
    return json.loads(raw)


def resolve_one(full_narrative: str, matched_sentence: str, extra_context: str,
                 all_candidates_in_segment: list, model_name: str) -> dict:
    highlighted = full_narrative.replace(
        matched_sentence, f"【{matched_sentence}】", 1
    ) if matched_sentence in full_narrative else full_narrative

    prompt = (
        f"整段原文（已用【】标出目标句）：\n{highlighted}\n\n"
        f"目标句中已标注信息：{extra_context}\n\n"
        f"这段原文里出现过的候选人物名单：{all_candidates_in_segment or '（本段未识别出明确人名）'}\n\n"
        f"请判断这处年龄信息的类型和归属。"
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_ollama_json(prompt, model_name=model_name)
            if isinstance(result, dict) and "type" in result:
                return result
        except Exception as e:
            print(f"      ⚠️ [尝试 {attempt}/{MAX_RETRIES}] 失败: {e}")
            time.sleep(1)
    return {"type": "unclear", "subject": "", "target_for_comparison": "", "value": None,
            "reasoning_note": "模型调用失败或格式错误，降级为unclear"}


def run(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE,
        narrative_source_file: str = NARRATIVE_SOURCE_FILE, model_name: str = DEFAULT_MODEL_NAME):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}，请先跑 00_prescan_anchors.py")
        return
    if not os.path.exists(narrative_source_file):
        print(f"❌ 找不到 {narrative_source_file}，需要它来获取每个 segment 的完整原文")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        scan_results = json.load(f)
    with open(narrative_source_file, "r", encoding="utf-8") as f:
        segments_raw = json.load(f)
    narrative_by_id = {s.get("segment_id"): (s.get("narrative", "") or s.get("text", "")) for s in segments_raw}

    resolved = []
    total_items = sum(
        len([a for a in seg["age_candidates"] if a.get("needs_llm_review")]) + len(seg["relation_candidates"])
        for seg in scan_results
    )
    print(f"🚀 共 {total_items} 处需要模型判断的候选\n" + "-" * 50)

    done = 0
    for seg in scan_results:
        seg_id = seg["segment_id"]
        full_narrative = narrative_by_id.get(seg_id, "")
        # 汇总本段所有已识别出的候选人物，供模型在归属判断时优先选用
        all_candidates_in_segment = sorted({
            c for a in seg["age_candidates"] for c in a.get("candidate_characters", [])
        } | {
            c for rc in seg["relation_candidates"] for c in rc.get("candidate_characters_in_sentence", [])
        })

        # 1. 需要复核的 age_candidates
        for a in seg["age_candidates"]:
            if not a.get("needs_llm_review"):
                continue
            done += 1
            print(f"[{done}/{total_items}] seg {seg_id}: {a['sentence'][:30]}...")
            extra = (f"正则识别出年龄「{a['stated_age']}岁」（精确度：{a.get('bound_type', 'exact')}），"
                     f"同句内候选归属人物：{a['candidate_characters'] or '未找到'}，"
                     f"{'检测到过去时间参照词；' if a['past_time_marker_detected'] else ''}"
                     f"{'检测到人生履历关键词（进学/及笄/娶妻/病故等）；' if a.get('milestone_keyword_detected') else ''}")
            result = resolve_one(full_narrative, a["sentence"], extra, all_candidates_in_segment, model_name)
            resolved.append({
                "segment_id": seg_id,
                "chapter": seg["chapter"],
                "source": "age_candidate",
                "sentence": a["sentence"],
                "regex_raw": a,
                "llm_resolution": result,
            })

        # 2. 所有 relation_candidates
        for rc in seg["relation_candidates"]:
            done += 1
            print(f"[{done}/{total_items}] seg {seg_id}: {rc['sentence'][:30]}...")
            if rc["type"] == "comparative":
                extra = (f"正则识别出比较级「{rc['matched_text']}」，比较对象原文写法："
                         f"「{rc['raw_target_phrase']}」，方向：{rc['direction']}，"
                         f"差值：{rc['age_diff']}，同句候选人物：{rc['candidate_characters_in_sentence']}")
            else:
                extra = (f"正则识别出时间跨度「{rc['matched_text']}」，"
                         f"跨度年数：{rc['elapsed_years']}，同句候选人物：{rc['candidate_characters_in_sentence']}")
            result = resolve_one(full_narrative, rc["sentence"], extra, all_candidates_in_segment, model_name)
            resolved.append({
                "segment_id": seg_id,
                "chapter": seg["chapter"],
                "source": rc["type"],
                "sentence": rc["sentence"],
                "regex_raw": rc,
                "llm_resolution": result,
            })

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(resolved, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成，共处理 {len(resolved)} 处 -> {output_file}")
    return resolved


if __name__ == "__main__":
    run()
