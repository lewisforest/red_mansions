# -*- coding: utf-8 -*-
"""
01_cleaner.py - 无损版
保留 100% 正文、序言与脂批，按自然情节大段切分（默认 800~1500 字/块）。

大块切分是这一版最主要的提速手段：全书切成几百个块而不是几千个，
后续 LLM 调用次数直接减少一个数量级。
"""

import os
import re
import json

CHAPTER_PATTERN = re.compile(
    r'(^\s*(?:卷[一二三四五六七八九十0-9]+\s*)?'
    r'(?:戚蓼生序|脂砚斋[^\n]*?序|序言|凡例|第[〇零一二三四五六七八九十百0-9]+\s*回[^\n]*))',
    re.MULTILINE
)
BRACKET_COMMENT_PATTERN = re.compile(r'【(.*?)】', re.DOTALL)
SENTENCE_END_CHARS = "。！？…”』"

# 常见网络下载声明/纯分隔线，这些不是《红楼梦》正文，过滤掉能省下浪费的 LLM 调用，
# 不属于对正文内容的删减。命中任意一条即视为噪音行。
_AD_PATTERNS = re.compile(r'(为您制作|下载的文件来自|本电子书由|txt.?下载|整理制作|www\.|\.com)', re.IGNORECASE)


def _is_noise_line(line: str) -> bool:
    if _AD_PATTERNS.search(line):
        return True
    stripped = line.strip('—=一－- ')
    if not stripped:  # 全是分隔符号的行，如 ——— 、 === 、 ———一———
        return True
    return False

# 依次尝试的编码列表：优先严格解码（不丢字），全部失败才退化为忽略非法字符
CANDIDATE_ENCODINGS = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5']


def _natural_sort_key(filename: str):
    """
    数字感知的文件名排序：避免 '10.txt' 被字符串排序排到 '2.txt' 前面。
    整套时间推理机制依赖 segment_id 递增 == 阅读顺序，文件排序错了会导致
    后面锚点校准和前向填充全部基于错误的顺序，所以这里不能简单用字符串排序。
    """
    parts = re.split(r'(\d+)', filename)
    return [int(p) if p.isdigit() else p for p in parts]


def _read_text_auto_encoding(file_path: str):
    """
    自动探测文件编码，避免用 errors='ignore' 静默丢字/产生乱码。
    很多老的红楼梦 txt 资源是 GBK/GB18030 编码，如果强行按 UTF-8 读取，
    整段文字会乱码，导致章节标题、时间关键词等所有正则全部失配。
    """
    with open(file_path, 'rb') as f:
        raw_bytes = f.read()

    for enc in CANDIDATE_ENCODINGS:
        try:
            return raw_bytes.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue

    print(f"  ⚠️ 无法用常见编码完整解码该文件，已用 utf-8 忽略非法字符读取，"
          f"可能丢失部分内容，建议手动确认原始编码。")
    return raw_bytes.decode('utf-8', errors='ignore'), 'utf-8(ignore)'


def clean_single_text(raw_text: str, min_chars: int = 800, max_chars: int = 1500) -> list:
    cleaned = re.sub(r'脂砚斋重评石头记[—\-]*曹雪芹?', '', raw_text)
    cleaned = CHAPTER_PATTERN.sub(r'\n\nSECTION_HEADER:\1\n\n', cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    chunks = []
    current_chapter = "序言/前言"
    buffer_parts = []
    buffer_zhi = []
    buffer_len = 0

    def flush_buffer():
        nonlocal buffer_parts, buffer_zhi, buffer_len
        narrative_str = "\n".join(buffer_parts).strip()
        if narrative_str or buffer_zhi:
            chunks.append({
                "chapter": current_chapter,
                "narrative": narrative_str,
                "zhi_evidence": list(buffer_zhi),
            })
        buffer_parts, buffer_zhi, buffer_len = [], [], 0

    chapter_seen = False
    for line in lines:
        if line.startswith("SECTION_HEADER:"):
            flush_buffer()
            current_chapter = line.replace("SECTION_HEADER:", "").strip()
            chapter_seen = True
            continue

        if _is_noise_line(line):
            continue

        # 跨行提取所有【...】里的内容作为脂批候选
        raw_comments = BRACKET_COMMENT_PATTERN.findall(line)
        if raw_comments:
            buffer_zhi.extend([re.sub(r'\s+', ' ', c).strip() for c in raw_comments if c.strip()])

        clean_narrative = BRACKET_COMMENT_PATTERN.sub('', line).strip()
        clean_narrative = re.sub(r'^(?:甲戌|蒙|庚辰|己卯|戚序|脂砚?|靖|立)[：:]', '', clean_narrative).strip()

        if clean_narrative:
            buffer_parts.append(clean_narrative)
            buffer_len += len(clean_narrative)

        # 达到较大字数块且处于句尾时收尾，给 LLM 提供充足的前后文，同时控制块大小
        reached_max = buffer_len >= max_chars
        reached_min_and_sentence_end = (
            buffer_len >= min_chars and clean_narrative and clean_narrative[-1] in SENTENCE_END_CHARS
        )
        if reached_max or reached_min_and_sentence_end:
            flush_buffer()

    flush_buffer()

    if not chapter_seen:
        print("  ⚠️ 未在本文件中检测到任何『第X回』/序言/凡例标题，全部内容归入了默认章节，"
              "请检查原始文件格式是否符合预期（可能是编码问题或标题格式与正则不符）。")

    return chunks


def clean_batch_files(input_dir: str, output_file: str, min_chars: int = 800, max_chars: int = 1500):
    all_chunks = []

    if not os.path.exists(input_dir):
        print(f"❌ 错误：找不到目录 {input_dir}")
        return []

    files = sorted([f for f in os.listdir(input_dir) if f.endswith('.txt')], key=_natural_sort_key)
    if not files:
        print(f"⚠️ 警告：{input_dir} 下没有找到任何 .txt 文件")
        return []

    for file_name in files:
        file_path = os.path.join(input_dir, file_name)
        print(f"正在清洗文件: {file_name}...")
        try:
            raw_text, encoding_used = _read_text_auto_encoding(file_path)
            print(f"  （识别编码: {encoding_used}）")
            file_chunks = clean_single_text(raw_text, min_chars=min_chars, max_chars=max_chars)
            all_chunks.extend(file_chunks)
            print(f"  -> 本文件生成 {len(file_chunks)} 个段落块")
        except Exception as e:
            # 单个文件出错不应该让整批处理中断
            print(f"  ❌ 处理该文件时出错，已跳过: {e}")

    # 给每个段落分配递增的 segment_id——这个顺序就是全书的阅读顺序（先按文件名
    # 排序，同一文件内再按文本出现顺序），04_timeline_aligner.py 的"锚点校准 +
    # 前向填充"整套时间推理机制都建立在"segment_id 递增 == 故事时间线推进"这个
    # 假设之上，顺序错了后面全盘皆错，所以这里显式赋值、不依赖上游自己编号。
    for idx, chunk in enumerate(all_chunks, start=1):
        chunk["segment_id"] = idx

    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    unique_chapters = len({c['chapter'] for c in all_chunks})
    print(f"✅ 无损清洗完成！共生成 {len(all_chunks)} 个段落块（segment_id 1~{len(all_chunks)}），"
          f"覆盖 {unique_chapters} 个章节/序言单元。")
    if len(all_chunks) > 0 and unique_chapters <= 1:
        print("⚠️ 注意：所有段落都被归入了同一个章节标签，这通常意味着章节标题没有被正确识别，"
              "请检查上面每个文件的『识别编码』和标题匹配提示。")

    return all_chunks


if __name__ == "__main__":
    clean_batch_files('./脂砚斋评红楼梦', './processed_data/01_cleaned_segments.json')
