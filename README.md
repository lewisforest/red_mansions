# red_mansions
爬梳红楼梦的时间线
```
my_redmansions_project/
├── raw_data/                    # 存放你原始的 txt 文本文件夹
│   ├── 01_10回.txt
│   └── 11_20回.txt
├── processed_data/              # 存放清洗后的 intermediate JSON
│   └── red_mansions_structured.json
├── output/                      # 存放最终大模型推导出的时间线结果
│   └── timeline_analysis_result.json
├── 01_cleaner.py                # 脚本 1：文本清洗与格式化
├── 02_llm_analyzer.py           # 脚本 2：Ollama API 封装与推理引擎
└── 03_run_pipeline.py           # 脚本 3：主控脚本（带断点续传保存）
```
