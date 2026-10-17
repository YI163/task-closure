#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py —— 审计 SKILL.md 的硬前置：哪几条真有机械约束，哪几条只靠自觉。

为什么需要它：用户问过一次「所以现在 skill 里所有硬性规则都是这么做的吗，还是只有我提到的你才这么改了」。
当时队长只能手工 grep 逐条回答。这个脚本把那次数的手工检查变成可复跑的命令。

判据（三档，按可靠度从高到低）：
  【机械】有脚本在不满足时直接拒绝（exit != 0），人绕不过去
  【半机械】工具会逐条提问并要求留痕，不回答不放行；但回答内容靠人自觉
  【纯自觉】只在文档里有文字，没有任何工具检查

用法：python3 scripts/audit.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

SCRIPTS = store.PROJECT_ROOT / "scripts"
SKILL = store.PROJECT_ROOT / "skills" / "task-navigator" / "SKILL.md"


def read(name: str) -> str:
    p = SCRIPTS / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def check_rule(rule_no: int, title: str, probes: list[tuple[str, str, str]]) -> tuple[str, list[str]]:
    """probes: [(文件, 特征串, 说明)]，任一命中即认为该档成立。"""
    for filename, needle, desc in probes:
        if needle and needle in read(filename):
            return desc, [f"{filename} 含 `{needle}`"]
    return "", []


RULES: list[tuple[int, str, str, list[tuple[str, str, str]]]] = [
    (1, "先读状态再开口", "机械",
     [("task_show.py", "PRECONDITIONS", "task_show 每次输出都打印九条硬前置与该任务 constraints——执行者必然看到")]),
    (2, "状态变更必须走脚本", "半机械",
     [("store.py", "单一入口", "store.py 声明所有读写必须经过它；但无机制阻止直接编辑 JSON")]),
    (3, "不假装（没执行不说已执行）", "纯自觉",
     [("", "", "")]),
    (4, "写计划前先读规则", "半机械",
     [("task_show.py", "硬前置自检", "规则随 task_show 输出送到眼前；但「是否真的读了」无法检查")]),
    (5, "主路径不可被后续问答推翻", "半机械",
     [("deliver.py", "primary_path_respected", "交付检查会逐条提问并要求留痕")]),
    (6, "出交付物前对照 constraints", "半机械",
     [("deliver.py", "constraints_checked", "交付检查会逐条提问并要求留痕")]),
    (7, "交付位置/格式/命名", "机械",
     [("deliver.py", "naming_ok", "命名规则被代码检查（任务 ID 前缀 / >25 字符直接报错）"),
      ("deliver.py", "DESKTOP", "桌面可达性被代码检查")]),
    (8, "承诺必配方案", "机械",
     [("deliver.py", "scan_commitments", "承诺句被代码扫描")]),
    (9, "交付前必须跑交付检查", "机械",
     [("task_update.py", "_has_deliverables", "有交付物但无 delivery_check 时，close 直接 die(2)")]),
    (10, "交付必须包含行动清单", "机械",
     [("deliver.py", "缺少「行动清单」文件", "交付目录无行动清单时直接报错、不得交付")]),
    (102, "流程图必须渲染（禁止手写ASCII）", "机械",
     [("deliver.py", "缺少流程图（渲染版）", "只认渲染出的 HTML/PNG/PDF；主动报出手写 ASCII 框图")]),
    (103, "绝不擅自合并用户文件", "机械",
     [("deliver.py", "GENERATED-MERGE-BUNDLE", "合并本带标记，检测只认标记（判据试过三版）")]),
    # 第 9 条「交付前跑检查」是一个动作，其组成部分不再单列——
    # 此前拆成三条（103/104/105）导致审计表比文档多 2 条。
    # **减法的方向也包括「审计表本身不要比规则更细」。
]


def main() -> int:
    print("═══ SKILL.md 硬前置审计 ═══")
    print(f"规则文件：{SKILL.relative_to(store.PROJECT_ROOT)}")
    print()

    # 先数 SKILL.md 里实际写了几条，防止审计表与文档脱节
    text = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""
    doc_rules = len(re.findall(r"^\d+(?:-\d+)?\. \*\*", text.split("### 4.1")[0], re.M))

    counts = {"机械": 0, "半机械": 0, "纯自觉": 0}
    rows = []
    for no, title, claimed, probes in RULES:
        found, evidence = check_rule(no, title, probes)
        level = claimed if found else "纯自觉"
        counts[level] += 1
        rows.append((no, title, level, evidence))

    print(f"{'#':<3}{'硬前置':<24}{'约束强度':<10}依据")
    print("─" * 78)
    for no, title, level, evidence in rows:
        mark = {"机械": "🔒", "半机械": "🔸", "纯自觉": "⚠️ "}[level]
        print(f"{no:<3}{title:<24}{mark}{level:<8}{(evidence[0] if evidence else '无')}")

    print()
    print("【统计】")
    print(f"  文档中写的条数：{doc_rules}　审计表条数：{len(RULES)}"
          + ("" if doc_rules == len(RULES) else "　⚠️ 两者不一致，审计表需同步"))
    for level in ("机械", "半机械", "纯自觉"):
        print(f"  {level}：{counts[level]} 条")

    print()
    print("【结论】")
    if counts["纯自觉"]:
        print(f"  仍有 {counts['纯自觉']} 条只靠自觉——这些是最可能被遗忘的："
              + "、".join(f"第{n}条" for n, _, lv, _ in rows if lv == "纯自觉"))
    print("  「机械」= 不满足直接拒绝，绕不过去；「半机械」= 会被追问但要人如实回答。")

    # 审计器自身也要防脱节
    return 0 if doc_rules == len(RULES) else 1


if __name__ == "__main__":
    sys.exit(main())
