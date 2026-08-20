# -*- coding: utf-8 -*-
"""
llm_analyzer.py
封装本地 Ollama 模型调用，提取时间线索、家族世系、人物年龄等信息。

在原逻辑基础上加的速度优化：
1. keep_alive：Ollama 默认 5 分钟无请求就把模型从显存卸载，下次请求要重新加载
   （几秒到几十秒不等）。并发/重试场景下很容易触发反复加载，是最容易被忽视的
   拖慢点。这里设置 30 分钟，保证整个批处理过程中模型常驻内存。
2. num_predict：给输出长度设一个上限，防止模型偶尔"话痨"生成远超需要的内容，
   拖慢单次请求（我们要的只是一个不大的 JSON，不需要无限生成）。
3. num_ctx 显式设置，配合更大的分段（800~1500字），避免上下文被截断。
"""

import re
import json
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
_session = requests.Session()

PROMPT_TEMPLATE = """你是一个精通《红楼梦》文本考据与脂砚斋批注的文史专家。

【分析任务】：
请仔细阅读下方正文与脂批，**深度提取**其中所有时间线索，特别注意：
1. 显式时间/节令（如：元宵、三月十五、去岁、今岁、到任方一月有余）。
2. **家族世系与爵位继承背景**（如：林家五世世袭与科举出身、贾府代字辈世系、遗本赐官等）。
3. **人物相对年龄与生卒婚嫁**（如：黛玉5岁、贾蓉16岁、贾珠14岁进学不到20岁卒、贾敏仙逝等）。
4. 判定本段相比上文是否发生年份跨越（如"次年""去岁""又是一年"）：
   - 若跨入下一年/次年，year_transition 填 "NEXT_YEAR"
   - 若属于同年内发生的情节，year_transition 填 "SAME_YEAR"

【输入数据】：
章节：{chapter}
正文内容：
{narrative}

脂批印证：
{zhi_text}

【输出格式】（仅输出合法的 JSON 对象，不要输出 Markdown 标记）：
{{
  "chapter": "{chapter}",
  "season_or_festival": "显式节令/时间说明",
  "year_transition": "SAME_YEAR 或 NEXT_YEAR",
  "background_and_lineage": ["世系继承/家族背景/人物年龄对比细节1", "细节2"],
  "narrative_events": ["详细情节事件（含生卒、官职升迁、迁徙等）"],
  "zhi_corroborations": ["脂批说明"],
  "reasoning_logic": "结合世系、年龄与时间词的推导逻辑"
}}
"""


def _clean_json_raw(raw: str) -> str:
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE | re.IGNORECASE)
    raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1:
        return raw[start:end + 1]
    return raw.strip()


def _normalize_response(parsed: dict, chapter: str) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    parsed.setdefault("chapter", chapter)
    parsed.setdefault("season_or_festival", "未明确提及")
    parsed.setdefault("year_transition", "SAME_YEAR")
    parsed.setdefault("background_and_lineage", [])
    parsed.setdefault("narrative_events", [])
    parsed.setdefault("zhi_corroborations", [])
    parsed.setdefault("reasoning_logic", "")

    for key in ["background_and_lineage", "narrative_events", "zhi_corroborations"]:
        if isinstance(parsed[key], str):
            parsed[key] = [parsed[key]] if parsed[key] else []

    return parsed


def analyze_timeline_segment(
    chapter: str,
    narrative: str,
    zhi_evidence: list,
    model_name: str = "gemma3:12b",
    max_retries: int = 2,
    timeout: int = 180,
    keep_alive: str = "30m",
    num_predict: int = 800,
) -> dict:
    zhi_text = "\n".join(f"- {c}" for c in zhi_evidence) if zhi_evidence else "无"
    prompt = PROMPT_TEMPLATE.format(chapter=chapter, narrative=narrative, zhi_text=zhi_text)

    payload = {
        "model": model_name,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0.0,
            "top_p": 0.3,
            "num_ctx": 8192,
            "num_predict": num_predict,
        },
    }

    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            response = _session.post(OLLAMA_URL, json=payload, timeout=timeout)
            response.raise_for_status()
            raw_res = response.json().get("response", "")

            clean_raw = _clean_json_raw(raw_res)
            parsed = json.loads(clean_raw)
            return _normalize_response(parsed, chapter)

        except Exception as e:
            last_error = str(e)
            if attempt <= max_retries:
                time.sleep(1.0 * attempt)

    return {
        "chapter": chapter,
        "error": last_error or "未知解析错误",
        "season_or_festival": "未明确提及",
        "year_transition": "SAME_YEAR",
        "background_and_lineage": [],
        "narrative_events": [],
        "zhi_corroborations": zhi_evidence,
        "reasoning_logic": f"推理失败: {last_error}",
    }
