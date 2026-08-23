# -*- coding: utf-8 -*-
"""
network_graph.py
"事件 -> 年份"的全局锚点地图，纯 Python 关键词匹配，不需要 LLM 参与判断。
"""

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
    "YINGLIAN_CHANGES_NAME": {
        "year_offset": 7,
        "keywords": ["香菱", "十二三岁", "冯渊", "薛蟠"],
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
        "keywords": ["贾宝玉", "袭人", "刘姥姥", "周瑞家的", "王熙凤", "平儿", "板儿"],
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
        "desc": "秦可卿病逝、出殡；贾瑞死亡",
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
    combined = "；".join(time_markers or [])
    for keyword, delta in TIME_DELTA_KEYWORDS:
        if keyword in combined:
            return delta
    return 0
