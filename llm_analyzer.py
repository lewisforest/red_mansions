# -*- coding: utf-8 -*-
"""
llm_analyzer.py
封装本地 Ollama 模型调用，提取时间线索、家族世系、人物年龄等信息。

本版改动（针对"越跑越慢" + "年份推理错误"两个问题）：

【年份推理错误】
把 year_transition 从二元的 SAME_YEAR/NEXT_YEAR 扩展为四态，并强制模型在给出结论前
先列出文中出现的时间/跨度指示词、判断是否属于楔子/家族前史等元叙事，避免"没有显式
'次年'字样就默认算同一年"这种粗暴归类，导致"披阅十载""英莲三岁...五岁"这类跨度被
错误地打成 SAME_YEAR。

【越跑越慢】
1. /api/generate 本身是无状态调用，我们从不回传上一次的 context 字段，所以不存在
   "历史对话像滚雪球一样累积进 attention 计算"的问题——这点可以排除。
2. 加了 repeat_penalty，降低模型在 JSON 生成中"卡壳重复"直到撞满 num_predict 上限
   的概率（这种卡壳本身就是单条请求变慢的直接原因）。
3. 把 Ollama 返回的 done_reason 记录下来：如果频繁是 "length"（即被 num_predict
   截断，而不是模型自然生成结束），说明大概率是在重复输出，可以在日志里直接看到。
4. 提供 force_unload_model()，配合 pipeline 里的定期重置逻辑，定期把模型从显存/内存
   强制卸载再重新加载，避免长时间连续推理导致的显存碎片化或潜在内存泄漏累积。
"""

import re
import json
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
_session = requests.Session()

PROMPT_TEMPLATE = """你是一个精通《红楼梦》文本考据与脂砚斋批注的文史专家。

【分析任务】：
请仔细阅读下方正文与脂批，深度提取其中所有时间线索。

在得出结论前，你必须在 reasoning_logic 中依次完成以下三步检查（这是强制步骤，不能跳过）：
1. 本段文本是否包含"十载""数年""转眼""次年""越明年""年方X岁……又X岁"等跨度/年龄
   对比词？把找到的原词填入 time_markers_found（没有则填空数组）。
2. 本段是否属于楔子、凡例、创作背景交代、家族前史（如"林家五世""贾府始祖""遗本赐官"）
   等元叙事内容，而不是某个具体年份里发生的单一情节？
3. 根据以上两步得出 year_transition：
   - 如果第 1 步找到了跨越多年的词（如"十载""数年""转眼""英莲三岁……后来五岁"），
     严禁判定为 SAME_YEAR，必须判定为 YEARS_LATER，并在 estimated_year_gap 中给出
     你估计的跨越年数（如"十载"填 10，"数年"填 3~5 之间你认为合理的数字，"转眼"
     若无更具体线索可填 2）。
   - 如果第 2 步判断为元叙事背景，判定为 META_BACKGROUND（这类内容不代表某一具体
     年份，不需要填 estimated_year_gap）。
   - 只有当本段确实发生在与上文相邻的同一年内（日、月更替，或无跨年标记的顺叙），
     才能判定为 SAME_YEAR。
   - 只有明确出现"次年""越明年""次冬"等恰好跨一年的词，才判定为 NEXT_YEAR。

【输入数据】：
章节：{chapter}
正文内容：
{narrative}

脂批印证：
{zhi_text}

【输出格式】（仅输出合法的 JSON 对象，不要输出 Markdown 标记）：
{{
  "chapter": "{chapter}",
  "season_or_festival": "显式节令/时间说明，没有则填 null",
  "time_markers_found": ["文中出现的时间/年龄/跨度指示词原文，没有则填空数组"],
  "is_meta_narrative": false,
  "year_transition": "SAME_YEAR / NEXT_YEAR / YEARS_LATER / META_BACKGROUND",
  "estimated_year_gap": 0,
  "background_and_lineage": ["世系继承/家族背景/人物年龄对比细节"],
  "narrative_events": ["详细情节事件（含生卒、官职升迁、迁徙等）"],
  "zhi_corroborations": ["脂批说明"],
  "reasoning_logic": "先按上面三步依次说明你的判断依据，再给出结论"
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


VALID_TRANSITIONS = {"SAME_YEAR", "NEXT_YEAR", "YEARS_LATER", "META_BACKGROUND"}


def _normalize_response(parsed: dict, chapter: str) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    parsed.setdefault("chapter", chapter)
    parsed.setdefault("season_or_festival", None)
    parsed.setdefault("time_markers_found", [])
    parsed.setdefault("is_meta_narrative", False)
    parsed.setdefault("year_transition", "SAME_YEAR")
    parsed.setdefault("estimated_year_gap", 0)
    parsed.setdefault("background_and_lineage", [])
    parsed.setdefault("narrative_events", [])
    parsed.setdefault("zhi_corroborations", [])
    parsed.setdefault("reasoning_logic", "")

    if parsed["year_transition"] not in VALID_TRANSITIONS:
        parsed["year_transition"] = "SAME_YEAR"

    try:
        parsed["estimated_year_gap"] = int(parsed.get("estimated_year_gap") or 0)
    except (TypeError, ValueError):
        parsed["estimated_year_gap"] = 0

    for key in ["time_markers_found", "background_and_lineage", "narrative_events", "zhi_corroborations"]:
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
    num_ctx: int = 8192,
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
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            # 降低"卡壳重复直到撞满 num_predict"的概率——这种卡壳是单条请求
            # 突然变慢的常见直接原因，而不只是硬件降频。
            "repeat_penalty": 1.15,
            "repeat_last_n": 256,
        },
    }

    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            request_start = time.time()
            response = _session.post(OLLAMA_URL, json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            raw_res = body.get("response", "")
            request_elapsed = time.time() - request_start

            # done_reason == "length" 说明是被 num_predict 截断的，而不是模型自然收尾，
            # 大概率意味着它在 JSON 里卡壳重复了，是"单条变慢"的直接信号。
            done_reason = body.get("done_reason")
            if done_reason == "length":
                print(f"    ⚠️ [{chapter}] 触发 num_predict 截断（耗时 {request_elapsed:.1f}s），"
                      f"模型疑似在生成中重复/卡壳，而非正常收尾。")

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
        "season_or_festival": None,
        "time_markers_found": [],
        "is_meta_narrative": False,
        "year_transition": "SAME_YEAR",
        "estimated_year_gap": 0,
        "background_and_lineage": [],
        "narrative_events": [],
        "zhi_corroborations": zhi_evidence,
        "reasoning_logic": f"推理失败: {last_error}",
    }


def force_unload_model(model_name: str, url: str = OLLAMA_URL, timeout: int = 30):
    """
    立即卸载模型（keep_alive=0），下一次调用会重新加载。
    用于长时间连续推理后定期"清空重来"，缓解可能的显存碎片化/内存累积导致的降速。
    """
    try:
        _session.post(url, json={"model": model_name, "prompt": "", "keep_alive": 0}, timeout=timeout)
        return True
    except Exception as e:
        print(f"  ⚠️ 强制卸载模型失败（不影响继续运行）: {e}")
        return False
