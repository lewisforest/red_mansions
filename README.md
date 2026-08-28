# red_mansions
爬梳红楼梦的时间线，不再硬编码特定事件对应的人物年龄，而是通过语言模型分析事件对应的时间。但是这个代码问题非常多，尽管时间进程精确到天，但是并没有绑定标志性人物和标志性事件。如果没有gpu，cpu运行太慢，可以运行02_pipeline.py一段时间后运行test_partial_pipeline.py看02_llm_extractions.json的推理结果是不是对。
```
project_root/
├── 脂砚斋评红楼梦/                  # 原始文本/脂批 TXT 目录
├── processed_data/                  # 中间 JSON 数据目录
│   ├── 01_cleaned_segments.json     # 1. 结构化清洗与切分段落
│   ├── 02_llm_extractions.json      # 2. LLM 分析每个切片里的时间地点人物事件
│   ├── 03_character_network.json    # 3. 人物关系网络图谱
│   └── 04_final_timeline.json       # 4. 时间轴挂载与对齐结果
├── character_alias.py               # 🛠️ 共享模块：统一别名映射表与噪声剔除逻辑
├── network_graph.py                 # 🛠️ 共享模块：全局事件锚点地图与时间跨度词表
├── 01_cleaner.py                    # 步骤 1：无损数据清洗与分段
├── 02_pipeline.py                    # 步骤 2：LLM 极速原位抽取
├── 03_character_network.py          # 步骤 3：构建人物共现关系网络
├── 04_timeline_aligner.py           # 步骤 4：根据语言模型分析的时间和segment的序号确定时间线
└── main.py                          # 🚀 全流程五步统一调度主控脚本
```
