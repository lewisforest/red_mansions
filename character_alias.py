# -*- coding: utf-8 -*-
"""
character_alias.py
全书人物"别名 -> 标准名"的统一映射表，被 03_character_network.py 和
04_timeline_aligner.py 共用。
"""

from typing import Dict, List, Set, Tuple

# 1. 男仆/管家列表：自动派生其妻子的“某某家的”独立节点
COUPLE_HUSBANDS = [
    "林之孝", "周瑞", "赖大", "王善保", "吴新登",
    "乌进孝", "包勇", "吴贵", "郑好时", "秦显"
]

# 2. 全量人物与别名原表 (标准名 -> 别名列表)
RAW_CHARACTER_MAP: Dict[str, List[str]] = {
    # === 十二金钗及主要女性 ===
    "贾宝玉": ["宝玉", "宝二爷", "怡红公子", "绛洞花主", "爱哥哥", "神瑛侍者", "宝兄弟", "富贵闲人"],
    "林黛玉": ["黛玉", "林妹妹", "颦颦", "潇湘妃子", "颦儿", "绛珠仙草", "绛珠仙子", "潇湘馆主", "林姑娘", "林丫头"],
    "薛宝钗": ["宝钗", "宝姐姐", "宝姑娘", "蘅芜君", "薛姑娘", "宝丫头", "蘅芜女"],
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
    "警幻仙子": ["仙姑", "警幻仙姑"],
    "贾巧姐": ["巧姐", "巧姐儿"],
    "贾大姐": ["大姐儿"],

    # === 贾府男丁及长辈 ===
    "贾政": ["存周", "政老爹", "政老爷", "政公"],
    "贾敏": ["贾夫人"],
    "贾赦": ["恩侯", "赦老爹", "赦老爷", "赦公"],
    "贾敬": ["敬老爷", "敬公"],
    "贾琏": ["琏二爷", "琏爷", "琏哥儿", "琏弟"],
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
    "林如海":["林海", "如海"],
    "秦钟": ["秦相公"],
    "贾雨村": ["雨村", "时飞", "贾时飞"],
    "甄士隐": ["士隐", "费", "甄费"],
    "冷子兴": ["子兴"],

    # === 薛家与王家 ===
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

    # === 丫鬟与侍女 ===
    "香菱": ["英莲", "甄英莲", "秋菱", "菱角儿"],
    "袭人": ["花袭人", "珍珠"],
    "紫鹃": ["鹦哥", "紫鹃妹妹"],
    "莺儿": ["黄金莺", "掌珠","金莺"],
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

    # === 小厮、戏子与外人 ===
    "茗烟": ["茗烟"],
    "焙茗": ["焙茗"],
    "蒋玉菡": ["琪官"],
    "芳官": ["耶律雄奴", "雄奴", "温都里纳"],
    "龄官": ["龄官"],
    "藕官": ["藕官"],
    "蕊官": ["蕊官"],
    "秦钟": ["秦锺", "鲸卿"],
    "柳湘莲": ["柳二郎", "冷面郎君", "湘莲"],
    "贾雨村": ["雨村", "贾化", "语村"],
    "甄士隐": ["士隐", "甄费"],
    "刘姥姥": ["刘老老"],
    "焦大": ["焦大"],
    "戴权": ["载权"],
    "冷子兴": ["冷子兴"],
    "石呆子": ["石呆子"],

    # === 家人管家夫妻 ===
    "林之孝": ["林管家"],
    "林之孝家的": ["林之孝家", "双管家"],
    "周瑞": ["周瑞"],
    "周瑞家的": ["周瑞家"],
    "赖大": ["赖总管"],
    "赖大家的": ["赖大娘", "赖大家的"],
    "王善保家的": ["王善保家"],
}

# 非实体噪声词过滤集合
NOISE_WORDS: Set[str] = {
    "吉时", "一行", "贾府三艳", "婆子", "老婆子", "和尚", "道人", "道士", "先生",
    "小厮", "小丫头们", "小丫头", "姊妹", "媳妇", "众丫鬟", "众人", "丫头", "姑娘",
    "老爷", "太太", "奶奶", "少爷", "主子", "奴才", "门客", "家人", "奶妈", "嬷嬷",
    "公人", "太监", "官兵", "老尼", "哥哥", "弟弟", "姐姐", "妹妹"
}


def _build_alias_structures() -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    """构建扁平 ALIAS_MAP 及按字符串长度降序排列的元组列表"""
    flat_map = {}
    for canon, aliases in RAW_CHARACTER_MAP.items():
        flat_map[canon] = canon
        for alias in aliases:
            flat_map[alias] = canon

    # 自动补充男仆妻子的派生词（如 "吴新登家的" -> "吴新登家的"）
    for husband in COUPLE_HUSBANDS:
        wife_canon = f"{husband}家的"
        if wife_canon not in flat_map:
            flat_map[wife_canon] = wife_canon
            flat_map[f"{husband}家"] = wife_canon

    # 按 Key 长度由大到小排序，确保长别名（如 "林之孝家的"）优先于短别名（如 "林之孝"）被命中
    sorted_tuples = sorted(flat_map.items(), key=lambda x: len(x[0]), reverse=True)
    return flat_map, sorted_tuples


ALIAS_MAP, SORTED_ALIAS_TUPLES = _build_alias_structures()


def clean_character_name(raw_name: str):
    """清理单个人名：最长前缀优先映射到标准名；噪声词/非法名返回 None"""
    if not raw_name:
        return None
    name = str(raw_name).strip(" '\"‘’“”")
    if not name or name in NOISE_WORDS:
        return None

    # 1. 精确匹配
    if name in ALIAS_MAP:
        canonical = ALIAS_MAP[name]
    else:
        # 2. 长词优先子串匹配（剥离后缀动作或修饰词，如 "林之孝家的回话" -> "林之孝家的"）
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
    """批量清理 + 去重，保持首次出现的顺序"""
    cleaned = []
    seen = set()
    for raw in raw_names or []:
        c = clean_character_name(raw)
        if c and c not in seen:
            cleaned.append(c)
            seen.add(c)
    return cleaned


def get_all_aliases(canonical_name: str) -> list:
    """反查一个标准名对应的所有别名（含标准名本身），用于逆向校验人物是否真的出现在文本里"""
    names = [canonical_name]
    for alias, canon in ALIAS_MAP.items():
        if canon == canonical_name and alias not in names:
            names.append(alias)
    return names


def is_character_grounded(canonical_name: str, text: str) -> bool:
    """判断某标准人名（或其任一别名）是否真的出现在给定文本里，用于剔除 LLM 虚假挂载的人物"""
    return any(name in (text or "") for name in get_all_aliases(canonical_name))
