# -*- coding: utf-8 -*-
"""
02_pipeline.py
稳健型 Ollama 抽取脚本（解决 Token 截断与 JSON 语法错误）

在你原来版本基础上的微调：
1. 超时从 180s 降到 60s：既然这一步的目标就是"2~5秒完成的纯抽取"，如果单次
   请求真的卡到 60s 还没回来，大概率是模型在生成中卡壳/死循环了，与其死等
   180s×3次重试（最坏情况单条能拖到9分钟），不如更快失败、更快重试。
2. zhi_evidence（脂批）直接从清洗阶段的结果透传到输出，不占用模型 token
   （脂批本身通常已经是明确的文字，不需要模型再"提取"一遍）。
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


def _normalize_and_parse_json(raw: str) -> dict:
    """
    清理并容错解析 LLM 输出的 JSON，分层尝试：
    1. 直接解析
    2. 全角标点归一化（，－>, ：－>:）—— 这一步是安全的，因为 JSON 本身不关心
       字符串【内容】里用什么标点，只关心【结构分隔符】必须是半角。模型在长
       列表里偶尔会把元素之间的逗号打成全角，这一步专门修这个。
    3. 两个引号直接相邻但中间漏了逗号（常见于很长的人物名单，模型数着数着
       漏打一个逗号）
    4. 截断兜底：结尾没闭合的括号/引号，尝试补全
    """
    text = raw
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end + 1]
    elif start != -1:
        text = text[start:]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    normalized = text.replace('，', ',').replace('：', ':')
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass

    comma_fixed = re.sub(r'"\s*\n?\s*"', '", "', normalized)
    try:
        return json.loads(comma_fixed)
    except json.JSONDecodeError:
        pass

    fixed_raw = comma_fixed.strip()
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
        raise ValueError(f"JSON 修复失败: {str(e)} | 原始长度 {len(raw)} 字 | 前200字: {raw[:200]}")


def _call_ollama_with_retry(base_payload, session, max_retries=3, base_timeout=60,
                             debug_log_path=None, seg_id=None):
    """
    重试时会逐步放宽资源，而不是原样重复请求：
    - num_predict 每次重试 +300（上限 1500）：应对"人物列表太长被截断"
    - temperature 每次重试 +0.2：温度为 0 时同一输入会生成完全相同的（有问题
      的）输出，重试without改变任何参数等于白跑；给一点随机性才有机会跳出
      同样的截断/漏逗号模式
    - timeout 每次重试 +30s：给生成更多内容留出时间
    最终仍然失败会把原始响应写入 debug_log_path，方便事后排查而不用重新触发。
    """
    last_raw = None
    last_err = None
    for attempt in range(1, max_retries + 1):
        payload = json.loads(json.dumps(base_payload))  # 深拷贝，避免多次尝试互相污染
        options = payload["options"]
        if attempt > 1:
            options["num_predict"] = min(options.get("num_predict", 512) + 300 * (attempt - 1), 1500)
            options["temperature"] = round(0.2 * (attempt - 1), 2)
        timeout = base_timeout + 30 * (attempt - 1)

        try:
            resp = session.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            raw_res = resp.json().get("response", "")
            last_raw = raw_res
            parsed = _normalize_and_parse_json(raw_res)
            return parsed, None
        except Exception as e:
            last_err = str(e)
            if attempt == max_retries:
                if debug_log_path and seg_id is not None:
                    try:
                        with open(debug_log_path, "a", encoding="utf-8") as logf:
                            logf.write(json.dumps(
                                {"segment_id": seg_id, "error": last_err, "raw_response": last_raw},
                                ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                return None, last_err
            time.sleep(2)
    return None, last_err


def run_pipeline(input_file="./processed_data/01_cleaned_segments.json",
                  output_file="./processed_data/02_llm_extractions.json",
                  model_name="gemma3:12b",
                  timeout=60,
                  max_retries=3):
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        segments = json.load(f)

    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)

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
    start_time = time.time()

    for idx, item in enumerate(todo_segments, 1):
        seg_id = item["segment_id"]
        chapter = item["chapter"]
        narrative = item["narrative"]
        zhi_evidence = item.get("zhi_evidence", [])

        # 过滤纯回目标题
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

        parsed, err_msg = _call_ollama_with_retry(payload, session, max_retries=max_retries, timeout=timeout)

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
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            elapsed = time.time() - start_time
            avg = elapsed / idx
            eta_min = (total_todo - idx) * avg / 60
            print(f"    💾 已保存 | 平均 {avg:.1f}s/条 | 预计剩余 {eta_min:.1f} 分钟")

    print(f"\n🎉 抽取完成！结果已存至 {output_file}")


if __name__ == "__main__":
    run_pipeline()
