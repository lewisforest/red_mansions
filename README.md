# red_mansions
爬梳红楼梦的时间线，新版本用了一个干净的脂砚斋批阅红楼梦文本，这样减轻了01_cleaner.py的很多工作负担
```
project_root/
├── 脂砚斋评红楼梦/                  # 原始文本/脂批 TXT 目录
├── processed_data/                  # 中间 JSON 数据目录
│   ├── 01_cleaned_segments.json     # 1. 结构化清洗与切分段落
│   ├── 02_llm_extractions.json      # 2. LLM 原位实体与事件抽取结果
│   ├── 03_character_network.json    # 3. 人物关系网络图谱
│   └── 04_final_timeline.json       # 4. 时间轴挂载与对齐结果
├── output/                          # 最终输出报告目录
│   └── 红楼梦人物履历与事件交集年表.md # 5. 最终生成的 Markdown 可视化报告
├── character_alias.py               # 🛠️ 共享模块：统一别名映射表与噪声剔除逻辑
├── network_graph.py                 # 🛠️ 共享模块：全局事件锚点地图与时间跨度词表
├── 01_cleaner.py                    # 步骤 1：无损数据清洗与分段
├── 02_pipeline.py                    # 步骤 2：LLM 极速原位抽取
├── 03_character_network.py          # 步骤 3：构建人物共现关系网络
├── 04_timeline_aligner.py           # 步骤 4：锚点校准 + 时间词推算对齐
├── 05_report_generator.py           # 步骤 5：生成人物履历与事件交集报告
└── main.py                          # 🚀 全流程五步统一调度主控脚本
```
