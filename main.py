# -*- coding: utf-8 -*-
"""
main.py
统一入口，依次调度：
  1. 01_cleaner.py   —— 原始 TXT 无损清洗为结构化段落 JSON（大块切分）
  2. 02_pipeline.py  —— 调用本地 LLM 做时间线推理（带断点续传、原子写入）
  3. 03_aggregate.py —— 按章节聚合成最终时间线（JSON + Markdown）

用法示例：
  python main.py                                   # 全流程，默认参数
  python main.py --workers 2                       # 2 个并发线程（需配合 Ollama 的
                                                     # OLLAMA_NUM_PARALLEL 环境变量才有意义）
  python main.py --skip-clean                       # 已经清洗过，直接跑推理+聚合
  python main.py --skip-clean --skip-pipeline       # 只重新聚合
  python main.py --model qwen2.5:14b                # 换模型
  python main.py --min-chars 1000 --max-chars 2000  # 调大分段块，进一步减少调用次数
"""

import argparse
import importlib.util
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _import_from_file(module_name: str, file_name: str):
    """按文件名动态导入模块（因为 01/02/03 开头的文件名不是合法的 import 标识符）"""
    file_path = os.path.join(BASE_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(description="《红楼梦》时间线梳理 流水线")

    parser.add_argument("--input-dir", default="./脂砚斋评红楼梦", help="原始 TXT 所在目录")
    parser.add_argument("--processed-json", default="./processed_data/red_mansions_structured.json",
                         help="清洗后段落 JSON 的路径")
    parser.add_argument("--timeline-json", default="./output/timeline_analysis_result.json",
                         help="逐段推理结果 JSON 的路径")
    parser.add_argument("--summary-json", default="./output/timeline_summary.json",
                         help="按章节聚合后的结构化结果路径")
    parser.add_argument("--summary-md", default="./output/timeline_summary.md",
                         help="按章节聚合后的可读 Markdown 路径")

    parser.add_argument("--model", default="gemma3:12b", help="Ollama 模型名")
    parser.add_argument("--workers", type=int, default=1,
                         help="并发调用模型的线程数（需配合 Ollama 的 OLLAMA_NUM_PARALLEL 才有真实加速）")
    parser.add_argument("--min-chars", type=int, default=800, help="清洗阶段段落块最小字符数")
    parser.add_argument("--max-chars", type=int, default=1500, help="清洗阶段段落块最大字符数")
    parser.add_argument("--save-every", type=int, default=5, help="推理阶段每完成多少条保存一次进度")
    parser.add_argument("--reset-every", type=int, default=30,
                         help="每完成多少条强制卸载并重新加载一次模型，缓解长时间连续推理的降速；设为 0 关闭")

    parser.add_argument("--skip-clean", action="store_true", help="跳过清洗步骤，直接用已有的 processed-json")
    parser.add_argument("--skip-pipeline", action="store_true", help="跳过推理步骤，直接用已有的 timeline-json 做聚合")
    parser.add_argument("--skip-aggregate", action="store_true", help="跳过聚合步骤")

    return parser.parse_args()


def main():
    args = parse_args()

    cleaner = _import_from_file("cleaner_module", "01_cleaner.py")
    pipeline = _import_from_file("pipeline_module", "02_pipeline.py")
    aggregate = _import_from_file("aggregate_module", "03_aggregate.py")

    # ---------- 步骤 1：清洗 ----------
    if not args.skip_clean:
        print("\n========== 步骤 1/3：清洗原始数据 ==========")
        cleaner.clean_batch_files(
            input_dir=args.input_dir,
            output_file=args.processed_json,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
        )
    else:
        print("\n⏭️  跳过步骤 1（清洗），使用已有文件:", args.processed_json)
        if not os.path.exists(args.processed_json):
            print(f"❌ 找不到 {args.processed_json}，无法继续，请去掉 --skip-clean 重新运行。")
            sys.exit(1)

    # ---------- 步骤 2：LLM 推理 ----------
    if not args.skip_pipeline:
        print("\n========== 步骤 2/3：调用模型做时间线推理 ==========")
        pipeline.run_timeline_pipeline(
            input_json=args.processed_json,
            output_json=args.timeline_json,
            model_name=args.model,
            workers=args.workers,
            save_every=args.save_every,
            reset_every=args.reset_every,
        )
    else:
        print("\n⏭️  跳过步骤 2（推理），使用已有文件:", args.timeline_json)
        if not os.path.exists(args.timeline_json):
            print(f"❌ 找不到 {args.timeline_json}，无法继续，请去掉 --skip-pipeline 重新运行。")
            sys.exit(1)

    # ---------- 步骤 3：聚合 ----------
    if not args.skip_aggregate:
        print("\n========== 步骤 3/3：按章节聚合时间线 ==========")
        aggregate.aggregate_timeline(
            input_json=args.timeline_json,
            output_json=args.summary_json,
            output_md=args.summary_md,
        )
    else:
        print("\n⏭️  跳过步骤 3（聚合）。")

    print("\n🎉 全部流程结束。")


if __name__ == "__main__":
    main()
