# -*- coding: utf-8 -*-
"""
11_kinship_llm_correction.py
-------------------------------
和 06 是同一套方法论：10 的正则只负责标出"这里像是在说亲属关系"，具体
"谁是谁的什么人"交给模型做窄口径判断——每次只看一句话（+完整原文做上下
文），输出几个字段的小JSON，不是自由列举。

用法：
    python 11_kinship_llm_correction.py
"""

import json
import os
import re
import time
import requests

from character_alias import clean_character_name

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:12b"
INPUT_FILE = "./processed_data/10_kinship_candidates.json"
NARRATIVE_SOURCE_FILE = "./processed_data/01_cleaned_segments.json"
OUTPUT_FILE = "./processed_data/11_kinship_resolved.json"
TIMEOUT_SECONDS = 300
MAX_RETRIES = 2

KINSHIP_SYSTEM_PROMPT = """你是精确的中文古典文本亲属关系核对助手。你会收到一整段
原文，以及其中一处被正则标出的、疑似描述亲属关系的句子。你的任务是判断这句话
具体说的是谁和谁是什么关系，绝不能引入原文之外的猜测。

关系类型（relation 字段必须是以下之一）：
"父女", "父子", "母女", "母子", "夫妻", "姐弟", "兄妹", "姐妹", "兄弟", "祖孙", "unclear"

【重要】"父/母"表示上一辈的性别，"女/子"表示下一辈的性别，务必对应正确：
- 如果 person_a 是"父"或"母"这一方，一定要根据 person_a 实际的性别选对"父"还是"母"，
  不要因为看到"公子""儿子"这类词就不假思索地选"父子"——生育、抚养这个动作的主语
  是谁，就看那个人本身的性别，而不是看孩子的性别。
- 女性人物的关系里不应该出现"父""夫"这种指代男性的字，出现了大概率是判断错误，
  请重新检查这段原文里 person_a 到底是谁。
如果原文没有明确写出足够信息来确定具体是谁，必须选 unclear，不要猜。

返回严格 JSON：
{
  "relation": "...",
  "person_a": "关系中的一方，原文里的具体人名",
  "person_b": "关系中的另一方，原文里的具体人名",
  "reasoning_note": "一句话说明依据，不超过20字"
}
"""

# 极简性别启发式——只用于事后校验，不用于判断，出现矛盾只报警不擅自纠正
# （和年龄冲突检测同一个设计原则：发现问题就标出来，不要用一个不完全可靠的
# 规则去覆盖模型的判断，避免制造新的错误）。
FEMALE_SUFFIX_HINTS = ["氏", "夫人", "姑娘", "姐", "妹", "娘", "婆", "太太", "奶奶", "小姐"]
MALE_SUFFIX_HINTS = ["公子", "老爷", "相公", "哥", "郎", "伯", "爷"]


def _guess_gender(name: str):
    """极粗略的性别猜测，仅用于事后校验矛盾，不作为权威判断"""
    for kw in FEMALE_SUFFIX_HINTS:
        if kw in name:
            return "female"
    for kw in MALE_SUFFIX_HINTS:
        if kw in name:
            return "male"
    return None


def _check_gender_consistency(relation: str, person_a: str, person_b: str) -> str:
    """检查关系标签隐含的性别和称谓后缀是否矛盾，返回警告文字（没有矛盾则返回空字符串）"""
    gender_a = _guess_gender(person_a)
    gender_b = _guess_gender(person_b)

    elder_gender_map = {"父女": "male", "父子": "male", "母女": "female", "母子": "female"}
    if relation in elder_gender_map and gender_a and gender_a != elder_gender_map[relation]:
        return f"⚠️ 关系'{relation}'要求person_a是{elder_gender_map[relation]}，但'{person_a}'称谓后缀显示是{gender_a}，可能判断错误"
    return ""


def call_ollama_json(prompt_text: str, model_name: str = DEFAULT_MODEL_NAME) -> dict:
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "system": KINSHIP_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 200, "num_ctx": 2048},
    }
    resp = requests.post(DEFAULT_OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    if resp.status_code >= 500:
        # 500往往是Ollama自身崩溃/内存不足重启，把响应体打出来方便诊断，
        # 而不是只报个"500 Server Error"看不出原因
        print(f"      🔍 Ollama返回体：{resp.text[:300]}")
    resp.raise_for_status()
    res_json = resp.json()
    raw = res_json.get("response", "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def resolve_one(full_narrative: str, sentence: str, pattern_desc: str, candidates: list, model_name: str) -> dict:
    highlighted = full_narrative.replace(sentence, f"【{sentence}】", 1) if sentence in full_narrative else full_narrative
    prompt = (
        f"整段原文（已用【】标出目标句）：\n{highlighted}\n\n"
        f"正则识别出的模式：{pattern_desc}\n"
        f"这段原文里出现过的候选人物：{candidates or '（未识别出明确人名）'}\n\n"
        f"请判断这句话具体描述的是谁和谁的什么关系。"
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_ollama_json(prompt, model_name=model_name)
            if isinstance(result, dict) and "relation" in result:
                return result
        except Exception as e:
            print(f"      ⚠️ [尝试 {attempt}/{MAX_RETRIES}] 失败: {e}")
            time.sleep(5)  # 500往往是模型服务端瞬时不稳定/资源紧张，给更长恢复时间再重试
    return {"relation": "unclear", "person_a": "", "person_b": "", "reasoning_note": "模型调用失败"}


def run(model_name: str = DEFAULT_MODEL_NAME):
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 找不到 {INPUT_FILE}，请先跑 10_kinship_prescan.py")
        return
    if not os.path.exists(NARRATIVE_SOURCE_FILE):
        print(f"❌ 找不到 {NARRATIVE_SOURCE_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        scan_results = json.load(f)
    with open(NARRATIVE_SOURCE_FILE, "r", encoding="utf-8") as f:
        segments_raw = json.load(f)
    narrative_by_id = {s.get("segment_id"): (s.get("narrative", "") or s.get("text", "")) for s in segments_raw}

    resolved = []
    total = sum(len(seg["kinship_candidates"]) for seg in scan_results)
    print(f"🚀 共 {total} 处亲属关系候选\n" + "-" * 50)

    done = 0
    for seg in scan_results:
        seg_id = seg["segment_id"]
        full_narrative = narrative_by_id.get(seg_id, "")
        for kc in seg["kinship_candidates"]:
            done += 1
            print(f"[{done}/{total}] seg {seg_id}: {kc['sentence'][:30]}...")
            result = resolve_one(full_narrative, kc["sentence"], kc["pattern_desc"],
                                  kc["candidate_characters_in_sentence"], model_name)
            gender_warning = _check_gender_consistency(
                result.get("relation", ""), result.get("person_a", ""), result.get("person_b", "")
            )
            if gender_warning:
                print(f"      {gender_warning}")
            resolved.append({
                "segment_id": seg_id,
                "chapter": seg["chapter"],
                "sentence": kc["sentence"],
                "resolution": result,
                "gender_consistency_warning": gender_warning,
            })

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(resolved, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成，共处理 {len(resolved)} 处 -> {OUTPUT_FILE}")
    return resolved


if __name__ == "__main__":
    run()
