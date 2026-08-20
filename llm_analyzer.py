# -*- coding: utf-8 -*-
"""
llm_analyzer.py
封装本地 Ollama 模型调用，提取时间线索、家族世系、人物年龄，以及人物关系网络/
交叉锚点事件。

本版新增（人物关系网络化，进一步提速）：
1. Prompt 里注入 network_graph.py 中的锚点参照系，要求模型额外输出
   characters_present（出场人物）和 relational_events（人物关系事件，
   附带 network_anchor 字段用于匹配锚点）。
2. 明确告诉模型：命中锚点时 reasoning_logic 只需简短说明匹配依据，不需要
   展开三步检查——这能显著缩短命中锚点段落的输出长度，直接提速。
   （没命中锚点的段落，仍然走之前"三步检查"的完整相对时间推理，保证准确性
   不因为省 token 而下降。）
"""

import re
import json
import time
import requests

from network_graph import RedMansionTimelineGraph

OLLAMA_URL = "http://localhost:11434/api/generate"
_session = requests.Session()
_graph = RedMansionTimelineGraph()
_NETWORK_CONTEXT = _graph.build_prompt_context()

PROMPT_TEMPLATE = """你是一个精通《红楼梦》文本考据、脂砚斋批注与人物关系网络的文史专家。

""" + _NETWORK_CONTEXT + """

【分析任务】：
请仔细阅读下方正文与脂批，完成两件事：

一、人物关系网络匹配（优先做这个，做得好可以让你少写很多推理文字）：
   识别文中出现的人物，以及人物之间发生的关系性事件（如生卒、婚嫁、探病、
   离别、书信往来等）。如果某个事件明显对应上面参照系里的某一条（哪怕措辞
   不同，只要事件本质一致，比如"黛玉之母去世"对应 DAIYU_MOTHER_DEATH），
   就把对应的 key 填入该事件的 network_anchor 字段。
   —— 如果成功命中锚点：reasoning_logic 只需要一两句话说明你是根据什么
      判断命中的即可，不需要再做下面的三步检查，直接按锚点年份给
      year_transition 相关字段定调。
   —— 如果没有命中任何锚点：才需要按以下三步走完整推理：
      1. 本段是否包含"十载""数年""转眼""次年""越明年""年方X岁……又X岁"
         等跨度/年龄对比词？填入 time_markers_found。
      2. 本段是否属于楔子、凡例、创作背景交代、家族前史等元叙事？
      3. 据此判定 year_transition：找到跨年词严禁判 SAME_YEAR，必须判
         YEARS_LATER 并给出 estimated_year_gap；属于元叙事判
         META_BACKGROUND；只有恰好跨一年才判 NEXT_YEAR；其余顺叙才判
         SAME_YEAR。

二、常规信息提取：显式时间/节令、家族世系与爵位继承背景、人物相对年龄、
    正文情节、脂批印证。

【输入数据】：
章节：{chapter}
正文内容：
{narrative}

脂批印证：
{zhi_text}

【输出格式】（仅输出合法的 JSON 对象，不要输出 Markdown 标记）：
{{
  "chapter": "{chapter}",
  "characters_present": ["文中出场或被提及的人物"],
  "relational_events": [
    {{
      "subject": "主体人物",
      "target": "关联人物",
      "relation": "关系（如：母女/主仆/夫妻）",
      "event": "具体事件",
      "subject_age": "主体人物当时年龄，不确定填 null",
      "network_anchor": "命中的锚点 key，没命中填 null"
    }}
  ],
  "season_or_festival": "显式节令/时间说明，没有则填 null",
  "time_markers_found": ["文中出现的时间/年龄/跨度指示词原文，没有则填空数组"],
  "is_meta_narrative": false,
  "year_transition": "SAME_YEAR / NEXT_YEAR / YEARS_LATER / META_BACKGROUND",
  "estimated_year_gap": 0,
  "background_and_lineage": ["世系继承/家族背景/人物年龄对比细节"],
  "narrative_events": ["详细情节事件（含生卒、官职升迁、迁徙等）"],
  "zhi_corroborations": ["脂批说明"],
  "reasoning_logic": "命中锚点则简短说明匹配依据；未命中则按三步检查依次说明"
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


def _normalize_relational_events(raw_events) -> list:
    if not isinstance(raw_events, list):
        return []
    cleaned = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        cleaned.append({
            "subject": ev.get("subject") or "",
            "target": ev.get("target") or "",
            "relation": ev.get("relation") or "",
            "event": ev.get("event") or "",
            "subject_age": ev.get("subject_age"),
            "network_anchor": ev.get("network_anchor"),
        })
    return cleaned


def _normalize_response(parsed: dict, chapter: str) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    parsed.setdefault("chapter", chapter)
    parsed.setdefault("characters_present", [])
    parsed["relational_events"] = _normalize_relational_events(parsed.get("relational_events"))
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

    for key in ["characters_present", "time_markers_found", "background_and_lineage",
                "narrative_events", "zhi_corroborations"]:
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

            done_reason = body.get("done_reason")
            if done_reason == "length":
                print(f"    ⚠️ [{chapter}] 触发 num_predict 截断（耗时 {request_elapsed:.1f}s），"
                      f"模型疑似在生成中重复/卡壳，而非正常收尾。")

            clean_raw = _clean_json_raw(raw_res)
            parsed = json.loads(clean_raw)
            normalized = _normalize_response(parsed, chapter)
            # 用人物关系网络锚点做校准（命中锚点会写入 matched_anchor 等字段）
            normalized = _graph.align_segment(normalized)
            return normalized

        except Exception as e:
            last_error = str(e)
            if attempt <= max_retries:
                time.sleep(1.0 * attempt)

    return {
        "chapter": chapter,
        "error": last_error or "未知解析错误",
        "characters_present": [],
        "relational_events": [],
        "season_or_festival": None,
        "time_markers_found": [],
        "is_meta_narrative": False,
        "year_transition": "SAME_YEAR",
        "estimated_year_gap": 0,
        "background_and_lineage": [],
        "narrative_events": [],
        "zhi_corroborations": zhi_evidence,
        "reasoning_logic": f"推理失败: {last_error}",
        "matched_anchor": None,
        "calculated_global_year_offset": None,
        "matched_anchor_desc": None,
    }


def force_unload_model(model_name: str, url: str = OLLAMA_URL, timeout: int = 30):
    """立即卸载模型（keep_alive=0），下一次调用会重新加载，缓解长时间连续推理导致的降速。"""
    try:
        _session.post(url, json={"model": model_name, "prompt": "", "keep_alive": 0}, timeout=timeout)
        return True
    except Exception as e:
        print(f"  ⚠️ 强制卸载模型失败（不影响继续运行）: {e}")
        return False
