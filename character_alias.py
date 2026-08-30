# -*- coding: utf-8 -*-
"""
character_alias.py
全书人物"别名 -> 标准名"的统一映射表，被 02/03/04 各阶段共用。

本文件职责单一：只做人物称谓归一化（alias -> canonical name），
不包含任何人物关系（父子/夫妻/主仆等）的硬编码判断——关系由
03_character_network.py 从 02 阶段的抽取结果里统计推理得到。
"""

from typing import Dict, List, Set, Tuple

COUPLE_HUSBANDS = [
    "林之孝", "周瑞", "赖大", "王善保", "吴新登",
    "乌进孝", "包勇", "吴贵", "郑好时", "秦显"
]

RAW_CHARACTER_MAP: Dict[str, List[str]] = {
    "贾宝玉": ["宝玉", "宝二爷", "怡红公子", "绛洞花主", "爱哥哥", "神瑛侍者", "宝兄弟", "富贵闲人"],
    "通灵宝玉": ["顽石", "此石", "石兄", "石道", "补天石", "顽石三万六千五百零一块", "石头"],
    "林黛玉": ["黛玉", "林妹妹", "颦颦", "潇湘妃子", "颦儿", "绛珠仙草", "绛珠仙子", "潇湘馆主", "林姑娘", "林丫头", "林潇湘", "女学生"],
    "薛宝钗": ["宝钗", "宝姐姐", "宝姑娘", "蘅芜君", "薛姑娘", "宝丫头", "蘅芜女", "薛大妹妹"],
    "王熙凤": ["凤姐", "凤姐儿", "琏二奶奶", "凤辣子", "凤丫头", "熙凤", "凤哥儿", "阿凤"],
    "贾母": ["老祖宗", "老太太", "史太君", "太夫人", "贾老夫人"],
    "史湘云": ["湘云", "云妹妹", "枕霞旧友", "史姑娘", "云丫头"],
    "李纨": ["李宫裁", "宫裁", "稻香老农", "李大奶奶", "纨纨", "李氏"],
    "妙玉": ["槛外人", "栊翠庵主人", "妙玉姑"],
    "贾元春": ["元春", "贾妃", "贵妃", "凤藻宫尚书", "元妃", "大小姐"],
    "贾迎春": ["迎春", "二姑娘", "木头", "迎姐儿", "二小姐"],
    "贾探春": ["探春", "三姑娘", "蕉下客", "敏探春", "三小姐"],
    "贾惜春": ["惜春", "四姑娘", "勘破三春", "四小姐"],
    "秦可卿": ["可卿", "蓉大奶奶", "大奶奶", "兼美", "秦氏", "官氏", "可儿"],
    "警幻仙子": ["仙姑", "警幻仙姑", "警幻"],
    "夏金桂": ["金桂"],
    "贾巧姐": ["巧姐", "巧姐儿"],
    "贾大姐": ["大姐儿"],

    "贾政": ["存周", "政老爹", "政老爷", "政公"],
    "贾敏": ["贾夫人", "贾氏夫人", "贾氏","林姑妈"],
    "贾赦": ["恩侯", "赦老爹", "赦老爷", "赦公"],
    "贾敬": ["敬老爷", "敬公"],
    "贾琏": ["琏二爷", "琏爷", "琏哥儿", "琏弟"],
    "贾珠":["珠","珠大爷"],
    "贾珍": ["珍爷", "珍哥儿", "珍大爷", "大爷"],
    "贾环": ["环哥", "环哥儿", "三爷", "贾三爷", "环弟"],
    "贾蓉": ["蓉哥", "蓉哥儿", "蓉大爷"],
    "贾兰": ["兰哥", "兰哥儿", "兰儿", "贾蓝"],
    "贾芸": ["芸哥", "芸哥儿"],
    "贾蔷": ["蔷哥", "蔷哥儿"],
    "贾芹": ["芹哥", "芹哥儿"],
    "贾瑞": ["天祥", "瑞大爷"],
    "贾代儒": ["代儒", "儒老爹"],
    "贾代化": ["代化"],
    "贾代修": ["代修"],
    "贾代善": ["代善"],
    "林如海": ["林海", "如海"],
    "贾雨村": ["雨村", "时飞", "贾时飞", "贾化", "语村"],
    "小沙弥":["门子"],
    "甄士隐": ["士隐", "费", "甄费"],
    "冷子兴": ["子兴"],
    "北静王": ["水溶"],

    "薛蟠": ["薛大爷", "呆霸王", "薛大哥", "文龙"],
    "薛宝琴": ["宝琴", "琴妹妹", "琴姑娘"],
    "薛蝌": ["蝌哥", "蝌哥儿"],
    "尤老娘": ["尤老娘"],
    "尤氏": ["尤氏", "大奶奶"],
    "尤二姐": ["二姐", "尤二姐"],
    "尤三姐": ["三姐", "尤三姐"],
    "王子腾": ["子腾", "王伯父"],
    "王仁": ["王仁"],
    "王夫人": ["王夫人", "太太", "二太太"],

    "香菱": ["英莲", "甄英莲", "秋菱", "菱角儿"],
    "袭人": ["花袭人", "珍珠"],
    "紫鹃": ["鹦哥", "紫鹃妹妹"],
    "莺儿": ["黄金莺", "掌珠", "金莺"],
    "晴雯": ["勇晴雯"],
    "鸳鸯": ["金鸳鸯", "鸳鸯女"],
    "平儿": ["平姑娘"],
    "金钏": ["金钏儿"],
    "玉钏": ["玉钏儿"],
    "司棋": ["司棋"],
    "抱琴": ["抱琴"],
    "侍书": ["侍书"],
    "入画": ["入画"],
    "麝月": ["麝月"],
    "雪雁": ["雪雁"],
    "碧痕": ["碧痕"],
    "茜雪": ["茜雪"],
    "彩云": ["彩云"],
    "彩霞": ["彩霞"],
    "林红玉": ["小红", "红玉"],
    "琥珀": ["琥珀"],

    "茗烟": ["茗烟"],
    "焙茗": ["焙茗"],
    "蒋玉菡": ["琪官"],
    "芳官": ["耶律雄奴", "雄奴", "温都里纳"],
    "龄官": ["龄官"],
    "藕官": ["藕官"],
    "蕊官": ["蕊官"],
    "秦钟": ["秦锺", "鲸卿", "秦相公"],
    "柳湘莲": ["柳二郎", "冷面郎君", "湘莲","柳二爷"],
    "刘姥姥": ["刘老老"],
    "焦大": ["焦大"],
    "戴权": ["载权"],
    "石呆子": ["石呆子"],
    "张金哥": ["金哥"],
    "封氏": ["封氏孺人"], 

    "林之孝": ["林管家"],
    "林之孝家的": ["林之孝家", "双管家"],
    "周瑞": ["周瑞"],
    "周瑞家的": ["周瑞家"],
    "赖大": ["赖总管"],
    "赖大家的": ["赖大娘", "赖大家的"],
    "王善保家的": ["王善保家"],
}

NOISE_WORDS: Set[str] = {
    "吉时", "一行", "贾府三艳", "婆子", "老婆子", "和尚", "道人", "道士", "先生",
    "小厮", "小丫头们", "小丫头", "姊妹", "媳妇", "众丫鬟", "众人", "丫头", "姑娘",
    "老爷", "太太", "奶奶", "少爷", "主子", "奴才", "门客", "家人", "奶妈", "嬷嬷",
    "公人", "太监", "官兵", "老尼", "哥哥", "弟弟", "姐姐", "妹妹"
}


def _build_alias_structures() -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    flat_map = {}
    for canon, aliases in RAW_CHARACTER_MAP.items():
        flat_map[canon] = canon
        for alias in aliases:
            flat_map[alias] = canon

    for husband in COUPLE_HUSBANDS:
        wife_canon = f"{husband}家的"
        if wife_canon not in flat_map:
            flat_map[wife_canon] = wife_canon
            flat_map[f"{husband}家"] = wife_canon

    sorted_tuples = sorted(flat_map.items(), key=lambda x: len(x[0]), reverse=True)
    return flat_map, sorted_tuples


ALIAS_MAP, SORTED_ALIAS_TUPLES = _build_alias_structures()


def clean_character_name(raw_name: str):
    if not raw_name:
        return None
    name = str(raw_name).strip(" '\"\u2018\u2019\u201c\u201d")
    if not name or name in NOISE_WORDS:
        return None

    if name in ALIAS_MAP:
        canonical = ALIAS_MAP[name]
    else:
        canonical = None
        for alias, canon in SORTED_ALIAS_TUPLES:
            if len(alias) >= 2 and alias in name:
                canonical = canon
                break
        if not canonical:
            canonical = name

    if len(canonical) < 2 or canonical in NOISE_WORDS:
        return None
    return canonical


def clean_character_list(raw_names) -> list:
    cleaned = []
    seen = set()
    for raw in raw_names or []:
        c = clean_character_name(raw)
        if c and c not in seen:
            cleaned.append(c)
            seen.add(c)
    return cleaned


def get_all_aliases(canonical_name: str) -> list:
    names = [canonical_name]
    for alias, canon in ALIAS_MAP.items():
        if canon == canonical_name and alias not in names:
            names.append(alias)
    return names


def is_character_grounded(canonical_name: str, text: str) -> bool:
    return any(name in (text or "") for name in get_all_aliases(canonical_name))

def get_primary_characters(min_aliases: int = 4):
    """别名数量达到阈值的视为主要人物，用于年龄追踪等下游筛选"""
    return {canon for canon, aliases in RAW_CHARACTER_MAP.items() if len(aliases) >= min_aliases}
