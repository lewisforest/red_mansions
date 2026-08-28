# red_mansions
爬梳红楼梦的时间线，不再硬编码任何人物的年龄和情节，从正文抓取与人物年龄、关系相关的内容进行分析，构建人物年龄的演化和人物之间的关系
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
├── 01_cleaner.py                    # 步骤 1：无损数据清洗与分段

```
