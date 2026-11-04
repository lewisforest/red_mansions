# -*- coding: utf-8 -*-
"""
01_cleaner.py - 净化版（源头彻底剔除脂批与注释）
在切片阶段就将所有脂砚斋批语、夹批、评论行物理抹杀，
输出绝对干净的正文切片，供后续大模型或正则精准提取。
"""

import os
import re
import json

CHAPTER_PATTERN = re.compile(
    r'(^\s*(?:卷[一二三四五六七八九十0-9]+\s*)?'
    r'(?:戚蓼生序|脂砚斋[^\n]*?序|序言|凡例|第[〇零一二三四五六七八九十百0-9]+\s*回[^\n]*))',
    re.MULTILINE
)

# ⭐️ 核心升级：用于在源头彻底粉碎各类批语的强力正则
# 覆盖 【...】, [...], (...), 〔...〕, 嵌套双括号等
HEAVY_COMMENT_PATTERN = re.compile(r'\[.*?\]|【.*?】|（.*?）|〔.*?〕|\(.*?\)', re.DOTALL)

SENTENCE_END_CHARS = "。！？…”』"

_AD_PATTERNS = re.compile(r'(为您制作|下载的文件来自|本电子书由|txt.?下载|整理制作|www\.|\.com)', re.IGNORECASE)


def _is_noise_line(line: str) -> bool:
    if _AD_PATTERNS.search(line):
        return True
    stripped = line.strip('—=一－- ')
    if not stripped:
        return True
    # ⭐️ 额外过滤掉包含评语特征的行
    if any(kw in line for kw in ["脂砚", "甲戌", "蒙侧", "戚序", "蒙双行", "眉批", "双行夹批", "夹批"]):
        return True
    return False


CANDIDATE_ENCODINGS = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5']


def _natural_sort_key(filename: str):
    parts = re.split(r'(\d+)', filename)
    return [int(p) if p.isdigit() else p for p in parts]


def _read_text_auto_encoding(file_path: str):
    with open(file_path, 'rb') as f:
        raw_bytes = f.read()

    for enc in CANDIDATE_ENCODINGS:
        try:
            return raw_bytes.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue

    return raw_bytes.decode('utf-8', errors='ignore'), 'utf-8(ignore)'


def clean_single_text(raw_text: str, min_chars: int = 800, max_chars: int = 1500) -> list:
    cleaned = re.sub(r'脂砚斋重评石头记[—\-]*曹雪芹?', '', raw_text)
    cleaned = CHAPTER_PATTERN.sub(r'\n\nSECTION_HEADER:\1\n\n', cleaned)

    # ⭐️ 在切分行之前，先用正则把整篇文本里所有的夹批括号连根拔起
    cleaned = HEAVY_COMMENT_PATTERN.sub('', cleaned)

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    chunks = []
    current_chapter = "序言/前言"
    buffer_parts = []
    buffer_len = 0

    def flush_buffer():
        nonlocal buffer_parts, buffer_len
        narrative_str = "\n".join(buffer_parts).strip()
        if narrative_str:
            chunks.append({
                "chapter": current_chapter,
                "narrative": narrative_str,
            })
        buffer_parts, buffer_len = [], 0

    chapter_seen = False
    for line in lines:
        if line.startswith("SECTION_HEADER:"):
            flush_buffer()
            current_chapter = line.replace("SECTION_HEADER:", "").strip()
            chapter_seen = True
            continue

        if _is_noise_line(line):
            continue

        clean_narrative = line.strip()
        clean_narrative = re.sub(r'^(?:甲戌|蒙|庚辰|己卯|戚序|脂砚?|靖|立)[：:]', '', clean_narrative).strip()

        if clean_narrative:
            buffer_parts.append(clean_narrative)
            buffer_len += len(clean_narrative)

        reached_max = buffer_len >= max_chars
        reached_min_and_sentence_end = (
            buffer_len >= min_chars and clean_narrative and clean_narrative[-1] in SENTENCE_END_CHARS
        )
        if reached_max or reached_min_and_sentence_end:
            flush_buffer()

    flush_buffer()
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
        raw_text, encoding_used = _read_text_auto_encoding(file_path)
        file_chunks = clean_single_text(raw_text, min_chars=min_chars, max_chars=max_chars)
        all_chunks.extend(file_chunks)
        print(f"  -> 本文件生成 {len(file_chunks)} 个纯净正文块")

    for idx, chunk in enumerate(all_chunks, start=1):
        chunk["segment_id"] = idx

    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    unique_chapters = len({c['chapter'] for c in all_chunks})
    print(f"✅ 彻底剔除脂批的净化清洗完成！共生成 {len(all_chunks)} 个正文段落块 -> {output_file}")
    return all_chunks


if __name__ == "__main__":
    clean_batch_files('./脂砚斋评红楼梦', './processed_data/01_cleaned_segments.json')
