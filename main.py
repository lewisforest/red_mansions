# -*- coding: utf-8 -*-
"""
main.py
红楼梦时间线分析流水线总控脚本：
    01 清洗与脂批分离 -> 02 LLM抽取与人物校准 ->
    03 人物关系网络（从02结果统计推理）-> 04 时间线推理（从02结果+segment顺序推理）

各阶段脚本文件名以数字开头（如 01_cleaner.py），不是合法的 Python
import 标识符，因此用 importlib 按文件路径动态加载，而不是 import 语句。

用法：
    python main.py                       # 从头跑完整四阶段（各阶段内部自带断点续跑）
    python main.py --from 2              # 假设01已经跑过，从第2阶段开始
    python main.py --only 3              # 只跑第3阶段（人物关系网络）
    python main.py --input-dir ./脂砚斋评红楼梦 --model gemma3:12b
"""

import argparse
import importlib.util
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "processed_data")


def _load_module(filename: str):
    """按文件路径动态加载模块（用于 01_xxx.py 这类数字开头的文件名）。
    加载后注册进 sys.modules，这样模块内部的
    `from character_alias import ...` 之类的相对 import 才能正常解析
    （character_alias.py 是普通合法模块名，可以被 import）。"""
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到脚本文件: {path}")
    module_name = filename[:-3].replace("-", "_")  # 去掉 .py 后缀
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def stage_01_clean(input_dir: str):
    m = _load_module("01_cleaner.py")
    out = os.path.join(DATA_DIR, "01_cleaned_segments.json")
    m.clean_batch_files(input_dir, out)
    return out


def stage_02_extract(model_name: str):
    m = _load_module("02_pipeline.py")
    inp = os.path.join(DATA_DIR, "01_cleaned_segments.json")
    out = os.path.join(DATA_DIR, "02_llm_extractions.json")
    m.run_pipeline(input_file=inp, output_file=out, model_name=model_name)
    return out


def stage_03_network():
    m = _load_module("03_character_network.py")
    inp = os.path.join(DATA_DIR, "02_llm_extractions.json")
    out = os.path.join(DATA_DIR, "03_character_network.json")
    return m.build_and_save_network(input_file=inp, output_file=out)


def stage_04_timeline():
    m = _load_module("04_timeline_aligner.py")
    inp = os.path.join(DATA_DIR, "02_llm_extractions.json")
    out = os.path.join(DATA_DIR, "04_timeline.json")
    return m.align_and_save_timeline(input_file=inp, output_file=out)


STAGE_LABELS = {
    1: "清洗与脂批分离 (01)",
    2: "LLM抽取与人物校准 (02)",
    3: "人物关系网络推理 (03)",
    4: "时间线推理 (04)",
}


def run_stage(stage_id: int, args):
    if stage_id == 1:
        return stage_01_clean(args.input_dir)
    if stage_id == 2:
        return stage_02_extract(args.model_name)
    if stage_id == 3:
        return stage_03_network()
    if stage_id == 4:
        return stage_04_timeline()
    raise ValueError(f"未知阶段: {stage_id}")


def main():
    parser = argparse.ArgumentParser(description="红楼梦时间线分析流水线总控")
    parser.add_argument("--from", dest="from_stage", type=int, default=1,
                        choices=[1, 2, 3, 4], help="从第几阶段开始（默认1）")
    parser.add_argument("--to", dest="to_stage", type=int, default=4,
                        choices=[1, 2, 3, 4], help="跑到第几阶段结束（默认4）")
    parser.add_argument("--only", dest="only_stage", type=int, default=None,
                        choices=[1, 2, 3, 4], help="只跑单个阶段（覆盖 --from/--to）")
    parser.add_argument("--input-dir", dest="input_dir", default="./脂砚斋评红楼梦",
                        help="01阶段：原始 txt 文件所在目录")
    parser.add_argument("--model", dest="model_name", default="gemma3:12b",
                        help="02阶段：Ollama 模型名")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    stages_to_run = [args.only_stage] if args.only_stage else list(range(args.from_stage, args.to_stage + 1))

    for stage_id in stages_to_run:
        print(f"\n{'=' * 60}\n▶ 阶段 {stage_id}：{STAGE_LABELS[stage_id]}\n{'=' * 60}")
        run_stage(stage_id, args)

    print("\n🎉 流水线执行完毕。")


if __name__ == "__main__":
    main()
