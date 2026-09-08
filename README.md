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
04_manual_review.py
  -> 04_manual.json
05_extract_and_clean.py
  -> 05_clean_facts.json
05_timeline_solver.py
  -> 05_age_relationship_network.json
  -> 05_time_patches.json
06_chronology_solver.py
  -> 06_chronology_solution.json
  -> 06_chronology_solution.md


统一入口：

```bash
python main.py --raw-dir ./脂砚斋评红楼梦 --work-dir ./processed_data
```

04 的功能：
调用语言模型将02_prescan_anchors.json和03_kinship_candidates.json的信息缝合起来，这两个json文档一个提取的是年龄线索，一个提取的是人物关系线索，脚本负责从字典缝合同一章回的内容，语言模型负责校验正则表达式提取的信息是否正确，工作由04_fused_corrected.py完成。机器校验的结果再经过人工确认由04_manual_review.py完成。

05 的功能：
首先将人工校验后的信息整理成干净的字典，由05_extract_and_clean.py完成。
由于语言模型无法完成跨章回的语义分析，篇幅过长，只有通过人工补充。例如第一回甄英莲出场的时候3岁，几岁的时候被拐的没有交代，直到第四回才通过贾雨村和门子的对话引出她是5岁被拐走的，被养了七八年拿出来卖，名字被改成香菱。还有一些正则表达式漏失的信息，例如冷子兴的讲述，旁白的介绍等，这些信息作为补丁手动添加，作为人物年龄分析的支撑材料，为了推演时间的演化，首先用人物的年龄差来固定人物之间的关系，生成05_age_relationship_network.json，由05_timeline_solver.py完成，附带生成补丁文件05_time_patches.json。

06的功能：
将人物和章回对齐，在每个章回中出现的人物年龄作为锚点，再把有年龄差的相关人物的年龄推算出来，同时把每个章节里有人际关系的人物列出来，形成06_chronology_solution.json和具备可读性的06_chronology_solution.md

```
项目/
├── 01_cleaner.py
├── 02_prescan_anchors.py
├── 03_kinship_prescan.py
├── 04_fused_corrected.py
├── 04_manual_review.py
├── 05_extract_and_clean.py
├── 05_timeline_solver.py
├── 06_chronology_solver.py
├── character_alias.py
└── 脂砚斋评红楼梦/
```
