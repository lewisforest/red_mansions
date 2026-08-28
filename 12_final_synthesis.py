# -*- coding: utf-8 -*-
"""
12_final_synthesis.py
------------------------
这是唯一一处允许语言模型"造句子"的地方，但边界非常严格：模型的输入是
已经通过 00~09/10~11 验证过的结构化事实（年龄、年龄差、亲属关系），
它的任务只是把这些已经锁定的数字和关系组织成一段通顺的中文叙述，
Prompt 里明确禁止它引入任何原文之外的新数字或新关系——这和"自由列举
事件"性质完全不同：自由列举是"凭空生成内容"，这里是"复述已验证内容"，
幻觉空间被压缩到接近于零（唯一风险是模型在转述时手滑改错一个数字，
所以最后还做了一次机械校验：生成的文本里出现的数字必须能在输入的
结构化数据里找到）。

姐弟年龄差之类的计算（比如"如海35岁生黛玉，36岁生弟弟，故姐弟相差1岁"）
全部由本脚本用 Python 算好、作为事实喂给模型，模型不做任何计算。

用法：
    python 12_final_synthesis.py
"""

import json
import os
import re
import requests

AGE_TIMELINE_FILE = "./processed_data/09_age_timeline.json"
KINSHIP_FILE = "./processed_data/11_kinship_resolved.json"
OUTPUT_FILE = "./processed_data/12_final_narrative.json"

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:12b"
TIMEOUT_SECONDS = 300

NARRATION_SYSTEM_PROMPT = """你是一个严谨的文本整理助手。你会收到一份关于《红楼梦》
某个人物家族的、已经验证过的结构化事实清单（年龄、年龄差、亲属关系）。

你的唯一任务是把这些事实组织成一段通顺的中文叙述。

【绝对规则】：
1. 只能使用给定清单里出现的数字和关系，一个字都不能改，不能四舍五入，
   不能凭自己的理解替换成别的数字。
2. 不允许添加清单里没有提到的任何新事实、新年龄、新关系。
3. 如果清单里的信息不足以说清楚某件事（比如不知道确切出生年份），就如实
   说"具体年份不详，但……"，不要编造一个听起来合理的数字。
4. 清单里 relation 字段如果写的是"推算的父母子女关系"或"推算的兄弟姐妹关系"，
   这是根据其他已知关系推算出来的，不是原文直接写明的，叙述时必须如实说明
   "由此可推算/推知……"，不能写得像是原文直接说的一样确定。
5. 只输出叙述文字本身，不要输出JSON、不要输出解释。
"""


def call_ollama_text(prompt_text: str, model_name: str = DEFAULT_MODEL_NAME) -> str:
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "system": NARRATION_SYSTEM_PROMPT,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": 2048},
    }
    resp = requests.post(DEFAULT_OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _extract_numbers(text: str):
    return set(re.findall(r"\d+", text))


def _build_relation_graph(confirmed_relations: list):
    """把 父女/父子/母女/母子 统一成有向边 parent_of(parent, child)，
    夫妻统一成无向边 spouse_of，兄弟姐妹统一成无向边 sibling_of。"""
    parent_of = []   # [(parent, child), ...]
    spouse_of = set()  # {frozenset({a,b}), ...}
    sibling_of = set()

    PARENT_RELATIONS = {"父女", "父子", "母女", "母子"}
    for rel in confirmed_relations:
        r, a, b = rel["relation"], rel["person_a"], rel["person_b"]
        if r in PARENT_RELATIONS:
            parent_of.append((a, b))
        elif r == "夫妻":
            spouse_of.add(frozenset({a, b}))
        elif r in ("姐弟", "兄妹", "姐妹", "兄弟"):
            sibling_of.add(frozenset({a, b}))

    return parent_of, spouse_of, sibling_of


def _infer_transitive_relations(parent_of: list, spouse_of: set, sibling_of: set):
    """纯代码传递推理，不经过模型：
    1. 配偶+亲子 -> 推出另一方也是该子女的父母（如海+贾氏夫妻，贾氏是黛玉母亲，
       推出如海是黛玉父亲）
    2. 同一父母的两个子女 -> 推出他们是兄弟姐妹
    每条推论都记录依据，方便你审查。"""
    inferred = []
    parent_set = set(parent_of)
    children_by_parent = {}
    for p, c in parent_of:
        children_by_parent.setdefault(p, set()).add(c)

    # 规则1：配偶 + 亲子 -> 另一方也是该子女的父母
    for p, c in parent_of:
        for pair in spouse_of:
            if p in pair:
                other = next(iter(pair - {p}))
                if (other, c) not in parent_set:
                    inferred.append({
                        "inferred_relation": "parent_of",
                        "parent": other, "child": c,
                        "basis": f"{p}与{other}是夫妻，且{p}是{c}的父母，故推出{other}也是{c}的父母",
                    })
                    parent_set.add((other, c))
                    children_by_parent.setdefault(other, set()).add(c)

    # 规则2：同一父母的两个子女 -> 兄弟姐妹（只报告，具体谁大谁小由年龄数据决定，这里不猜）
    for parent, children in children_by_parent.items():
        children = list(children)
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                pair = frozenset({children[i], children[j]})
                if pair not in sibling_of:
                    inferred.append({
                        "inferred_relation": "siblings",
                        "person_a": children[i], "person_b": children[j],
                        "basis": f"{parent}是{children[i]}和{children[j]}共同的父母，故推出二人是兄弟姐妹",
                    })
                    sibling_of.add(pair)

    return inferred


def build_family_facts(age_data: dict, kinship_data: list) -> dict:
    """把年龄图谱和亲属关系拼成"人物 -> 关系 -> 年龄差"的事实清单，
    这里的年龄差计算全部是Python算术，不经过模型。"""
    anchors = age_data.get("age_anchors_by_character", {})

    same_scene_diffs = {}
    for item in age_data.get("timeline", []):
        stated = item.get("directly_stated", {})
        names = list(stated.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                same_scene_diffs[(a, b)] = stated[a] - stated[b]

    confirmed_relations = [
        r["resolution"] for r in kinship_data
        if r["resolution"].get("relation") not in (None, "unclear")
        and r["resolution"].get("person_a") and r["resolution"].get("person_b")
    ]

    facts_per_pair = []
    for rel in confirmed_relations:
        a, b = rel["person_a"], rel["person_b"]
        diff = same_scene_diffs.get((a, b))
        if diff is None:
            diff = same_scene_diffs.get((b, a))
            if diff is not None:
                diff = -diff
        facts_per_pair.append({
            "person_a": a, "person_b": b, "relation": rel["relation"],
            "age_diff": diff, "source": "directly_extracted",
        })

    # 传递推理：配偶+亲子 -> 另一方父母；同父母子女 -> 兄弟姐妹
    parent_of, spouse_of, sibling_of = _build_relation_graph(confirmed_relations)
    inferred = _infer_transitive_relations(parent_of, spouse_of, sibling_of)
    for inf in inferred:
        if inf["inferred_relation"] == "parent_of":
            a, b = inf["parent"], inf["child"]
            diff = same_scene_diffs.get((a, b)) or (
                -same_scene_diffs[(b, a)] if (b, a) in same_scene_diffs else None
            )
            facts_per_pair.append({
                "person_a": a, "person_b": b, "relation": "推算的父母子女关系",
                "age_diff": diff, "source": "inferred", "basis": inf["basis"],
            })
        else:
            a, b = inf["person_a"], inf["person_b"]
            diff = same_scene_diffs.get((a, b)) or (
                -same_scene_diffs[(b, a)] if (b, a) in same_scene_diffs else None
            )
            facts_per_pair.append({
                "person_a": a, "person_b": b, "relation": "推算的兄弟姐妹关系",
                "age_diff": diff, "source": "inferred", "basis": inf["basis"],
            })

    return {"relations": facts_per_pair, "age_anchors": anchors}


def run(model_name: str = DEFAULT_MODEL_NAME):
    if not os.path.exists(AGE_TIMELINE_FILE) or not os.path.exists(KINSHIP_FILE):
        print("❌ 请先跑完 09_build_age_timeline.py 和 11_kinship_llm_correction.py")
        return

    with open(AGE_TIMELINE_FILE, "r", encoding="utf-8") as f:
        age_data = json.load(f)
    with open(KINSHIP_FILE, "r", encoding="utf-8") as f:
        kinship_data = json.load(f)

    facts = build_family_facts(age_data, kinship_data)
    if not facts["relations"]:
        print("⚠️ 没有找到任何'关系+年龄差都齐全'的组合，无法生成叙述。"
              "可能是10/11抓到的关系还太少，或者和09的年龄锚点没有重叠。")
        return

    facts_text = json.dumps(facts, ensure_ascii=False, indent=2)
    prompt = f"结构化事实：\n{facts_text}\n\n请据此写一段通顺的中文叙述。"

    narrative = call_ollama_text(prompt, model_name=model_name)

    # 机械校验：叙述里出现的数字必须都能在输入事实里找到，防止模型转述时手滑改错
    input_numbers = _extract_numbers(facts_text)
    output_numbers = _extract_numbers(narrative)
    hallucinated_numbers = output_numbers - input_numbers

    result = {
        "input_facts": facts,
        "narrative": narrative,
        "hallucinated_numbers_check": list(hallucinated_numbers),
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("✅ 合成完成\n")
    print("--- 生成的叙述 ---")
    print(narrative)
    if hallucinated_numbers:
        print(f"\n⚠️ 警告：叙述里出现了输入事实里没有的数字 {hallucinated_numbers}，"
              f"这条结果不可信，需要人工核查或重跑")
    else:
        print("\n✅ 数字校验通过：叙述里的所有数字都能在输入事实里找到依据")

    return result


if __name__ == "__main__":
    run()
