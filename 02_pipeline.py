# -*- coding: utf-8 -*-
"""
02_pipeline.py
批量时间线推理流水线：
1. 与 main.py 的参数接口对接 (workers, save_every 等)
2. 支持断点续传（读取已有结果并跳过已完成/未出错的项）
3. 多线程并发请求本地 LLM
4. 原子写入进度文件，避免中途崩溃损坏 JSON

【关于并发速度的重要提醒】
workers > 1 能不能真正提速，取决于 Ollama 服务端是否允许并行处理请求。
默认情况下 Ollama 通常仍是单队列串行处理，线程池并发只是在客户端排队等待，
不会有实际加速。如果你的机器显存/内存充足，可以在启动 Ollama 前设置：
    export OLLAMA_NUM_PARALLEL=2
    export OLLAMA_MAX_LOADED_MODELS=1
再重启 ollama serve，然后把 --workers 设为 2 左右，才能看到真正的并发加速。
盲目调高 workers 而不设置这个环境变量，通常不会更快，还可能因为请求排队导致
超时增多。
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm_analyzer import analyze_timeline_segment


def _atomic_save(results: list, output_json: str):
    os.makedirs(os.path.dirname(output_json) or '.', exist_ok=True)
    tmp_path = output_json + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, output_json)


def run_timeline_pipeline(
    input_json: str,
    output_json: str,
    model_name: str = "gemma3:12b",
    workers: int = 1,
    save_every: int = 5,
):
    if not os.path.exists(input_json):
        print(f"❌ 找不到输入文件: {input_json}")
        sys.exit(1)

    with open(input_json, 'r', encoding='utf-8') as f:
        raw_items = json.load(f)

    total_len = len(raw_items)
    print(f"📦 读取到 {total_len} 条数据段落。")
    if total_len == 0:
        print("⚠️ 输入为空，请检查清洗步骤的输出。")
        return

    # 断点续传检查：只有当历史结果长度与当前输入完全一致时才复用
    # （如果你改了 min-chars/max-chars 重新清洗过，段落数会变，历史进度对不上号，
    #  这时候不能强行复用索引，只能提示重新跑）
    results = [None] * total_len
    processed_count = 0

    if os.path.exists(output_json):
        try:
            with open(output_json, 'r', encoding='utf-8') as f:
                old_results = json.load(f)
            if isinstance(old_results, list) and len(old_results) == total_len:
                results = old_results
                processed_count = sum(1 for item in results if item and "error" not in item)
                print(f"🔄 检测到历史断点文件，已完成 {processed_count}/{total_len} 条，跳过已处理项。")
            else:
                print(f"⚠️ 历史结果条数（{len(old_results)}）与当前输入条数（{total_len}）不一致，"
                      f"可能是清洗参数变了，历史进度无法直接复用，将重新开始。")
        except Exception:
            print("⚠️ 读取历史断点文件失败，将从头开始推理。")

    # 筛选未完成的任务（None 或 上次出错的都重新跑）
    tasks_to_run = [
        (idx, item) for idx, item in enumerate(raw_items)
        if results[idx] is None or "error" in results[idx]
    ]

    if not tasks_to_run:
        print("✅ 所有数据已推理完成，无需重复运行。")
    else:
        print(f"🚀 开始推理剩余 {len(tasks_to_run)} 条任务，并发线程数: {workers}")
        start_time = time.time()

        def worker(index, item):
            res = analyze_timeline_segment(
                chapter=item.get("chapter", "未知章节"),
                narrative=item.get("narrative", ""),
                zhi_evidence=item.get("zhi_evidence", []),
                model_name=model_name,
            )
            return index, res

        completed = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {executor.submit(worker, idx, item): idx for idx, item in tasks_to_run}

            for future in as_completed(future_map):
                idx, res = future.result()
                results[idx] = res
                completed += 1

                if completed % save_every == 0 or completed == len(tasks_to_run):
                    _atomic_save(results, output_json)
                    total_done = processed_count + completed
                    elapsed = time.time() - start_time
                    avg_per_item = elapsed / completed
                    remaining = len(tasks_to_run) - completed
                    eta_min = remaining * avg_per_item / 60
                    print(f"进度: {total_done}/{total_len} ({total_done / total_len * 100:.1f}%) "
                          f"| 平均 {avg_per_item:.1f}s/条 | 预计剩余 {eta_min:.1f} 分钟 [已自动保存]")

    # 后置全局年份累加推算（基于 year_transition 顺序推导）
    print("⏳ 正在结合年份跨越标记 (year_transition) 计算全局累加年份...")
    current_year = 0
    for res in results:
        if res:
            if res.get("year_transition") == "NEXT_YEAR":
                current_year += 1
            res["offset_years"] = current_year

    _atomic_save(results, output_json)

    error_count = sum(1 for r in results if r and r.get("error"))
    print(f"✅ LLM 时间线推理完成，已写入: {output_json}")
    if error_count:
        print(f"⚠️ 其中 {error_count} 条推理失败（已标记 error 字段），重新运行本脚本会自动只重跑这些失败项。")


if __name__ == "__main__":
    run_timeline_pipeline(
        input_json="./processed_data/red_mansions_structured.json",
        output_json="./output/timeline_analysis_result.json",
        model_name="gemma3:12b",
        workers=1,
        save_every=5,
    )
