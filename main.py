# -*- coding: utf-8 -*-
"""
main.py
统一入口，依次调度五个步骤：
  1. 01_cleaner.py            —— 原始 TXT 清洗为结构化段落 JSON（含 segment_id）
  2. 02_pipeline.py           —— LLM 原位抽取（人物/年龄/时间词/事件，不注入背景知识）
  3. 03_character_network.py —— 纯 Python，从抽取结果自动统计人物共现网络
  4. 04_timeline_aligner.py   —— 纯 Python，锚点关键词匹配 + 时间词增量推理，对齐时间轴
  5. 05_report_generator.py  —— 生成最终可读报告（人物履历 + 同纪年事件交集 + 关系网络摘要）

用法示例：
  python main.py                              # 全流程
  python main.py --skip-clean                 # 已清洗过，从第2步开始
  python main.py --skip-clean --skip-pipeline # 已经跑完LLM抽取，从第3步开始
  python main.py --model qwen2.5:14b          # 换模型
"""

import argparse
import importlib.util
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _import_from_file(module_name: str, file_name: str):
    file_path = os.path.join(BASE_DIR, file_name)
    if not os.path.exists(file_path):
        print(f"❌ 找不到脚本文件: {file_path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(description="《红楼梦》时间线梳理 流水线（五步版）")

    parser.add_argument("--input-dir", default="./脂砚斋评红楼梦", help="原始 TXT 所在目录")
    parser.add_argument("--cleaned-json", default="./processed_data/01_cleaned_segments.json")
    parser.add_argument("--extraction-json", default="./processed_data/02_llm_extractions.json")
    parser.add_argument("--network-json", default="./processed_data/03_character_network.json")
    parser.add_argument("--timeline-json", default="./processed_data/04_final_timeline.json")
    parser.add_argument("--report-md", default="./output/红楼梦人物履历与事件交集年表.md")

    parser.add_argument("--model", default="gemma3:12b", help="Ollama 模型名")
    parser.add_argument("--min-chars", type=int, default=800, help="清洗阶段段落块最小字符数")
    parser.add_argument("--max-chars", type=int, default=1500, help="清洗阶段段落块最大字符数")
    parser.add_argument("--min-anchor-hits", type=int, default=2,
                         help="判定命中一个锚点事件所需的最少关键词命中数")

    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--skip-network", action="store_true")
    parser.add_argument("--skip-align", action="store_true")
    parser.add_argument("--skip-report", action="store_true")

    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs("./processed_data", exist_ok=True)
    os.makedirs("./output", exist_ok=True)

    cleaner = _import_from_file("cleaner_mod", "01_cleaner.py")
    pipeline = _import_from_file("pipeline_mod", "02_pipeline.py")
    network_builder = _import_from_file("network_mod", "03_character_network.py")
    aligner = _import_from_file("aligner_mod", "04_timeline_aligner.py")
    reporter = _import_from_file("reporter_mod", "05_report_generator.py")

    # ---------- 步骤 1：清洗 ----------
    if not args.skip_clean:
        print("\n========== 步骤 1/5：清洗原始数据 ==========")
        cleaner.clean_batch_files(
            input_dir=args.input_dir,
            output_file=args.cleaned_json,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
        )
    else:
        print("\n⏭️  跳过步骤 1，使用已有文件:", args.cleaned_json)
        if not os.path.exists(args.cleaned_json):
            print(f"❌ 找不到 {args.cleaned_json}，请去掉 --skip-clean 重新运行。")
            sys.exit(1)

    # ---------- 步骤 2：LLM 原位抽取 ----------
    if not args.skip_pipeline:
        print("\n========== 步骤 2/5：LLM 原位抽取（人物/年龄/时间词/事件） ==========")
        pipeline.run_pipeline(
            input_file=args.cleaned_json,
            output_file=args.extraction_json,
            model_name=args.model,
        )
    else:
        print("\n⏭️  跳过步骤 2，使用已有文件:", args.extraction_json)
        if not os.path.exists(args.extraction_json):
            print(f"❌ 找不到 {args.extraction_json}，请去掉 --skip-pipeline 重新运行。")
            sys.exit(1)

    # ---------- 步骤 3：人物关系网络 ----------
    if not args.skip_network:
        print("\n========== 步骤 3/5：自动构建人物关系网络 ==========")
        network_builder.build_character_network(
            input_file=args.extraction_json,
            output_file=args.network_json,
        )
    else:
        print("\n⏭️  跳过步骤 3。")

    # ---------- 步骤 4：时间轴对齐 ----------
    if not args.skip_align:
        print("\n========== 步骤 4/5：锚点校准 + 时间词推理，对齐时间轴 ==========")
        aligner.align_and_clean_timeline(
            input_file=args.extraction_json,
            output_file=args.timeline_json,
            min_anchor_hits=args.min_anchor_hits,
        )
    else:
        print("\n⏭️  跳过步骤 4。")
        if not os.path.exists(args.timeline_json):
            print(f"❌ 找不到 {args.timeline_json}，请去掉 --skip-align 重新运行。")
            sys.exit(1)

    # ---------- 步骤 5：生成报告 ----------
    if not args.skip_report:
        print("\n========== 步骤 5/5：生成高可读性人物履历与事件交集报告 ==========")
        reporter.generate_biography_and_intersection_report(
            input_file=args.timeline_json,
            output_file=args.report_md,
            network_file=args.network_json,
        )
    else:
        print("\n⏭️  跳过步骤 5。")

    print("\n🎉 全部流程结束。")


if __name__ == "__main__":
    main()
