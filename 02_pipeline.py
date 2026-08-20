# -*- coding: utf-8 -*-
"""
02_pipeline.py
批量时间线推理流水线。

本版新增（针对"越跑越慢"问题）：
1. --reset-every：每完成 N 条，强制卸载一次模型（keep_alive=0）再等它重新加载。
   如果减速是显存碎片化/内存累积导致的，这能定期"清空重来"；如果减速是硬件
   热降频导致的，强制卸载之间的等待也顺带给了硬件一点喘息时间。
2. 速度趋势监测：把最初 10 条的平均耗时当作基线，之后每保存一次就对比最近
   10 条的平均耗时，如果慢了超过 1.5 倍，直接打印预警，提示你去检查温度/
   显存占用，而不是等跑完 1000 分钟才发现不对劲。
3. offset_years 的计算换成按新的四态 year_transition 累加：
   SAME_YEAR +0 / NEXT_YEAR +1 / YEARS_LATER +estimated_year_gap（缺省给 3）/
   META_BACKGROUND 不参与线性年份推进，只打一个 is_meta_narrative 标记。
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm_analyzer import analyze_timeline_segment, force_unload_model


def _atomic_save(results: list, output_json: str):
    os.makedirs(os.path.dirname(output_json) or '.', exist_ok=True)
    tmp_path = output_json + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, output_json)


def _compute_offset_years(results: list):
    """按新的四态 year_transition 依次累加年份"""
    current_year = 0
    for res in results:
        if not res or res.get("error"):
            continue
        yt = res.get("year_transition", "SAME_YEAR")
        if yt == "NEXT_YEAR":
            current_year += 1
        elif yt == "YEARS_LATER":
            gap = res.get("estimated_year_gap") or 0
            if gap <= 0:
                gap = 3  # 模型没给出具体估计时的保守默认值
            current_year += gap
        # SAME_YEAR：不变；META_BACKGROUND：不参与线性年份推进
        res["offset_years"] = current_year
        res["is_meta_narrative"] = (yt == "META_BACKGROUND")


def run_timeline_pipeline(
    input_json: str,
    output_json: str,
    model_name: str = "gemma3:12b",
    workers: int = 1,
    save_every: int = 5,
    reset_every: int = 30,
    slowdown_warn_ratio: float = 1.5,
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
                      f"历史进度无法直接复用，将重新开始。")
        except Exception:
            print("⚠️ 读取历史断点文件失败，将从头开始推理。")

    tasks_to_run = [
        (idx, item) for idx, item in enumerate(raw_items)
        if results[idx] is None or "error" in results[idx]
    ]

    if not tasks_to_run:
        print("✅ 所有数据已推理完成，无需重复运行。")
    else:
        print(f"🚀 开始推理剩余 {len(tasks_to_run)} 条任务，并发线程数: {workers}"
              f"，每 {reset_every} 条自动强制重载一次模型")
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
        recent_times = []  # 最近若干条的耗时，用于趋势监测
        baseline_avg = None
        last_tick = start_time

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {executor.submit(worker, idx, item): idx for idx, item in tasks_to_run}

            for future in as_completed(future_map):
                idx, res = future.result()
                results[idx] = res
                completed += 1

                now = time.time()
                recent_times.append(now - last_tick)
                last_tick = now

                if completed % save_every == 0 or completed == len(tasks_to_run):
                    _atomic_save(results, output_json)
                    total_done = processed_count + completed
                    elapsed = time.time() - start_time
                    avg_per_item = elapsed / completed
                    remaining = len(tasks_to_run) - completed
                    eta_min = remaining * avg_per_item / 60

                    window = recent_times[-10:]
                    recent_avg = sum(window) / len(window)
                    if baseline_avg is None and completed >= 10:
                        baseline_avg = recent_avg

                    print(f"进度: {total_done}/{total_len} ({total_done / total_len * 100:.1f}%) "
                          f"| 累计平均 {avg_per_item:.1f}s/条 | 最近10条平均 {recent_avg:.1f}s/条 "
                          f"| 预计剩余 {eta_min:.1f} 分钟 [已自动保存]")

                    if baseline_avg and recent_avg > baseline_avg * slowdown_warn_ratio:
                        print(f"    🐢 速度预警：最近 10 条平均耗时（{recent_avg:.1f}s）已是初始基线"
                              f"（{baseline_avg:.1f}s）的 {recent_avg / baseline_avg:.1f} 倍，"
                              f"疑似硬件降频或显存/内存资源紧张，建议检查温度与显存占用"
                              f"（如 nvidia-smi），或缩短 --reset-every。")

                # 定期强制卸载重载模型，缓解长时间连续推理可能导致的显存碎片化/降速
                if reset_every > 0 and completed % reset_every == 0 and completed != len(tasks_to_run):
                    print(f"  🔁 已完成 {completed} 条，强制卸载模型并等待重新加载...")
                    force_unload_model(model_name)
                    time.sleep(2.0)  # 给卸载/下次加载留一点缓冲时间

    _compute_offset_years(results)
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
        reset_every=30,
    )
