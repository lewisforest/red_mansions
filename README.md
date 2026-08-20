# red_mansions
爬梳红楼梦的时间线
```
my_redmansions_project/
├── 脂砚斋评红楼梦/                    # 存放原始的 txt 文本文件夹
│   ├── 01_10回.txt
│   └── 11_20回.txt
├── processed_data/              # 存放清洗后的 intermediate JSON
│   └── red_mansions_structured.json
├── output/                      # 存放最终大模型推导出的时间线结果
│   └── timeline_analysis_result.json
├── 01_cleaner.py                # 脚本 1：文本清洗与格式化
├── llm_analyzer.py              # Ollama API读取清洗后json化的文本，对时间线进行分析
├── network_graph.py             # 建立时刻锚定标志性事件
├── 02_pipeline.py               # 脚本 2：与 main.py 的参数接口对接
├── 03_aggregate.py              # 脚本 3：将逐段推理结果按章节聚合成时间线（JSON + 可读 Markdown）
└── main.py                      # 统一入口，依次调度01-03脚本
```
