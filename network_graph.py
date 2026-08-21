# -*- coding: utf-8 -*-
"""
network_graph.py
"事件 -> 年份"的全局锚点地图，纯 Python 关键词匹配，不需要 LLM 参与判断。

03_character_network.py 负责统计"谁和谁一起出现过"（人物共现网络）；
这个文件负责"某个具体事件对应哪个锚点年份"（事件层面的地图）。
04_timeline_aligner.py 把两者结合起来做真正的时间推理：
  1. 用 character_alias.py 把人物名字归一化到标准名；
  2. 用这里的 ANCHOR_GRAPH 关键词表，看这一段是否命中某个已知锚点事件——
     命中就把这一段"钉"在锚点年份上（高置信度，同时能纠正之前的累积漂移）；
  3. 没命中锚点的段落，用 TIME_DELTA_KEYWORDS 检查 time_markers 里有没有
     "次年""数年""十载"这类词，命中就在上一次的年份基础上加相应的年数
     （中等置信度）；
  4. 都没命中就沿用上一段的年份（低置信度，仅表示"大概率还在同一年"）。

这样时间轴的推进始终有真实文本证据支撑（人物、事件、时间词），而不是
"第几回大概是第几年"这种和实际内容脱节的粗暴区间表；而且全部逻辑都在
Python 里跑，秒级完成，不会有 LLM 幻觉风险。

⚠️ 下面的锚点年份是为了让 pipeline 内部时间轴自洽而设定的参考框架，不是
红学界公认的唯一定论。如果你有更确信的考据依据，直接改这里的 year_offset /
keywords / desc 即可，下游代码不用跟着改。
"""

# 参考基准：元年 = 0（对应甄士隐英莲三岁出场）
ANCHOR_GRAPH = {
    "YINGLIAN_BORN": {
        "year_offset": 0,
        "keywords": ["香菱", "三岁", "甄士隐"],
        "desc": "甄士隐之女英莲三岁出场（红楼纪年起点）",
    },
    "YINGLIAN_LOST": {
        "year_offset": 2,
        "keywords": ["香菱", "五岁", "霍启", "元宵"],
        "desc": "英莲五岁元宵节被拐，甄家随后败落",
    },
    "YINGLIAN_CHANGES_NAME":{
        "year_offset": 7,
        "keywords": ["香菱", "十二三岁","冯渊","薛蟠"],
        "desc": "英莲被同时卖给冯渊和薛蟠，冯渊被打死，冯渊家奴告状；薛宝钗准备入京待选",
    },
    "DAIYU_MOTHER_DEATH_AND_TRAVEL": {
        "year_offset": 8,
        "keywords": ["贾敏", "林黛玉", "扬州", "抛父", "进京", "葫芦案"],
        "desc": "贾敏病逝，黛玉抛父进京，隆冬抵达荣国府；贾雨村接手葫芦案",
    },
    "XUE_FAMILY_ARRIVE": {
        "year_offset": 9,
        "keywords": ["薛姨妈", "薛宝钗", "香菱", "葫芦案", "护官符"],
        "desc": "贾雨村葫芦案结案；薛家举家入京，宝钗出场",
    },
    "BAOYU_TAIXU_DREAM": {
        "year_offset": 10,
        "keywords": ["太虚幻境", "秦可卿", "警幻仙姑", "贾宝玉", "梅花"],
        "desc": "宁国府赏梅，宝玉梦游太虚幻境",
    },
    "BAOYU_SEXUAL_RELATION": {
        "year_offset": 10,
        "keywords": ["贾宝玉", "袭人","刘姥姥", "周瑞家的", "王熙凤","平儿", "板儿"],
        "desc": "贾宝玉和袭人发生性关系；刘姥姥进大观园",
    },
    "QIN_KEQING_SICK": {
        "year_offset": 10,
        "keywords": ["秦可卿", "贾敬", "贾瑞", "王熙凤"],
        "desc": "秦可卿生病，王熙凤探视；贾敬过生日；贾瑞对王熙凤有非分之想",
    },
    "QIN_KEQING_AND_JAI_RUI_DEATH": {
        "year_offset": 13,
        "keywords": ["秦可卿", "天香楼", "出殡", "病逝", "贾瑞"],
        "desc": "秦可卿病逝、出殡； 贾瑞死亡",
    },
    "LIN_RUHAI_DEATH": {
        "year_offset": 13,
        "keywords": ["林如海", "扬州", "病重", "奔丧"],
        "desc": "林如海在扬州病逝，黛玉奔丧",
    },
    "YUANCHUN_VISIT": {
        "year_offset": 14,
        "keywords": ["贾元春", "省亲", "大观园", "题咏"],
        "desc": "元春晋封贤德妃回家省亲，大观园首次正式启用",
    },
}

# 事件层面命中锚点用的是"是不是这件事"，这里补一层"过了多久"的信号：
# 如果一段文字没有命中任何锚点，但 time_markers 里出现了这些词，就在上一次
# 的年份基础上做相应的增量调整——这一步也完全不需要 LLM 参与判断，纯粹是
# 对已经抽取出来的 time_markers 原文做关键词匹配。
TIME_DELTA_KEYWORDS = [
    ("十载", 10), ("十年", 10),
    ("八年", 8), ("七年", 7), ("六年", 6),
    ("数载", 3), ("数年", 3), ("几年", 3), ("三年", 3),
    ("两年", 2), ("二年", 2),
    ("转眼", 1), ("次年", 1), ("越年", 1), ("越明年", 1),
    ("明年", 1), ("次冬", 1), ("过了一年", 1),
]


def align_segment_to_graph(characters: list, core_events: list, time_markers: list,
                            anchor_graph: dict = None, min_hits: int = 2):
    """
    用归一化后的人物名单 + 事件文本 + 时间词，对一段文本做关键词匹配，
    返回命中的锚点列表（按命中关键词数量降序，第一个即最佳匹配）。
    """
    anchor_graph = anchor_graph or ANCHOR_GRAPH
    chars_set = set(characters or [])
    combined_text = "；".join((core_events or []) + (time_markers or []))

    matches = []
    for anchor_id, info in anchor_graph.items():
        hit_count = sum(
            1 for kw in info["keywords"]
            if kw in chars_set or kw in combined_text
        )
        if hit_count >= min_hits:
            matches.append({
                "anchor_id": anchor_id,
                "year_offset": info["year_offset"],
                "desc": info["desc"],
                "hit_count": hit_count,
            })

    matches.sort(key=lambda m: m["hit_count"], reverse=True)
    return matches


def infer_year_delta_from_markers(time_markers: list) -> int:
    """没命中锚点时，看 time_markers 里有没有跨度词，返回应该增加的年数（没有则返回0）"""
    combined = "；".join(time_markers or [])
    for keyword, delta in TIME_DELTA_KEYWORDS:
        if keyword in combined:
            return delta
    return 0
