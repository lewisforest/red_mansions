# -*- coding: utf-8 -*-
"""
01_cleaner.py - 结构化无损清洗版
适配抓取纯化后的《红楼梦》文本，精准剥离 〔...〕 脂批与正文，按自然情节打块。

本版修复了一个关键 bug：原代码是【逐行】调用 ZHIPY_PATTERN.findall(line_str)，
即使 pattern 带了 re.DOTALL，也没有意义——因为每次传进去的就只有一行文本，
DOTALL 压根没有"跨行"的机会生效。结果是：只要一条批注跨了 2 行以上才闭合
（比如"蒙本回前"这种回前诗批注很常见跨行），前面几行会被【完全当成正文】，
连〔这个符号本身都原样残留在 narrative 里，直接污染送进模型的文本。

修复方式：不再逐行清理，而是先把一个"块"要用到的原始行整体攒起来，在攒完的
整段文本上一次性做批注抽取/剔除，这样跨行批注也能被正确闭合匹配。

另外加了一个"括号平衡校验"：统计每个章节里〔和〕的数量，如果对不上，说明
原始文本本身可能有缺失的收尾符号（很可能是你删回车时手滑带掉的），直接打印
警告，而不是让代码悄悄猜一个可能错误的边界。
"""
import json
import os
import re

ZHIPY_PATTERN = re.compile(r"〔(.*?)〕", re.DOTALL)

CHAPTER_PATTERN = re.compile(
    r"^\s*(第[〇零一二三四五六七八九十百0-9]+\s*回[^\n]*|甲戌本凡例|凡例|序言)",
    re.MULTILINE,
)

SENTENCE_END_CHARS = "。！？…”』"


CANDIDATE_ENCODINGS = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5']


def _read_file_auto_encoding(filepath: str):
    """自动探测编码读取，避免因为编码猜错导致整段乱码（老 txt 资源常见 GBK）"""
    with open(filepath, 'rb') as f:
        raw_bytes = f.read()
    for enc in CANDIDATE_ENCODINGS:
        try:
            return raw_bytes.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode('utf-8', errors='ignore'), 'utf-8(ignore)'


def _check_bracket_balance(text: str, chapter_label: str):
    """检查〔〕数量是否配对，不配对说明原始文本可能缺了收尾符号"""
    open_count = text.count("〔")
    close_count = text.count("〕")
    if open_count != close_count:
        print(f"  ⚠️ 括号不平衡警告 [{chapter_label}]：〔 出现 {open_count} 次，"
              f"〕 出现 {close_count} 次，相差 {abs(open_count - close_count)}。"
              f"这通常意味着原文某处缺了收尾符号（常见于手动删回车时手滑带掉），"
              f"建议对照原始文本核实这一章的批注边界，否则可能出现多条批注被"
              f"错误合并成一条的情况。")


def clean_single_text(raw_text: str, min_chars: int = 800, max_chars: int = 1500) -> list:
    lines = raw_text.splitlines()
    chunks = []
    current_chapter = "前言/凡例"

    # 攒的是"原始行"（未剔除批注），只有 flush 时才在整段文本上一次性清理
    buffer_raw_lines = []
    buffer_len_estimate = 0
    chapter_full_text_for_check = []  # 用于按章节做括号平衡校验

    def flush_buffer():
        nonlocal buffer_raw_lines, buffer_len_estimate
        if not buffer_raw_lines:
            return

        whole_text = "\n".join(buffer_raw_lines)

        # 在整块文本上一次性抽取批注——跨行的批注这里能被正确闭合匹配
        zhi_matches = [re.sub(r"\s+", " ", m).strip() for m in ZHIPY_PATTERN.findall(whole_text)]
        zhi_matches = [m for m in zhi_matches if m]

        clean_narrative = ZHIPY_PATTERN.sub("", whole_text)
        # 清理批注后可能留下多余空行，重新整理一下
        clean_lines = [l.strip() for l in clean_narrative.splitlines() if l.strip()]
        clean_narrative = "\n".join(clean_lines)

        if clean_narrative or zhi_matches:
            chunks.append({
                "chapter": current_chapter,
                "narrative": clean_narrative,
                "zhi_evidence": zhi_matches,
            })

        buffer_raw_lines, buffer_len_estimate = [], 0

    for line in lines:
        line_str = line.strip()

        if not line_str or line_str.startswith("=" * 10):
            continue

        if CHAPTER_PATTERN.match(line_str):
            # 章节切换前，先对上一章累计的全部原始文本做一次括号平衡校验
            if chapter_full_text_for_check:
                _check_bracket_balance("".join(chapter_full_text_for_check), current_chapter)
            chapter_full_text_for_check = []

            flush_buffer()
            current_chapter = line_str
            continue

        chapter_full_text_for_check.append(line_str)
        buffer_raw_lines.append(line_str)

        # 粗略估计长度用于判断何时切块（即使跨行批注在这里被少量误计入，
        # 也只影响切块时机，不影响最终内容正确性——正确性由 flush 时的整块
        # 清理来保证）
        approx_len = len(re.sub(r"〔.*?〕", "", line_str, flags=re.DOTALL))
        buffer_len_estimate += approx_len

        ends_with_sentence = bool(line_str) and line_str[-1] in SENTENCE_END_CHARS
        reached_max = buffer_len_estimate >= max_chars
        reached_min_and_sentence_end = buffer_len_estimate >= min_chars and ends_with_sentence
        if reached_max or reached_min_and_sentence_end:
            flush_buffer()

    # 收尾：最后一章也要做括号平衡校验 + flush 剩余缓冲区
    if chapter_full_text_for_check:
        _check_bracket_balance("".join(chapter_full_text_for_check), current_chapter)
    flush_buffer()

    return chunks


def clean_batch_files(
    input_dir: str,
    output_file: str,
    min_chars: int = 800,
    max_chars: int = 1500,
):
    """
    批量清洗入口——接收一个【目录】，遍历目录下所有 .txt 文件。
    目录里哪怕只有一个文件也完全没问题，直接把整理好的原文单独放进这个
    目录（比如 ./脂砚斋评红楼梦/红楼梦_干净正文.txt）即可，不需要额外处理。
    """
    if not os.path.exists(input_dir):
        print(f"❌ 找不到目录: {input_dir}")
        return []
    if not os.path.isdir(input_dir):
        print(f"❌ {input_dir} 不是一个目录。如果你想直接清洗单个文件，"
              f"请把这个 txt 放进一个文件夹里，再把文件夹路径传进来。")
        return []

    files = sorted(f for f in os.listdir(input_dir) if f.endswith(".txt"))
    if not files:
        print(f"⚠️ {input_dir} 下没有找到任何 .txt 文件")
        return []

    all_chunks = []
    for filename in files:
        filepath = os.path.join(input_dir, filename)
        print(f"正在清洗文件: {filename}...")
        raw_text, encoding_used = _read_file_auto_encoding(filepath)
        print(f"  （识别编码: {encoding_used}）")
        chunks = clean_single_text(raw_text, min_chars=min_chars, max_chars=max_chars)
        all_chunks.extend(chunks)
        print(f"  -> 本文件生成 {len(chunks)} 个段落块")

    for idx, chunk in enumerate(all_chunks, start=1):
        chunk["segment_id"] = idx

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    unique_chapters = len({c["chapter"] for c in all_chunks})
    print(f"✅ 清洗完成！共处理 {len(files)} 个文件，生成 {len(all_chunks)} 个段落块，"
          f"覆盖 {unique_chapters} 个回目/单元。")
    return all_chunks


if __name__ == "__main__":
    clean_batch_files("./脂砚斋评红楼梦", "./processed_data/01_cleaned_segments.json")
