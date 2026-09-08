# -*- coding: utf-8 -*-
"""《红楼梦》06：章节时间线求解器

输入：
    ./processed_data/05_clean_facts.json
    ./processed_data/05_age_relationship_network.json
    ./processed_data/05_time_patches.json

输出：
    ./processed_data/06_chronology_solution.json
    ./processed_data/06_chronology_solution.md

职责：
    1. clean facts 提供原始年龄锚点；
    2. 05_age_relationship_network 提供人物年龄关系和由 patch 补出的年龄点；
    3. 05_time_patches 提供事件之间的时间跨度；
    4. 用这些约束求解“时间节点”的相对顺序和跨度；
    5. 把人物年龄关系扩展到同一时间点，形成“章节 × 人物年龄”；
    6. 不丢弃 clean facts 中不能进入主时间轴的 PAST / 未标记年龄事实，单独保存；
    7. 不硬编码具体人物年龄或章节跨度。

重要规则：
    - PRESENT 才参与主时间线年龄传播和人物跨时间年龄增长；
    - PAST 不参与主时间传播，但必须保留；
    - temporal_anchor 为 None 的年龄事实不强行改成 PRESENT，但必须保留；
    - patch 是“事件 -> 事件”的时间跨度，不直接等于“整章 -> 整章”的跨度；
    - 人物年龄关系只负责在已有时间点上扩展人物年龄，不负责凭空制造章节时间；
    - 没有可靠连接的时间节点保持 None，不强行拼接。
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

FACTS_JSON_PATH = "./processed_data/05_clean_facts.json"
AGE_NETWORK_PATH = "./processed_data/05_age_relationship_network.json"
TIME_PATCHES_PATH = "./processed_data/05_time_patches.json"
MANUAL_JSON_PATH = "./processed_data/04_manual.json"

OUTPUT_JSON = "./processed_data/06_chronology_solution.json"
OUTPUT_MD = "./processed_data/06_chronology_solution.md"


class ChronologySolver:
    def __init__(
        self,
        facts_path: str = FACTS_JSON_PATH,
        age_network_path: str = AGE_NETWORK_PATH,
        patches_path: str = TIME_PATCHES_PATH,
        manual_path: str = MANUAL_JSON_PATH,
    ) -> None:
        self.facts_path = facts_path
        self.age_network_path = age_network_path
        self.patches_path = patches_path
        self.manual_path = manual_path

        self.facts: List[Dict[str, Any]] = []
        self.age_network: Dict[str, Any] = {}
        self.patches: List[Dict[str, Any]] = []
        self.manual_reviews: Dict[str, Any] = {}
        self.manual_relations_by_chapter: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        self.person_aliases: Dict[str, str] = {
            "甄士隐之女英莲": "香菱",
            "英莲": "香菱",
        }

        self.chapter_order: List[str] = []
        self.chapter_to_segments: Dict[str, List[int]] = defaultdict(list)
        self.segment_to_chapter: Dict[int, str] = {}
        self.node_chapter: Dict[str, str] = {}

        # 主时间轴年龄点：来自 05 的 age_points（这些点已经包含 patch 推导年龄）
        self.age_points: List[Dict[str, Any]] = []
        self.points_by_node: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.points_by_subject: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # clean facts 中所有年龄事实（包含 PAST / None anchor），只用于信息保全和章节展示
        self.all_clean_age_facts: List[Dict[str, Any]] = []

        # 年龄关系网络
        self.age_edges: List[Dict[str, Any]] = []
        self.age_adjacency: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = defaultdict(list)

        # patch 事件节点
        self.patch_events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # 时间约束：T(to) - T(from) = span_years
        self.time_constraints: List[Dict[str, Any]] = []

        # node -> relative time
        self.node_time: Dict[str, Optional[int]] = {}
        self.components: List[Dict[str, Any]] = []

        self.conflicts: List[Dict[str, Any]] = []

    # ==================================================================
    # IO / 基础
    # ==================================================================

    @staticmethod
    def load_json(path: str, default: Any = None) -> Any:
        if not os.path.exists(path):
            if default is not None:
                return default
            raise FileNotFoundError(f"文件不存在：{path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_json(path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def save_text(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def normalize_person(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        name = str(name).strip()
        return self.person_aliases.get(name, name) or None

    @staticmethod
    def is_age_fact(fact: Dict[str, Any]) -> bool:
        return fact.get("clue_type") in {"absolute", "relative_diff"} or fact.get("fact_type") == "age"

    @staticmethod
    def get_age(fact: Dict[str, Any]) -> Optional[int]:
        value = fact.get("age_value")
        if value is None:
            value = fact.get("value")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def point_node(point: Dict[str, Any]) -> str:
        return str(point.get("context_id") or f"POINT::{point.get('subject')}::{point.get('segment_id')}")

    @staticmethod
    def _chinese_chapter_number(text: str) -> int:
        """从“第十一回”这类章节标题中提取回次，供章节统一排序。"""
        import re

        m = re.search(r"第([零〇一二两三四五六七八九十百千万]+)回", str(text))
        if not m:
            return 10**9

        chars = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
            "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }
        s = m.group(1)
        if s.isdigit():
            return int(s)

        total = 0
        section = 0
        unit = 1
        for ch in reversed(s):
            if ch in chars:
                section += chars[ch] * unit
            elif ch == "十":
                unit = 10
                if section == 0:
                    section = 1
            elif ch == "百":
                unit = 100
                if section == 0:
                    section = 1
            elif ch == "千":
                unit = 1000
                if section == 0:
                    section = 1
            elif ch == "万":
                unit = 10000
        return section if section else total

    @staticmethod
    def node_sort_key(node: str) -> Tuple[int, int, str]:
        if node.startswith("SEGMENT::"):
            try:
                return (0, int(node.split("::", 1)[1]), node)
            except Exception:
                return (0, 10**9, node)
        if node.startswith("PATCH::"):
            return (1, 10**9, node)
        return (2, 10**9, node)

    # ==================================================================
    # 读取
    # ==================================================================

    def load_data(self) -> None:
        self.facts = self.load_json(self.facts_path, default=[])
        self.age_network = self.load_json(self.age_network_path, default={})
        self.patches = self.load_json(self.patches_path, default=[])
        manual = self.load_json(self.manual_path, default={})
        if isinstance(manual, dict):
            self.manual_reviews = manual.get("reviews", {})
            if not isinstance(self.manual_reviews, dict):
                self.manual_reviews = {}
        else:
            self.manual_reviews = {}

        if not isinstance(self.facts, list):
            raise ValueError("05_clean_facts.json 必须是 list")
        if not isinstance(self.age_network, dict):
            raise ValueError("05_age_relationship_network.json 必须是 object")
        if not isinstance(self.patches, list):
            raise ValueError("05_time_patches.json 必须是 list")

    @staticmethod
    def parse_chapter_number(chapter: Optional[str]) -> Optional[int]:
        """从章节题目提取“第X回”的数字，统一作为章节排序依据。"""
        if not chapter:
            return None
        m = re.search(r"第([零〇一二两三四五六七八九十百千万]+)回", str(chapter))
        if not m:
            return None

        s = m.group(1)
        digits = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
            "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }
        if s.isdigit():
            return int(s)

        total = 0
        section = 0
        unit = 1
        for ch in reversed(s):
            if ch in digits:
                section += digits[ch] * unit
            elif ch == "十":
                if section == 0:
                    section = 1
                total += section * 10 if unit == 1 else section * unit
                section = 0
                unit = 1
            elif ch == "百":
                if section == 0:
                    section = 1
                unit = 100
            elif ch == "千":
                if section == 0:
                    section = 1
                unit = 1000
            elif ch == "万":
                if section == 0:
                    section = 1
                unit = 10000
        if "十" not in s and "百" not in s and "千" not in s and "万" not in s:
            return sum(digits.get(ch, 0) * (10 ** i) for i, ch in enumerate(reversed(s)))

        # 更稳妥的通用中文数字解析：按单位累加。
        value = 0
        section = 0
        unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
        for ch in s:
            if ch in digits:
                section = digits[ch]
            elif ch in unit_map:
                unit_value = unit_map[ch]
                if section == 0:
                    section = 1
                value += section * unit_value
                section = 0
        return value + section

    def build_chapter_index(self) -> None:
        first_segment: Dict[str, int] = {}
        chapters: set[str] = set()
        self.chapter_order = []
        self.chapter_to_segments.clear()
        self.segment_to_chapter.clear()

        for fact in self.facts:
            sid = fact.get("segment_id")
            chapter = fact.get("chapter")
            if not isinstance(sid, int) or not chapter:
                continue
            chapter = str(chapter)
            chapters.add(chapter)
            self.segment_to_chapter[sid] = chapter
            self.chapter_to_segments[chapter].append(sid)
            first_segment[chapter] = min(first_segment.get(chapter, 10**9), sid)

        for patch in self.patches:
            if not isinstance(patch, dict):
                continue
            for key in ("from_chapter", "to_chapter"):
                chapter = patch.get(key)
                if chapter:
                    chapters.add(str(chapter))

        # 04_manual 中的关系也可以提供 clean facts 没覆盖的章节。
        for review in self.manual_reviews.values():
            if not isinstance(review, dict):
                continue
            chapter = review.get("chapter")
            if chapter:
                chapters.add(str(chapter))

        for chapter in self.chapter_to_segments:
            self.chapter_to_segments[chapter] = sorted(set(self.chapter_to_segments[chapter]))

        self.chapter_order = sorted(
            chapters,
            key=lambda chapter: (
                self.parse_chapter_number(chapter) if self.parse_chapter_number(chapter) is not None else 10**9,
                first_segment.get(chapter, 10**9),
                chapter,
            ),
        )

    # ==================================================================
    # 05 年龄知识层
    # ==================================================================

    def load_age_points(self) -> None:
        self.age_points.clear()
        self.points_by_node.clear()
        self.points_by_subject.clear()

        raw = self.age_network.get("age_points", [])
        if not isinstance(raw, list):
            return

        for raw_point in raw:
            if not isinstance(raw_point, dict):
                continue

            subject = self.normalize_person(raw_point.get("subject"))
            age = raw_point.get("age")
            chapter = raw_point.get("chapter")
            if not subject or age is None or not chapter:
                continue

            try:
                age = int(age)
            except (TypeError, ValueError):
                continue

            point = dict(raw_point)
            point["subject"] = subject
            point["age"] = age
            point["chapter"] = str(chapter)

            node = self.point_node(point)
            self.node_chapter[node] = str(point["chapter"])
            self.age_points.append(point)
            self.points_by_node[node].append(point)
            self.points_by_subject[subject].append(point)

        for subject in self.points_by_subject:
            self.points_by_subject[subject].sort(
                key=lambda p: (
                    p.get("segment_id") if isinstance(p.get("segment_id"), int) else 10**9,
                    p.get("patch_index") if isinstance(p.get("patch_index"), int) else 10**9,
                    str(p.get("context_id") or ""),
                )
            )

    def load_all_clean_age_facts(self) -> None:
        """保留全部 clean 年龄信息。

        PAST / temporal_anchor=None 不进入主时间传播，但不能从最终结果消失。
        """
        self.all_clean_age_facts = []
        for fact in self.facts:
            if not self.is_age_fact(fact):
                continue
            subject = self.normalize_person(fact.get("subject"))
            age = self.get_age(fact)
            chapter = fact.get("chapter")
            sid = fact.get("segment_id")
            if not subject or age is None or not chapter or not isinstance(sid, int):
                continue
            self.all_clean_age_facts.append({
                "subject": subject,
                "age": age,
                "chapter": str(chapter),
                "segment_id": sid,
                "temporal_anchor": fact.get("temporal_anchor"),
                "clue_type": fact.get("clue_type"),
                "source_key": fact.get("source_key"),
                "matched_text": fact.get("matched_text"),
                "sentence": fact.get("sentence"),
            })

    def load_age_relationships(self) -> None:
        self.age_edges.clear()
        self.age_adjacency.clear()

        for level in ("direct_edges", "inferred_edges"):
            raw_edges = self.age_network.get(level, [])
            if not isinstance(raw_edges, list):
                continue

            for raw in raw_edges:
                if not isinstance(raw, dict):
                    continue
                a = self.normalize_person(raw.get("a"))
                b = self.normalize_person(raw.get("b"))
                diff = raw.get("difference")
                if not a or not b or diff is None:
                    continue
                try:
                    diff = int(diff)
                except (TypeError, ValueError):
                    continue

                edge = dict(raw)
                edge["a"] = a
                edge["b"] = b
                edge["difference"] = diff
                self.age_edges.append(edge)

                # Age(a) - Age(b) = diff
                # 已知 a -> b：b = a - diff
                self.age_adjacency[a].append((b, -diff, edge))
                # 已知 b -> a：a = b + diff
                self.age_adjacency[b].append((a, diff, edge))

    # ==================================================================
    # patch 事件：直接使用 05 已经生成的 patch_events
    # ==================================================================

    def load_patch_events(self) -> None:
        self.patch_events.clear()
        raw = self.age_network.get("patch_events", [])
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                subject = self.normalize_person(item.get("subject"))
                if not subject:
                    continue
                event = dict(item)
                event["subject"] = subject
                node = str(event.get("context_id") or event.get("event_id") or "")
                if node and event.get("chapter"):
                    self.node_chapter[node] = str(event["chapter"])
                self.patch_events[subject].append(event)

        for subject in self.patch_events:
            self.patch_events[subject].sort(
                key=lambda e: (
                    e.get("patch_index") if isinstance(e.get("patch_index"), int) else -1,
                    str(e.get("event_id") or ""),
                )
            )

    # ==================================================================
    # 时间约束
    # ==================================================================

    def add_constraint(self, constraint: Dict[str, Any]) -> None:
        if not constraint.get("from_node") or not constraint.get("to_node"):
            return
        try:
            constraint["span_years"] = int(constraint["span_years"])
        except (TypeError, ValueError, KeyError):
            return
        key = (
            constraint["from_node"],
            constraint["to_node"],
            constraint["span_years"],
            constraint.get("source"),
            constraint.get("subject"),
            constraint.get("patch_index"),
        )
        existing = {
            (
                c.get("from_node"), c.get("to_node"), c.get("span_years"),
                c.get("source"), c.get("subject"), c.get("patch_index"),
            )
            for c in self.time_constraints
        }
        if key not in existing:
            self.time_constraints.append(constraint)

    def build_clean_age_growth_constraints(self) -> None:
        """
        用 05 已经形成的全部 PRESENT 年龄点计算人物跨时间年龄变化。

        这里特意不再只看 source == 05_clean_facts：
            clean 年龄点 + patch 派生年龄点
        必须一起参与。

        这一步是把“人工补充的年龄”真正接入时间求解的关键。

        例如：
            贾宝玉：第二回 patch = 7岁
            第二十五回 clean = 13岁

        得到：
            T(第二十五回) - T(第二回) = 6
        """
        by_subject: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in self.age_points:
            # 05 的 patch 年龄点都明确标成 PRESENT；clean 也应是 PRESENT。
            source = str(p.get("source") or "")
            if source == "05_clean_facts":
                if p.get("temporal_anchor") not in {"PRESENT", None}:
                    continue
            elif source == "05_time_patches_derived":
                # patch 明确给这个人物的年龄，属于真实年龄锚点；
                # 例如香菱 3 -> 5 -> 12 -> 13，贾蓉 16 -> 18。
                if p.get("temporal_anchor") not in {"PRESENT", None}:
                    continue
            elif source.startswith("05_age_relationship_inferred_at_patch"):
                # 关系网络推导出的“别人年龄”只能用于当前时间点的年龄扩展，
                # 不能再反过来制造人物自身的跨时间增长约束，否则会把“林黛玉5岁”
                # 与“贾宝玉7岁 => 林黛玉6岁”的近似关系误算成同章经过1年。
                continue
            else:
                continue

            if p.get("age") is None or not p.get("chapter"):
                continue
            by_subject[str(p["subject"])].append(p)

        chapter_index = {chapter: i for i, chapter in enumerate(self.chapter_order)}

        def point_sort_key(p: Dict[str, Any]) -> Tuple[int, int, int, str]:
            chapter_rank = chapter_index.get(str(p.get("chapter")), 10**9)
            sid = p.get("segment_id") if isinstance(p.get("segment_id"), int) else 10**9
            patch_idx = p.get("patch_index") if isinstance(p.get("patch_index"), int) else 10**9
            context = str(p.get("context_id") or "")
            return chapter_rank, sid, patch_idx, context

        for subject, points in by_subject.items():
            ordered = sorted(points, key=point_sort_key)

            # 相同 context 下的重复年龄点只保留一条。不同年龄必须报冲突。
            dedup: List[Dict[str, Any]] = []
            seen_context: Dict[str, Dict[str, Any]] = {}
            for p in ordered:
                context = str(p.get("context_id") or "")
                if context and context in seen_context:
                    old = seen_context[context]
                    if int(old["age"]) != int(p["age"]):
                        self.conflicts.append({
                            "type": "same_subject_same_context_age_conflict",
                            "subject": subject,
                            "context_id": context,
                            "ages": sorted({int(old["age"]), int(p["age"])}),
                            "sources": [old.get("source_key"), p.get("source_key")],
                        })
                    continue
                if context:
                    seen_context[context] = p
                dedup.append(p)

            for previous, current in zip(dedup, dedup[1:]):
                # 同一年龄点/同一人物重复观察不产生新的时间跨度。
                if self.point_node(previous) == self.point_node(current):
                    continue

                delta = int(current["age"]) - int(previous["age"])

                if delta < 0:
                    self.conflicts.append({
                        "type": "main_timeline_age_decrease",
                        "subject": subject,
                        "from_chapter": previous["chapter"],
                        "to_chapter": current["chapter"],
                        "from_age": previous["age"],
                        "to_age": current["age"],
                        "age_delta": delta,
                        "from_context": previous.get("context_id"),
                        "to_context": current.get("context_id"),
                    })
                    continue

                self.add_constraint({
                    "type": "character_age_growth",
                    "from_node": self.point_node(previous),
                    "to_node": self.point_node(current),
                    "span_years": delta,
                    "subject": subject,
                    "from_chapter": previous["chapter"],
                    "to_chapter": current["chapter"],
                    "from_segment": previous.get("segment_id"),
                    "to_segment": current.get("segment_id"),
                    "from_context": previous.get("context_id"),
                    "to_context": current.get("context_id"),
                    "evidence": [x for x in [previous.get("source_key"), current.get("source_key")] if x],
                })

    def build_patch_constraints(self) -> None:
        """patch 作为事件->事件的时间跨度。"""
        for subject, events in self.patch_events.items():
            for previous, current in zip(events, events[1:]):
                span = current.get("span_years_from_previous")
                if span is None:
                    # 如果 05 event 没有携带，则从原始 patch 找。
                    pidx = current.get("patch_index")
                    if isinstance(pidx, int) and 0 <= pidx < len(self.patches):
                        span = self.patches[pidx].get("span_years")
                if span is None:
                    continue
                self.add_constraint({
                    "type": "time_patch_event",
                    "from_node": str(previous.get("context_id") or previous.get("event_id")),
                    "to_node": str(current.get("context_id") or current.get("event_id")),
                    "span_years": int(span),
                    "subject": subject,
                    "from_chapter": previous.get("chapter"),
                    "to_chapter": current.get("chapter"),
                    "patch_index": current.get("patch_index"),
                    "event": current.get("event"),
                })

    def align_patch_events_to_clean_points(self) -> None:
        """只在“同人物 + 同章节 + 同年龄”时把 patch event 与 clean segment 零跨度对齐。"""
        clean_index: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = defaultdict(list)
        for p in self.age_points:
            if p.get("source") != "05_clean_facts":
                continue
            sid = p.get("segment_id")
            if not isinstance(sid, int):
                continue
            clean_index[(str(p["subject"]), str(p["chapter"]), int(p["age"]))].append(p)

        for subject, events in self.patch_events.items():
            for event in events:
                age = event.get("age")
                chapter = event.get("chapter")
                if age is None or not chapter:
                    continue
                matches = clean_index.get((subject, str(chapter), int(age)), [])
                if len(matches) == 1:
                    segment_node = self.point_node(matches[0])
                    event_node = str(event.get("context_id") or event.get("event_id"))
                    self.add_constraint({
                        "type": "patch_clean_alignment",
                        "from_node": segment_node,
                        "to_node": event_node,
                        "span_years": 0,
                        "subject": subject,
                        "from_chapter": matches[0]["chapter"],
                        "to_chapter": chapter,
                        "from_segment": matches[0]["segment_id"],
                        "patch_index": event.get("patch_index"),
                    })
                elif len(matches) > 1:
                    self.conflicts.append({
                        "type": "patch_clean_alignment_ambiguous",
                        "subject": subject,
                        "chapter": chapter,
                        "age": age,
                        "patch_event": event,
                        "matches": [m.get("source_key") for m in matches],
                    })

    # ==================================================================
    # 时间图求解
    # ==================================================================

    def solve_time_graph(self) -> None:
        graph: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = defaultdict(list)
        nodes: set[str] = set()

        for c in self.time_constraints:
            a = c["from_node"]
            b = c["to_node"]
            span = int(c["span_years"])
            graph[a].append((b, span, c))
            graph[b].append((a, -span, c))
            nodes.add(a)
            nodes.add(b)

        # 所有主时间年龄点即使没有约束，也必须保留
        for node in self.points_by_node:
            nodes.add(node)

        self.node_time = {node: None for node in nodes}
        self.components = []
        visited: set[str] = set()

        chapter_rank = {chapter: i for i, chapter in enumerate(self.chapter_order)}

        def temporal_node_key(node: str) -> Tuple[int, int, str]:
            chapter = self.node_chapter.get(node, "")
            rank = chapter_rank.get(chapter, 10**9)
            # 同一章节内保持：segment/clean 在前，patch event 在后。
            kind = 0 if node.startswith("SEGMENT::") else 1
            return rank, kind, node

        for start in sorted(nodes, key=temporal_node_key):
            if start in visited:
                continue
            if start not in graph:
                visited.add(start)
                continue

            distance: Dict[str, int] = {start: 0}
            queue = deque([start])
            visited.add(start)
            component: List[str] = []

            while queue:
                current = queue.popleft()
                component.append(current)
                for nxt, delta, constraint in graph[current]:
                    proposed = distance[current] + delta
                    if nxt not in distance:
                        distance[nxt] = proposed
                        visited.add(nxt)
                        queue.append(nxt)
                    elif distance[nxt] != proposed:
                        self.conflicts.append({
                            "type": "time_constraint_cycle_conflict",
                            "current_node": current,
                            "next_node": nxt,
                            "existing_time": distance[nxt],
                            "new_time": proposed,
                            "constraint": constraint,
                        })

            anchor = min(component, key=temporal_node_key)
            offset = distance[anchor]
            normalized = {node: value - offset for node, value in distance.items()}

            for node, value in normalized.items():
                self.node_time[node] = value

            self.components.append({
                "anchor_node": anchor,
                "nodes": sorted(component, key=temporal_node_key),
                "relative_years": normalized,
            })

    # ==================================================================
    # 章节时间点
    # ==================================================================

    def build_chapter_time_index(self) -> Dict[str, List[int]]:
        """把已经求解出的 segment / patch event 时间整理到章节。"""
        chapter_times: Dict[str, set[int]] = defaultdict(set)

        for point in self.age_points:
            node = self.point_node(point)
            t = self.node_time.get(node)
            if t is None:
                continue
            chapter = str(point["chapter"])
            chapter_times[chapter].add(int(t))

        for subject, events in self.patch_events.items():
            for event in events:
                node = str(event.get("context_id") or event.get("event_id"))
                t = self.node_time.get(node)
                if t is None or not event.get("chapter"):
                    continue
                chapter_times[str(event["chapter"])].add(int(t))

        return {k: sorted(v) for k, v in chapter_times.items()}

    def get_chapter_clean_age_records(self, chapter: str) -> List[Dict[str, Any]]:
        records = []
        for fact in self.all_clean_age_facts:
            if fact["chapter"] == chapter:
                records.append(dict(fact))
        return records

    # ==================================================================
    # 年龄关系扩展
    # ==================================================================

    def expand_related_ages(self, known: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
        """从当前时间点的已知年龄沿 05 年龄关系网络扩展人物。

        已知年龄优先：
            clean / patch 的已知年龄 > 网络推导年龄。
        如果网络推导与已知年龄冲突，保留已知值，并记录 alternative_age。
        """
        result: Dict[str, Dict[str, Any]] = {}
        resolved: Dict[str, int] = {}
        queue = deque()

        for person, age in known.items():
            person = self.normalize_person(person) or person
            resolved[person] = int(age)
            result[person] = {
                "age": int(age),
                "source": "observed_or_patch",
            }
            queue.append(person)

        while queue:
            current = queue.popleft()
            current_age = resolved[current]

            for nxt, delta, edge in self.age_adjacency.get(current, []):
                proposed = current_age + delta

                if nxt not in resolved:
                    resolved[nxt] = proposed
                    result[nxt] = {
                        "age": proposed,
                        "source": "inferred_from_age_relationship",
                        "derived_from": {
                            "from_person": current,
                            "relationship": f"Age({edge['a']}) - Age({edge['b']}) = {edge['difference']}",
                            "edge_source": edge.get("source"),
                            "segment_id": edge.get("segment_id"),
                            "context_id": edge.get("context_id"),
                        },
                    }
                    queue.append(nxt)
                    continue

                if resolved[nxt] != proposed:
                    # 已知事实优先，不覆盖；保留网络推导值供研究检查。
                    result.setdefault(nxt, {"age": resolved[nxt], "source": "observed_or_patch"})
                    alternatives = result[nxt].setdefault("alternative_ages", [])
                    candidate = {
                        "age": proposed,
                        "source": "inferred_from_age_relationship",
                        "derived_from": {
                            "from_person": current,
                            "relationship": f"Age({edge['a']}) - Age({edge['b']}) = {edge['difference']}",
                            "edge_source": edge.get("source"),
                            "segment_id": edge.get("segment_id"),
                            "context_id": edge.get("context_id"),
                        },
                    }
                    if not any(a.get("age") == proposed for a in alternatives):
                        alternatives.append(candidate)

        return result

    # ==================================================================
    # 04_manual 人物关系
    # ==================================================================

    ACCEPTED_RELATION_REASONS = {
        "救回机器遗漏的正则物理线索",
        "人工认可机器判断",
        "修正机器误判，人工重新录入有效实体与关系",
    }

    def load_manual_relations(self) -> None:
        """
        从 04_manual.json 提取与章节绑定的人物关系。

        只接受明确属于人工有效关系的记录：
            - 救回机器遗漏的正则物理线索
            - 人工认可机器判断
            - 修正机器误判，人工重新录入有效实体与关系

        confirmed -> 使用 machine
        overridden -> 使用 final 覆盖 machine
        其他状态 -> 不进入章节关系结果。
        """
        self.manual_relations_by_chapter.clear()

        for key, review in self.manual_reviews.items():
            if not isinstance(review, dict):
                continue
            if review.get("item_type") != "kinship":
                continue

            reason = str(review.get("reason") or "").strip()
            if reason not in self.ACCEPTED_RELATION_REASONS:
                continue

            status = str(review.get("status") or "").strip().lower()
            if status == "confirmed":
                resolved = review.get("machine")
            elif status == "overridden":
                machine = review.get("machine") or {}
                final = review.get("final") or {}
                resolved = dict(machine) if isinstance(machine, dict) else {}
                if isinstance(final, dict):
                    resolved.update(final)
            else:
                continue

            if not isinstance(resolved, dict):
                continue

            is_valid = resolved.get("is_valid")
            relation = resolved.get("relation")
            person_a = resolved.get("person_a")
            person_b = resolved.get("person_b")
            chapter = review.get("chapter")

            if is_valid is False:
                continue
            if not relation or not person_a or not person_b or not chapter:
                continue

            chapter = str(chapter)
            record = {
                "relation": str(relation),
                "person_a": self.normalize_person(person_a) or str(person_a),
                "person_b": self.normalize_person(person_b) or str(person_b),
                "chapter": chapter,
                "chapter_number": self.parse_chapter_number(chapter),
                "segment_id": review.get("segment_id"),
                "candidate_index": review.get("candidate_index"),
                "status": status,
                "reason": reason,
                "source": "04_manual",
                "review_key": str(key),
            }
            self.manual_relations_by_chapter[chapter].append(record)

        # 同一章节去重。
        for chapter, relations in self.manual_relations_by_chapter.items():
            seen = set()
            unique = []
            for item in relations:
                signature = (
                    item["relation"], item["person_a"], item["person_b"],
                    item.get("segment_id"), item.get("candidate_index"),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                unique.append(item)
            unique.sort(key=lambda x: (
                x.get("segment_id") if isinstance(x.get("segment_id"), int) else 10**9,
                str(x.get("person_a") or ""),
                str(x.get("person_b") or ""),
            ))
            self.manual_relations_by_chapter[chapter] = unique

    def get_chapter_relations(self, chapter: str) -> List[Dict[str, Any]]:
        return list(self.manual_relations_by_chapter.get(chapter, []))

    # ==================================================================
    # 最终章节 × 人物年龄
    # ==================================================================

    def build_chapter_timeline(self) -> List[Dict[str, Any]]:
        """
        每回只输出一行：

            回次 | 章节 | 人物年龄 | 人物关系

        同一章节内部可能存在多个时间点（例如香菱第一回 3岁 -> 5岁），
        这里不显示内部 relative_year，而是把同一人物在本回的多个年龄
        合并成一个年龄序列：

            香菱 3→5岁

        章节排序只依据标题中的“第X回”数字。
        """
        chapter_times = self.build_chapter_time_index()
        rows: List[Dict[str, Any]] = []

        for chapter in self.chapter_order:
            # ----------------------------------------------------------
            # 本章所有已求解的内部时间点
            # ----------------------------------------------------------
            times = chapter_times.get(chapter, [])

            # ----------------------------------------------------------
            # 人物年龄：按人物收集本章所有内部时间点的年龄
            # ----------------------------------------------------------
            person_age_points: Dict[str, List[Tuple[Optional[int], int, Dict[str, Any]]]] = defaultdict(list)

            for point in self.age_points:
                if point.get("chapter") != chapter:
                    continue

                node = self.point_node(point)
                point_time = self.node_time.get(node)

                person = str(point["subject"])
                age = int(point["age"])

                # 允许同一人物同一时间点重复出现相同年龄，但去掉完全重复。
                signature = (point_time, age, point.get("source_key"))
                existing_sig = {
                    (t, a, e.get("source_key"))
                    for t, a, e in person_age_points[person]
                }
                if signature not in existing_sig:
                    person_age_points[person].append(
                        (point_time, age, point)
                    )

            # ----------------------------------------------------------
            # patch 事件年龄也纳入本章人物年龄
            # ----------------------------------------------------------
            for subject, events in self.patch_events.items():
                for event in events:
                    if event.get("chapter") != chapter:
                        continue
                    age = event.get("age")
                    if age is None:
                        continue

                    node = str(
                        event.get("context_id")
                        or event.get("event_id")
                    )
                    event_time = self.node_time.get(node)

                    record = {
                        "source": "05_time_patches",
                        "patch_index": event.get("patch_index"),
                        "event_id": event.get("event_id"),
                    }
                    signature = (event_time, int(age), record.get("event_id"))
                    existing_sig = {
                        (t, a, e.get("event_id"))
                        for t, a, e in person_age_points[subject]
                    }
                    if signature not in existing_sig:
                        person_age_points[subject].append(
                            (event_time, int(age), record)
                        )

            # ----------------------------------------------------------
            # 先把“本章直接观测/patch人物”作为种子，
            # 再按本章相关年龄网络扩展人物。
            # 对于同一人物出现多个年龄，按内部时间顺序去重。
            # ----------------------------------------------------------
            characters: Dict[str, Dict[str, Any]] = {}
            seed_ages: Dict[str, int] = {}

            for person, records in person_age_points.items():
                records.sort(
                    key=lambda x: (
                        x[0] if x[0] is not None else 10**9,
                        x[1],
                    )
                )

                ages: List[int] = []
                for _, age, _ in records:
                    if age not in ages:
                        ages.append(age)

                if not ages:
                    continue

                # 本章如果有多个内部时间点，使用最后一个已知年龄作为
                #“相关人物扩展”的当前年龄，避免同一人物被同一章早期事件
                # 的旧年龄重复扩展。
                seed_ages[person] = ages[-1]

                data: Dict[str, Any] = {
                    "age": ages[-1],
                    "source": "observed_or_patch",
                }
                if len(ages) > 1:
                    data["age_sequence"] = ages
                    data["age_display"] = "→".join(f"{a}岁" for a in ages)
                else:
                    data["age_display"] = f"{ages[0]}岁"
                characters[person] = data

            # 网络扩展：对本章的每一个年龄种子分别传播，然后合并结果。
            # 不把完全没有本章种子的其他人物凭空放进来。
            if seed_ages:
                expanded = self.expand_related_ages(seed_ages)
                for person, data in expanded.items():
                    if person in characters:
                        # 已有本章直接年龄时绝不被关系推导覆盖。
                        continue
                    characters[person] = data
                    characters[person]["age_display"] = f"{data['age']}岁"

            # ----------------------------------------------------------
            # 关系：04_manual 中已按 reason 筛选的人工有效关系
            # ----------------------------------------------------------
            relations = self.get_chapter_relations(chapter)

            rows.append({
                "chapter_number": self.parse_chapter_number(chapter),
                "chapter": chapter,
                "characters": characters,
                "relations": relations,
            })

        # --------------------------------------------------------------
        # 严格按章节标题里的第X回排序
        # --------------------------------------------------------------
        rows.sort(key=lambda x: (
            x.get("chapter_number")
            if x.get("chapter_number") is not None
            else 10**9,
            str(x.get("chapter") or ""),
        ))

        return rows

    def build_non_main_age_records(self) -> List[Dict[str, Any]]:
        """输出 PAST / 未标记年龄，防止研究数据在 06 阶段消失。"""
        result = []
        for rec in self.all_clean_age_facts:
            if rec.get("temporal_anchor") == "PRESENT":
                continue
            result.append(rec)
        return result

    # ==================================================================
    # 输出
    # ==================================================================

    def solve(self) -> Dict[str, Any]:
        self.load_data()
        self.build_chapter_index()
        self.load_age_points()
        self.load_all_clean_age_facts()
        self.load_age_relationships()
        self.load_patch_events()
        self.load_manual_relations()

        # 顺序非常重要：先建立人物年龄增长与 patch 事件跨度，再进行对齐和求解。
        self.time_constraints = []
        self.build_clean_age_growth_constraints()
        self.build_patch_constraints()
        self.align_patch_events_to_clean_points()
        self.solve_time_graph()

        chapter_timeline = self.build_chapter_timeline()

        return {
            "schema_version": "06.chronology.5",
            "rules": {
                "main_timeline_age": "只使用 PRESENT；PAST/None 不参与主时间传播",
                "age_relationship": "直接使用 05_age_relationship_network 的年龄关系",
                "patch": "patch 是事件->事件跨度，不等于整章->整章跨度",
                "alignment": "patch 事件仅在同人物+同章节+同年龄时与 clean segment 零跨度对齐",
                "age_expansion": "章节时间点上的已知人物通过年龄关系网络扩展相关人物",
                "known_age_priority": "直接观察/patch 年龄优先于关系网络推导年龄；冲突值保留为 alternative_ages",
                "chapter_sort": "从章节标题正则提取第X回数字后排序，并写入 chapter_number；主阅读表不按 relative_year 排序",
                "manual_relations": "读取 04_manual.json 中指定人工有效关系，并按章节加入输出",
                "unanchored": "没有时间约束连接的年龄仍然输出；主阅读表不显示 relative_year。",
            },
            "chapter_timeline": chapter_timeline,
            "non_main_timeline_age_records": self.build_non_main_age_records(),
            "node_time": self.node_time,
            "time_constraints": self.time_constraints,
            "components": self.components,
            "conflicts": self.conflicts,
        }

    def save_outputs(self) -> Dict[str, Any]:
        result = self.solve()
        self.save_json(OUTPUT_JSON, result)

        lines = [
            "# 《红楼梦》章节—人物年龄与人物关系",
            "",
            "| 回次 | 章节 | 人物年龄 | 人物关系 |",
            "|---:|---|---|---|",
        ]
        for row in result["chapter_timeline"]:
            chars = "；".join(
                f"{name} {data.get('age_display', str(data.get('age', ''))) + ('岁' if not str(data.get('age_display', '')).endswith('岁') else '')}"
                for name, data in row["characters"].items()
            )
            relations_text = "；".join(
                f"{r['person_a']}—{r['relation']}—{r['person_b']}"
                for r in row.get("relations", [])
            )
            lines.append(
                f"| {row.get('chapter_number', '')} | {row['chapter']} | {chars} | {relations_text} |"
            )

        lines.extend(["", "## 主时间轴外的年龄事实", ""])
        for item in result["non_main_timeline_age_records"]:
            lines.append(
                f"- {item['chapter']} / {item['subject']}：{item['age']}岁"
                f"（{item.get('temporal_anchor') or '未标记'}，{item.get('source_key') or ''}）"
            )

        lines.extend(["", "## 冲突", ""])
        if result["conflicts"]:
            lines.extend(
                f"- {json.dumps(c, ensure_ascii=False)}"
                for c in result["conflicts"]
            )
        else:
            lines.append("无")

        self.save_text(OUTPUT_MD, "\n".join(lines) + "\n")
        return result


if __name__ == "__main__":
    solver = ChronologySolver()
    result = solver.save_outputs()
    print(f"06 完成：{OUTPUT_JSON}")
    print(f"章节时间线行数: {len(result['chapter_timeline'])}")
    print(f"时间节点数: {len(result['node_time'])}")
    print(f"时间约束数: {len(result['time_constraints'])}")
    print(f"主时间轴外年龄事实: {len(result['non_main_timeline_age_records'])}")
    print(f"冲突数: {len(result['conflicts'])}")
