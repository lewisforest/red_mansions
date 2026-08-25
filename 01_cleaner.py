# -*- coding: utf-8 -*-
"""01_cleaner.py - 结构化无损清洗版（带批注插记与只读上文继承）

改动要点：
1. 【括号安全闭合】：仅在括号配对（count('〔') == count('〕')）且处于句子结尾时切块。
2. 【脂批位置插记】：正文中将 〔...〕 替换为 [脂批1]，zhi_evidence 输出为字典 {"脂批1": "..."}。
3. 【只读上文继承】：输出新增 context_prefix 字段（取上一块末尾 180 字），供 02 阶段指代消解。
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
CANDIDATE_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5"]


def _read_file_auto_encoding(filepath: str):
  """自动探测编码读取"""
  with open(filepath, "rb") as f:
    raw_bytes = f.read()
  for enc in CANDIDATE_ENCODINGS:
    try:
      return raw_bytes.decode(enc), enc
    except (UnicodeDecodeError, LookupError):
      continue
  return raw_bytes.decode("utf-8", errors="ignore"), "utf-8(ignore)"


def _check_bracket_balance(text: str, chapter_label: str):
  """校验整章括号配对情况"""
  open_count = text.count("〔")
  close_count = text.count("〕")
  if open_count != close_count:
    print(
        f"  ⚠️ 括号不平衡警告 [{chapter_label}]：〔 出现 {open_count} 次，"
        f"〕 出现 {close_count} 次，相差 {abs(open_count - close_count)}。"
    )


def _parse_and_anchor_zhi(whole_text: str):
  """剔除批注并在正文中留下 [脂批1] 锚点，返回纯化正文与批注映射字典"""
  zhi_dict = {}
  counter = 1

  def replace_func(match):
    nonlocal counter
    content = match.group(1).strip()
    content_clean = re.sub(r"\s+", " ", content)  # 抹平批注内部多余回车
    if not content_clean:
      return ""

    anchor_tag = f"[脂批{counter}]"
    zhi_dict[f"脂批{counter}"] = content_clean
    counter += 1
    return anchor_tag

  # 替换批注为锚点标记
  narrative_with_anchors = ZHIPY_PATTERN.sub(replace_func, whole_text)

  # 清理空行
  clean_lines = [
      l.strip() for l in narrative_with_anchors.splitlines() if l.strip()
  ]
  final_narrative = "\n".join(clean_lines)

  return final_narrative, zhi_dict


def clean_single_text(
    raw_text: str,
    min_chars: int = 800,
    max_chars: int = 1500,
    context_prefix_len: int = 180,
) -> list:
  lines = raw_text.splitlines()
  chunks = []
  current_chapter = "前言/凡例"

  buffer_raw_lines = []
  chapter_full_text_for_check = []
  last_chunk_tail = ""  # 记录上一块结尾文本，作为下块的 context_prefix

  def flush_buffer():
    nonlocal buffer_raw_lines, last_chunk_tail
    if not buffer_raw_lines:
      return

    whole_text = "\n".join(buffer_raw_lines)
    clean_narrative, zhi_dict = _parse_and_anchor_zhi(whole_text)

    if clean_narrative or zhi_dict:
      chunks.append({
          "chapter": current_chapter,
          "context_prefix": last_chunk_tail,  # 只读背景（辅助消解代词）
          "narrative": clean_narrative,  # 主体提取文本
          "zhi_evidence": zhi_dict,  # 锚点对应表
      })

      # 更新上一块的末尾文本（取最后 context_prefix_len 个字）
      if len(clean_narrative) > context_prefix_len:
        last_chunk_tail = "..." + clean_narrative[-context_prefix_len:]
      else:
        last_chunk_tail = clean_narrative

    buffer_raw_lines = []

  for line in lines:
    line_str = line.strip()
    if not line_str or line_str.startswith("=" * 10):
      continue

    # 遇到章节标题
    if CHAPTER_PATTERN.match(line_str):
      if chapter_full_text_for_check:
        _check_bracket_balance(
            "".join(chapter_full_text_for_check), current_chapter
        )
      chapter_full_text_for_check = []

      flush_buffer()
      current_chapter = line_str
      last_chunk_tail = ""  # 跨章节时重置上下文
      continue

    chapter_full_text_for_check.append(line_str)
    buffer_raw_lines.append(line_str)

    current_buffer_str = "\n".join(buffer_raw_lines)

    # 估算净正文长度（除去批注字符）
    approx_len = len(re.sub(r"〔.*?〕", "", current_buffer_str, flags=re.DOTALL))

    # 安全切块的三个关键判断：
    # 1. 达到最小长度要求
    # 2. 必须以标点符号结尾
    # 3. 关键：缓冲区内括号必须【绝对闭合】（〔 和 〕 数量相等）
    is_balanced = current_buffer_str.count("〔") == current_buffer_str.count("〕")
    ends_with_sentence = line_str[-1] in SENTENCE_END_CHARS

    reached_min_and_sentence_end = (
        approx_len >= min_chars and ends_with_sentence
    )
    reached_max = approx_len >= max_chars

    if is_balanced and (reached_max or reached_min_and_sentence_end):
      flush_buffer()

  if chapter_full_text_for_check:
    _check_bracket_balance(
        "".join(chapter_full_text_for_check), current_chapter
    )
  flush_buffer()

  return chunks


def clean_batch_files(
    input_dir: str,
    output_file: str,
    min_chars: int = 800,
    max_chars: int = 1500,
):
  if not os.path.exists(input_dir) or not os.path.isdir(input_dir):
    print(f"❌ 找不到有效目录: {input_dir}")
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
    chunks = clean_single_text(
        raw_text, min_chars=min_chars, max_chars=max_chars
    )
    all_chunks.extend(chunks)
    print(f"  -> 本文件生成 {len(chunks)} 个段落块")

  for idx, chunk in enumerate(all_chunks, start=1):
    chunk["segment_id"] = idx

  os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
  with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False, indent=2)

  unique_chapters = len({c["chapter"] for c in all_chunks})
  print(
      f"✅ 清洗完成！共处理 {len(files)} 个文件，生成 {len(all_chunks)} 个段落块，"
      f"覆盖 {unique_chapters} 个回目/单元。"
  )
  return all_chunks


if __name__ == "__main__":
  clean_batch_files(
      "./脂砚斋评红楼梦", "./processed_data/01_cleaned_segments.json"
  )
