# red_mansions
爬梳红楼梦的时间线
```
project_root/
├── 读取基础信息/脂砚斋评红楼梦/    # 原始文本/脂批目录
├── processed_data/                  # 中间过程数据目录
│   ├── 01_cleaned_segments.json     # 1. 清洗分段结果
│   ├── 02_llm_extractions.json      # 2. LLM 极速原位抽取结果
│   ├── 03_character_network.json    # 3. 人物关系网络图谱
│   └── 04_final_timeline.json       # 4. 最终时间轴对齐结果
├── output/                          # 最终输出报告目录
│   └── timeline_summary.md          # 聚合 Markdown 报告
├── 01_cleaner.py                    # 步骤 1：纯 Python 数据清洗
├── 02_pipeline.py                   # 步骤 2：LLM 极速抽取（2-3秒/条）
├── 03_character_network.py          # 步骤 3：纯 Python 构建人物共现网络
├── 04_timeline_aligner.py           # 步骤 4：纯 Python 时间轴挂载对齐
└── main.py                          # 🚀 全流程统一调度主控脚本
```
