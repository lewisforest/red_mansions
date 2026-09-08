# -*- coding: utf-8 -*-
"""05：人物年龄知识层

输入：
    ./processed_data/05_clean_facts.json
    ./processed_data/05_time_patches.json

输出：
    ./processed_data/05_age_relationship_network.json

职责：
    - clean facts 的 PRESENT absolute 年龄 -> 年龄点
    - time patches -> 人物补充年龄点（不计算章节跨度）
    - clean facts 的 PRESENT relative_diff -> 明确年龄差
    - 同一时间上下文的 PRESENT absolute 年龄 -> 年龄差
    - 对年龄关系做闭包，形成可查询的年龄关系地图

注意：
    05 不解决“第几回相隔几年”。
    章节跨度由 06 使用本文件中的年龄点 + patch + clean facts 求解。
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict, deque
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

FACTS_JSON_PATH = "./processed_data/05_clean_facts.json"
DEFAULT_PATCHES_INPUT = "./processed_data/05_time_patches.json"
OUTPUT_AGE_NETWORK = "./processed_data/05_age_relationship_network.json"


class AgeRelationshipSolver:
    def __init__(self) -> None:
        self.person_aliases: Dict[str, str] = {
            "甄士隐之女英莲": "香菱",
            "英莲": "香菱",
        }
        self.facts: List[Dict[str, Any]] = []
        self.patches: List[Dict[str, Any]] = []
        self.age_points: List[Dict[str, Any]] = []
        self.direct_edges: List[Dict[str, Any]] = []
        self.inferred_edges: List[Dict[str, Any]] = []
        self.patch_events: List[Dict[str, Any]] = []
        self.conflicts: List[Dict[str, Any]] = []

    @staticmethod
    def load_json(path: str, default: Any = None) -> Any:
        if not os.path.exists(path):
            if default is not None:
                return default
            raise FileNotFoundError(f"文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_json(path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def normalize_person(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        name = str(name).strip()
        return self.person_aliases.get(name, name) or None

    @staticmethod
    def is_age_fact(fact: Dict[str, Any]) -> bool:
        return (
            fact.get("clue_type") in {"absolute", "relative_diff"}
            or fact.get("fact_type") == "age"
        )

    @classmethod
    def is_present_absolute(cls, fact: Dict[str, Any]) -> bool:
        return (
            cls.is_age_fact(fact)
            and fact.get("clue_type") == "absolute"
            and fact.get("temporal_anchor") == "PRESENT"
        )

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
    def parse_explicit_age(text: Optional[str]) -> Optional[int]:
        """只读取人工 patch 描述中明确出现的 X岁。"""
        if not text:
            return None
        s = str(text)
        m = re.search(r"(\d{1,3})\s*岁", s)
        if m:
            return int(m.group(1))

        digit = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }
        m = re.search(r"([一二两三四五六七八九十]{1,3})\s*岁", s)
        if not m:
            return None
        x = m.group(1)
        if x == "十":
            return 10
        if x.startswith("十"):
            return 10 + digit.get(x[1], 0)
        if x.endswith("十"):
            return digit.get(x[0], 0) * 10
        if "十" in x:
            return digit.get(x[0], 0) * 10 + digit.get(x[-1], 0)
        return digit.get(x)

    def load_data(self) -> None:
        self.facts = self.load_json(FACTS_JSON_PATH, default=[])
        self.patches = self.load_json(DEFAULT_PATCHES_INPUT, default=[])
        if not isinstance(self.facts, list):
            raise ValueError("05_clean_facts.json 必须是 list")
        if not isinstance(self.patches, list):
            raise ValueError("05_time_patches.json 必须是 list")

    # ------------------------------------------------------------------
    # 1. clean facts 年龄点
    # ------------------------------------------------------------------
    def build_clean_age_points(self) -> None:
        self.age_points = []
        for fact in self.facts:
            if not self.is_present_absolute(fact):
                continue
            subject = self.normalize_person(fact.get("subject"))
            age = self.get_age(fact)
            sid = fact.get("segment_id")
            chapter = fact.get("chapter")
            if not subject or age is None or not isinstance(sid, int) or not chapter:
                continue
            self.age_points.append({
                "subject": subject,
                "age": age,
                "chapter": str(chapter),
                "segment_id": sid,
                "context_id": f"SEGMENT::{sid}",
                "source": "05_clean_facts",
                "source_key": fact.get("source_key"),
                "sentence": fact.get("sentence"),
                "matched_text": fact.get("matched_text"),
            })

    def _find_clean_seed(self, subject: str, chapter: str) -> Optional[Dict[str, Any]]:
        candidates = [
            p for p in self.age_points
            if p["subject"] == subject and p["chapter"] == chapter
            and p.get("source") == "05_clean_facts"
        ]
        if not candidates:
            return None
        ages = {p["age"] for p in candidates}
        if len(ages) != 1:
            self.conflicts.append({
                "type": "patch_seed_ambiguous",
                "subject": subject,
                "chapter": chapter,
                "ages": sorted(ages),
            })
            return None
        return candidates[0]

    # ------------------------------------------------------------------
    # 2. patch 补年龄点
    # ------------------------------------------------------------------
    def build_patch_age_points(self) -> None:
        """沿着每个人物的 patch 链传播年龄。

        起点优先使用同章 clean PRESENT 年龄，否则读取 event 中明确出现的年龄。
        patch 的 span_years 只用于推算下一个年龄，不在 05 中解释章节跨度。
        """
        self.patch_events = []
        grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
        for i, patch in enumerate(self.patches):
            if not isinstance(patch, dict):
                continue
            subject = self.normalize_person(patch.get("subject"))
            if subject:
                grouped[subject].append((i, patch))

        for subject, items in grouped.items():
            items.sort(key=lambda x: x[0])
            first_patch = items[0][1]
            first_chapter = str(first_patch.get("from_chapter") or "")
            seed = self._find_clean_seed(subject, first_chapter)
            current_age = seed["age"] if seed else self.parse_explicit_age(first_patch.get("event"))
            if current_age is None:
                continue

            # 事件链起点
            start_context = seed.get("context_id") if seed else f"PATCH::{subject}::EVENT::0"
            start_segment = seed.get("segment_id") if seed else None
            self.patch_events.append({
                "subject": subject,
                "patch_index": None,
                "event_id": f"PATCH::{subject}::EVENT::0",
                "chapter": first_chapter,
                "age": current_age,
                "context_id": start_context,
                "segment_id": start_segment,
                "event": "event_chain_start",
            })

            current_context = start_context
            current_segment = start_segment

            for event_no, (patch_index, patch) in enumerate(items, start=1):
                from_chapter = str(patch.get("from_chapter") or "")
                to_chapter = str(patch.get("to_chapter") or "")
                try:
                    span = int(patch.get("span_years"))
                except (TypeError, ValueError):
                    continue

                from_age = current_age
                expected_to_age = from_age + span
                explicit_age = self.parse_explicit_age(patch.get("event"))

                # 对第一条 patch，event 常描述终点年龄，例如“5岁被拐”。
                # 如果与 seed + span 一致，则使用它作为验证；不一致则记录冲突并保留跨度计算值。
                to_age = expected_to_age
                if explicit_age is not None and explicit_age != expected_to_age:
                    if explicit_age == from_age:
                        # 例如“贾瑞20岁生病1年后死亡”：20岁是起点。
                        to_age = expected_to_age
                    else:
                        self.conflicts.append({
                            "type": "patch_age_vs_span_conflict",
                            "subject": subject,
                            "patch_index": patch_index,
                            "from_age": from_age,
                            "span_years": span,
                            "expected_to_age": expected_to_age,
                            "explicit_event_age": explicit_age,
                            "event": patch.get("event"),
                        })
                        # 人工明确的年龄仍然可以作为终点事实
                        to_age = explicit_age

                to_context = f"PATCH::{subject}::EVENT::{event_no}"

                # 保存终点补充年龄点
                self.age_points.append({
                    "subject": subject,
                    "age": to_age,
                    "chapter": to_chapter,
                    "segment_id": None,
                    "context_id": to_context,
                    "temporal_anchor": "PRESENT",
                    "source": "05_time_patches_derived",
                    "patch_index": patch_index,
                    "event": patch.get("event"),
                    "from_context_id": current_context,
                    "span_years_from_previous": span,
                })

                self.patch_events.append({
                    "subject": subject,
                    "patch_index": patch_index,
                    "event_id": to_context,
                    "chapter": to_chapter,
                    "age": to_age,
                    "context_id": to_context,
                    "segment_id": None,
                    "event": patch.get("event"),
                    "from_context_id": current_context,
                    "span_years_from_previous": span,
                })

                current_age = to_age
                current_context = to_context
                current_segment = None

    # ------------------------------------------------------------------
    # 3. 年龄关系
    # ------------------------------------------------------------------
    @staticmethod
    def edge_key(edge: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            edge["a"], edge["b"], edge["difference"],
            edge.get("context_id"), edge.get("source")
        )

    def add_edge(self, edge: Dict[str, Any]) -> None:
        if self.edge_key(edge) not in {self.edge_key(e) for e in self.direct_edges}:
            self.direct_edges.append(edge)

    def add_relative_edges(self) -> None:
        for fact in self.facts:
            if not self.is_age_fact(fact):
                continue
            if fact.get("clue_type") != "relative_diff" or fact.get("temporal_anchor") != "PRESENT":
                continue
            a = self.normalize_person(fact.get("subject"))
            b = self.normalize_person(fact.get("target"))
            diff = fact.get("diff_value")
            if not a or not b or diff is None:
                continue
            try:
                diff = int(diff)
            except (TypeError, ValueError):
                continue
            sid = fact.get("segment_id")
            self.add_edge({
                "a": a,
                "b": b,
                "difference": diff,
                "equation": f"Age({a}) - Age({b}) = {diff}",
                "source": "explicit_relative_diff",
                "segment_id": sid,
                "context_id": f"SEGMENT::{sid}",
                "chapter": fact.get("chapter"),
                "source_key": fact.get("source_key"),
                "evidence": [fact.get("source_key")] if fact.get("source_key") else [],
            })

    def add_same_context_edges(self) -> None:
        """
        只对“同一个 PRESENT 时间上下文”中的绝对年龄做两两相减。

        时间上下文有两种：
          1. clean fact 的 SEGMENT::<segment_id>；
          2. patch 补充年龄经过关系扩展后形成的 PATCH::<subject>::EVENT::<n>。

        因此，patch 不是只产生一个人的年龄；如果 patch 已经给某人物一个年龄，
        又可以通过 05 的年龄关系网络得到其他人物在同一事件时刻的年龄，
        那么这些年龄也应该进入同一个 context 并计算年龄差。
        """
        grouped: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for point in self.age_points:
            context = str(point.get("context_id") or "")
            source = str(point.get("source") or "")
            if not context:
                continue
            if not (context.startswith("SEGMENT::") or context.startswith("PATCH::")):
                continue
            # age_points 中进入主年龄网络的点必须是 PRESENT。
            # clean point 本身已经由 build_clean_age_points 过滤；patch point 在本模块中也视为 PRESENT 事件点。
            if source == "05_clean_facts" or source.startswith("05_time_patches") or source.startswith("05_age_relationship_inferred_at_patch"):
                subject = point.get("subject")
                if subject:
                    grouped[context][str(subject)] = point

        for context_id, members_map in grouped.items():
            members = list(members_map.values())
            if len(members) < 2:
                continue

            sid = None
            if context_id.startswith("SEGMENT::"):
                try:
                    sid = int(context_id.split("::", 1)[1])
                except Exception:
                    sid = None

            edge_source = (
                "same_segment_present_absolute_age"
                if context_id.startswith("SEGMENT::")
                else "same_patch_event_present_absolute_age"
            )

            for left, right in combinations(members, 2):
                diff = int(left["age"]) - int(right["age"])
                self.add_edge({
                    "a": left["subject"],
                    "b": right["subject"],
                    "difference": diff,
                    "equation": f"Age({left['subject']}) - Age({right['subject']}) = {diff}",
                    "source": edge_source,
                    "segment_id": sid,
                    "context_id": context_id,
                    "chapter": left.get("chapter"),
                    "evidence": [
                        x for x in [left.get("source_key"), right.get("source_key")]
                        if x
                    ],
                })

    def infer_patch_context_ages(self) -> None:
        """用年龄关系把 patch 已知人物的年龄扩展到相关人物。

        例如 patch 给出：
            贾宝玉 = 7
        而年龄关系有：
            Age(贾宝玉) - Age(林黛玉) = 1
        则补充：
            林黛玉 = 6

        这里生成的是“同一个 patch event context 下”的补充年龄点，
        不等于把人物永久地绑定到这个年龄。
        """
        if not self.patch_events:
            return

        adjacency: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = defaultdict(list)
        # 只使用 direct edges；inferred_edges 是 direct 的数学闭包，避免重复传播及
        # 在不一致闭环中引入额外路径。
        for e in self.direct_edges:
            a, b, diff = e["a"], e["b"], int(e["difference"])
            # Age(a) - Age(b) = diff
            # 已知 a -> b = age(a) - diff
            adjacency[a].append((b, -diff, e))
            # 已知 b -> a = age(b) + diff
            adjacency[b].append((a, diff, e))

        existing_keys = {
            (
                p.get("subject"), p.get("age"), p.get("chapter"),
                p.get("context_id")
            )
            for p in self.age_points
        }

        for event in self.patch_events:
            seed_person = event.get("subject")
            seed_age = event.get("age")
            context_id = event.get("context_id") or event.get("event_id")
            chapter = event.get("chapter")
            if not seed_person or seed_age is None or not context_id or not chapter:
                continue

            distances: Dict[str, int] = {str(seed_person): int(seed_age)}
            via: Dict[str, Dict[str, Any]] = {}
            queue = deque([str(seed_person)])

            while queue:
                current = queue.popleft()
                for nxt, delta, edge in adjacency.get(current, []):
                    proposed = distances[current] + delta
                    if nxt not in distances:
                        distances[nxt] = proposed
                        via[nxt] = {
                            "from_person": current,
                            "relationship": f"Age({edge['a']}) - Age({edge['b']}) = {edge['difference']}",
                            "edge_source": edge.get("source"),
                        }
                        queue.append(nxt)
                    elif distances[nxt] != proposed:
                        self.conflicts.append({
                            "type": "patch_context_age_relationship_conflict",
                            "context_id": context_id,
                            "person": nxt,
                            "existing_age": distances[nxt],
                            "new_age": proposed,
                            "via": current,
                        })

            for person, age in distances.items():
                if person == seed_person:
                    continue
                key = (person, age, chapter, context_id)
                if key in existing_keys:
                    continue
                self.age_points.append({
                    "subject": person,
                    "age": age,
                    "chapter": str(chapter),
                    "segment_id": None,
                    "context_id": str(context_id),
                    "temporal_anchor": "PRESENT",
                    "source": "05_age_relationship_inferred_at_patch",
                    "patch_index": event.get("patch_index"),
                    "event": event.get("event"),
                    "derived_from": via.get(person),
                })
                existing_keys.add(key)

    def build_transitive_closure(self) -> None:
        """年龄关系闭包。关系边按人物本身视为年龄差约束。

        若不同来源形成不一致闭环，只记录冲突，不覆盖原始边。
        """
        adjacency: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = defaultdict(list)
        persons = {p["subject"] for p in self.age_points}
        for e in self.direct_edges:
            persons.update({e["a"], e["b"]})
            adjacency[e["a"]].append((e["b"], int(e["difference"]), e))
            adjacency[e["b"]].append((e["a"], -int(e["difference"]), e))

        self.inferred_edges = []
        seen: set[Tuple[str, str, int]] = set()
        for start in sorted(persons):
            distance = {start: 0}
            evidence = {start: []}
            queue = deque([start])
            while queue:
                cur = queue.popleft()
                for nxt, delta, source_edge in adjacency.get(cur, []):
                    proposed = distance[cur] + delta
                    path = evidence[cur] + [source_edge.get("source_key") or source_edge.get("source")]
                    if nxt not in distance:
                        distance[nxt] = proposed
                        evidence[nxt] = path
                        queue.append(nxt)
                    elif distance[nxt] != proposed:
                        self.conflicts.append({
                            "type": "age_network_inconsistent",
                            "start": start,
                            "node": nxt,
                            "existing_difference": distance[nxt],
                            "new_difference": proposed,
                            "via": source_edge.get("source_key") or source_edge.get("source"),
                        })

            for target, diff in distance.items():
                if target == start:
                    continue
                a, b = sorted([start, target])
                canonical_diff = diff if start == a else -diff
                key = (a, b, canonical_diff)
                if key in seen:
                    continue
                seen.add(key)
                if any(
                    (e["a"], e["b"], e["difference"]) == (a, b, canonical_diff)
                    or (e["a"], e["b"], e["difference"]) == (b, a, -canonical_diff)
                    for e in self.direct_edges
                ):
                    continue
                self.inferred_edges.append({
                    "a": a,
                    "b": b,
                    "difference": canonical_diff,
                    "equation": f"Age({a}) - Age({b}) = {canonical_diff}",
                    "source": "transitive_closure",
                    "evidence": evidence.get(target, []),
                })

    def solve(self) -> Dict[str, Any]:
        self.load_data()
        self.build_clean_age_points()
        self.build_patch_age_points()
        self.add_relative_edges()

        # 先用明确的 relative_diff 扩展 patch 事件中的相关人物年龄，
        # 再把这些“同一 patch 事件时刻”的年龄一起计算年龄差。
        self.infer_patch_context_ages()
        self.add_same_context_edges()

        # patch context 产生的新年龄关系也必须进入闭包。
        self.build_transitive_closure()

        # 去重年龄点
        unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for p in self.age_points:
            key = (
                p.get("subject"), p.get("age"), p.get("chapter"),
                p.get("segment_id"), p.get("context_id"), p.get("source"),
                p.get("patch_index"),
            )
            unique.setdefault(key, p)
        points = list(unique.values())
        points.sort(key=lambda p: (
            p.get("segment_id") if isinstance(p.get("segment_id"), int) else 10**9,
            str(p.get("chapter") or ""),
            str(p.get("subject") or ""),
            int(p.get("age", 0)),
            str(p.get("context_id") or ""),
        ))

        persons = sorted(
            {p["subject"] for p in points}
            | {e["a"] for e in self.direct_edges + self.inferred_edges}
            | {e["b"] for e in self.direct_edges + self.inferred_edges}
        )

        return {
            "schema_version": "05.age_network.4",
            "rules": {
                "present_only": True,
                "past": "PAST 不参与主年龄网络计算",
                "relative_diff": "直接使用 clean facts 已整理的 subject/target/diff_value",
                "same_context_absolute": "只对同一个 PRESENT 时间上下文（clean segment 或 patch event）的 absolute 年龄两两相减",
                "patch": "先补人物年龄点，不在 05 计算章节跨度",
            },
            "persons": persons,
            "age_points": points,
            "patch_events": self.patch_events,
            "direct_edges": self.direct_edges,
            "inferred_edges": self.inferred_edges,
            "conflicts": self.conflicts,
        }

    def save(self, path: str = OUTPUT_AGE_NETWORK) -> Dict[str, Any]:
        result = self.solve()
        self.save_json(path, result)
        return result


if __name__ == "__main__":

    if not os.path.exists(DEFAULT_PATCHES_INPUT):
        sample_patches = [
            {
                "subject": "香菱",
                "from_chapter": "第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀",
                "to_chapter": "第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀",
                "span_years": 2,
                "event": "5岁元宵节被拐（根据第四回追叙）",
            },
            {
                "subject": "香菱",
                "from_chapter": "第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀",
                "to_chapter": "第四回 薄命女偏逢薄命郎 葫芦僧乱判葫芦案",
                "span_years": 7,
                "event": "12岁被卖给冯渊和薛蟠，冯渊被打死，家奴告状",
            },
            {
                "subject": "香菱",
                "from_chapter": "第四回 薄命女偏逢薄命郎 葫芦僧乱判葫芦案",
                "to_chapter": "第四回 薄命女偏逢薄命郎 葫芦僧乱判葫芦案",
                "span_years": 1,
                "event": "13岁 贾雨村接手冯渊案并结案",
            },
            {
                "subject": "贾蓉",
                "from_chapter": "第二回 贾夫人仙逝扬州城 冷子兴演说荣国府",
                "to_chapter": "第六回 贾宝玉初试云雨情 刘姥姥一进荣国府",
                "span_years": 2,
                "event": "18岁 刘姥姥一进荣国府见到王熙凤的时候贾蓉十七八岁",
            },
            {
                "subject": "贾宝玉",
                "from_chapter": "第二回 贾夫人仙逝扬州城 冷子兴演说荣国府",
                "to_chapter": "第二回 贾夫人仙逝扬州城 冷子兴演说荣国府",
                "span_years": 0,
                "event": "7岁 冷子兴告诉贾雨村贾宝玉的年龄约七八岁，说明林黛玉应该5岁多快6岁了",
            },
            {
                "subject": "贾瑞",
                "from_chapter": "第十一回 庆寿辰宁府排家宴 见熙凤贾瑞起淫心",
                "to_chapter": "第十二回 王熙凤毒设相思局 贾天祥正照风月鉴",
                "span_years": 1,
                "event": "贾敬过生日，秦可卿病重，贾瑞见到王熙凤，十一月三十日贾瑞主动找王熙凤，王熙凤设相思局让贾瑞受惊吓着凉导致生病，贾瑞20岁生病1年后死亡，不久后秦可卿死亡",
            },
        ]
        os.makedirs(os.path.dirname(DEFAULT_PATCHES_INPUT), exist_ok=True)
        with open(DEFAULT_PATCHES_INPUT, "w", encoding="utf-8") as f:
            json.dump(sample_patches, f, ensure_ascii=False, indent=2)
        print(f"已创建补丁样例：{DEFAULT_PATCHES_INPUT}")

    solver = AgeRelationshipSolver()
    result = solver.save()
    print(f"05 完成：{OUTPUT_AGE_NETWORK}")
    print(f"年龄点: {len(result['age_points'])}")
    print(f"人物: {len(result['persons'])}")
    print(f"直接年龄关系: {len(result['direct_edges'])}")
    print(f"推导年龄关系: {len(result['inferred_edges'])}")
    print(f"冲突: {len(result['conflicts'])}")
