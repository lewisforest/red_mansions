# 红楼梦时间线分析流水线

执行顺序：

01_cleaner.py
  -> 01_cleaned_segments.json
02_prescan_anchors.py
  -> 02_prescan_anchors.json
03_kinship_prescan.py
  -> 03_kinship_candidates.json
04_fused_corrected.py
  -> 04_fused_corrected.json
05_timeline_builder.py
  -> 05_timeline.json

统一入口：

```bash
python main.py --raw-dir ./脂砚斋评红楼梦 --work-dir ./processed_data
```

04 的两个重要修正：
1. 候选不再按 sentence 去重；同一句可保留多个年龄候选。
2. run() 支持传入各阶段文件路径，方便 main.py 编排。

05 的设计：
- segment_id / chapter_index 是文本出现位置，不是故事年代。
- LLM 纠错后的年龄事实形成同一人物的年龄顺序约束。
- PAST / PRESENT / FUTURE 只作为时间状态约束。
- 保留 evidence、constraints、contradictions、unresolved，方便审计。
- 不自动生成未经文本支持的公历年份。

```
项目/
├── 01_cleaner.py
├── 02_prescan_anchors.py
├── 03_kinship_prescan.py
├── 04_fused_corrected.py
├── 05_timeline_builder.py
├── character_alias.py
├── main.py
└── 脂砚斋评红楼梦/
```
