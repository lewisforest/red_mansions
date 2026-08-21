# -*- coding: utf-8 -*-
"""
02_pipeline.py
稳健型 Ollama 抽取脚本：只做"这段话里明确提到了什么"的原位抽取，不注入任何
全局背景知识、不要求推理过程——这是保证速度和降低幻觉的核心设计。

在你原来的版本基础上做的补丁：
- zhi_evidence 直接从 01 的输出透传到这里的记录里（不送进 LLM，纯粹是数据搬运），
  后面 03/04/05 步骤如果要引用脂批原文作为佐证，数据不会丢。
"""
import re
import json
import time
import requests
import os

OLLAMA_URL = "http://localhost:11434/api/generate"

PROMPT_TEMPLATE = """你是一个严谨的文本实体抽取助手。请阅读下方段落，仅抽取【明确提及】的信息，不要进行任何推论，不要引入未出场角色。

【待分析段落】：
章节：{chapter}
正文：{narrative}

【抽取要求】：
1. characters_present: 文中【直接出场或被提及】的人物姓名列表。
2. age_mentions: 提及的人物年龄，无则填 []。例：[{"character": "英莲", "age_str": "三岁", "age_num": 3}]
3. time_markers: 出现的具体时间/节令/跨度原词（如："元宵佳节"、"三岁"、"次日"），无则填 []。
4. core_events: 本段发生的核心动作/事件简述（1-2句话）。

【注意事项】：
- 仅输出标准 JSON，无 markdown 标记。
- 字符串值内部【严禁使用英文双引号 "】，如需引用请使用中文单引号 ‘’。

【输出格式】：
{
  "characters_present": ["人名1", "人名2"],
  "age_mentions": [],
  "time_markers": [],
  "core_events": ["核心事件简述"]
}
"""


def _clean_and_parse_json(raw: str) -> dict:
    """清理并容错解析 LLM 输出的 JSON"""
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE | re.IGNORECASE)
    raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)

    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    elif start != -1:
        raw = raw[start:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fixed_raw = raw.strip()
    if not fixed_raw.endswith('}'):
        if not fixed_raw.endswith('"') and not fixed_raw.endswith(']'):
            fixed_raw += '"'
        if fixed_raw.count('[') > fixed_raw.count(']'):
            fixed_raw += ']'
        if fixed_raw.count('{') > fixed_raw.count('}'):
            fixed_raw += '}'

    try:
        return json.loads(fixed_raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 修复失败: {str(e)} | 原输出前100字: {raw[:100]}")


def _call_ollama_with_retry(payload, session, max_retries=3, timeout=180):
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            raw_res = resp.json().get("response", "")
            parsed = _clean_and_parse_json(raw_res)
            return parsed, None
        except Exception as e:
            if attempt == max_retries:
                return None, str(e)
            time.sleep(2)


def run_pipeline(input_file="./processed_data/01_cleaned_segments.json",
                  output_file="./processed_data/02_llm_extractions.json",
                  model_name="gemma3:12b"):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    results = []
    processed_ids = set()

    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                old_results = json.load(f)
                for r in old_results:
                    if "segment_id" in r and "error" not in r:
                        results.append(r)
                        processed_ids.add(r["segment_id"])
            print(f"🔄 读取断点：已跳过 {len(processed_ids)} 条成功记录。")
        except Exception:
            results = []
            processed_ids = set()

    todo_segments = [s for s in segments if s["segment_id"] not in processed_ids]
    total_todo = len(todo_segments)

    if total_todo == 0:
        print("✅ 所有段落均已成功抽取！")
        return

    print(f"🚀 开始抽取 | 待处理: {total_todo} 条 / 总共: {len(segments)} 条")

    session = requests.Session()

    for idx, item in enumerate(todo_segments, 1):
        seg_id = item["segment_id"]
        chapter = item["chapter"]
        narrative = item["narrative"]
        zhi_evidence = item.get("zhi_evidence", [])

        # 过滤纯回目标题（内容极短且像标题，直接落记录不调模型，省一次请求）
        if len(narrative) < 30 and ("回" in narrative and "第" in narrative):
            record = {
                "segment_id": seg_id,
                "chapter": chapter,
                "narrative": narrative,
                "zhi_evidence": zhi_evidence,
                "characters_present": [],
                "age_mentions": [],
                "time_markers": [],
                "core_events": [narrative],
            }
            results.append(record)
            continue

        prompt = PROMPT_TEMPLATE.replace("{chapter}", str(chapter)).replace("{narrative}", str(narrative))

        payload = {
            "model": model_name,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": "1h",
            "options": {
                "temperature": 0.0,
                "num_ctx": 2048,
                "num_predict": 512,
            },
        }

        req_start = time.time()
        print(f"[{idx}/{total_todo}] 正在抽取 ID:{seg_id} ...", end="", flush=True)

        parsed, err_msg = _call_ollama_with_retry(payload, session, max_retries=3, timeout=180)

        if parsed:
            record = {
                "segment_id": seg_id,
                "chapter": chapter,
                "narrative": narrative,
                "zhi_evidence": zhi_evidence,
                "characters_present": parsed.get("characters_present", []),
                "age_mentions": parsed.get("age_mentions", []),
                "time_markers": parsed.get("time_markers", []),
                "core_events": parsed.get("core_events", []),
            }
            cost = time.time() - req_start
            print(f" ✅ 成功 ({cost:.1f}s)")
        else:
            record = {
                "segment_id": seg_id,
                "chapter": chapter,
                "narrative": narrative,
                "zhi_evidence": zhi_evidence,
                "error": err_msg,
                "characters_present": [],
                "age_mentions": [],
                "time_markers": [],
                "core_events": [],
            }
            print(f" ❌ 失败: {err_msg}")

        results.append(record)

        if idx % 5 == 0 or idx == total_todo:
            results.sort(key=lambda x: x.get("segment_id", 0))
            tmp_path = output_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, output_file)

    print(f"\n🎉 抽取完成！结果已存至 {output_file}")


if __name__ == "__main__":
    run_pipeline()
