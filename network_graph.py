# -*- coding: utf-8 -*-
"""
network_graph.py
人物关系网络 + 全局同步锚点（Cross-referencing Events）。

核心思路：单段文本靠"次年""数年后"这类相对时间词做局部推理，长距离累加下来
误差会越滚越大（第 5 回和第 50 回之间隔了几十段相对推理，随便哪段判断错一点，
后面全部跟着偏）。但红楼梦里有一些红学公认的"交叉锚点事件"——比如林如海病逝
与秦可卿出殡是同一时间窗口——只要在文本里识别出这类事件，就能不依赖前面的
累加结果，直接把当前段落"钉"在一个绝对年份上，后续段落再从这个新的锚点重新
开始相对推理，误差不会无限累积。

附带的提速效果：锚点匹配本质上是"模式匹配"而不是"展开式因果推导"，所以命中
锚点时可以让模型只做简短确认，不用像三步检查法那样写一整段推理链，输出 token
数能明显减少。

⚠️ 重要说明：下面这套锚点年份是为了让 pipeline 内部的时间轴保持自洽而设定的
一套参考框架，不是红学界公认的唯一定论——《红楼梦》本身的内部纪年就存在不少
公认的、可能是作者刻意为之的矛盾（草蛇灰线本身就允许多重解读）。如果你有更
确信的考据依据，直接改这里的 year_offset / desc 即可，下游代码不用跟着改。
"""

# 参考基准：与最初 prompt 里的"元年参照卡"保持一致（元年 = 0）
ANCHOR_GRAPH = {
    "YINGLIAN_BORN": {
        "year_offset": 0,
        "desc": "甄士隐之女英莲三岁出场",
    },
    "YINGLIAN_LOST": {
        "year_offset": 2,
        "desc": "英莲五岁元宵节被拐，甄家随后败落",
    },
    "DAIYU_MOTHER_DEATH": {
        "year_offset": 4,
        "desc": "林黛玉之母贾敏病逝（黛玉约5岁），林如海延请贾雨村教读",
    },
    "DAIYU_ENTER_JIA": {
        "year_offset": 7,
        "desc": "林黛玉丧母后抛父进京入荣国府（约6~7岁）；此时英莲已被卖改名香菱（约12~13岁）",
    },
    "LIN_RUHAI_DEATH": {
        "year_offset": 9,
        "desc": "林如海在扬州病逝，黛玉奔丧",
    },
    "QIN_KEQING_DEATH": {
        "year_offset": 9,
        "desc": "秦可卿病逝、出殡，与林如海病逝为同一时间窗口的同步事件",
    },
}


class RedMansionTimelineGraph:
    """
    极简版"事件网络同步器"：
    如果某段文本被 LLM 识别出命中了 ANCHOR_GRAPH 里的某个锚点，就直接用锚点
    预设的绝对年份校准该段落的位置，覆盖掉之前一路累加相对时间推出来的估计值。
    """

    def __init__(self, anchors: dict = None):
        self.anchors = anchors or ANCHOR_GRAPH

    def align_segment(self, llm_output: dict) -> dict:
        """
        扫描 llm_output['relational_events']，命中锚点就写入：
        - matched_anchor: 命中的锚点 key
        - matched_anchor_desc: 锚点描述
        - calculated_global_year_offset: 锚点对应的绝对参考年份
        没命中则这三个字段填 None，供下游区分"锚点校准"与"相对推理"两种来源。
        """
        relational_events = llm_output.get("relational_events")
        if isinstance(relational_events, list):
            for ev in relational_events:
                if not isinstance(ev, dict):
                    continue
                anchor_key = ev.get("network_anchor")
                if anchor_key and anchor_key in self.anchors:
                    info = self.anchors[anchor_key]
                    llm_output["matched_anchor"] = anchor_key
                    llm_output["calculated_global_year_offset"] = info["year_offset"]
                    llm_output["matched_anchor_desc"] = info["desc"]
                    return llm_output

        llm_output.setdefault("matched_anchor", None)
        llm_output.setdefault("calculated_global_year_offset", None)
        llm_output.setdefault("matched_anchor_desc", None)
        return llm_output

    def build_prompt_context(self) -> str:
        """生成供 Prompt 使用的人物关系网络说明文字"""
        lines = ["【核心人物关系与同步时间锚点参照系（用于交叉校验，仅供模式匹配参考）】："]
        for key, info in self.anchors.items():
            lines.append(f"- {key}：{info['desc']}（内部参考年份 Y{info['year_offset']}）")
        return "\n".join(lines)
