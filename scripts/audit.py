#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py —— 审计 SKILL.md 的硬前置：哪几条真有约束，哪几条只靠自觉。

为什么需要它：用户问过一次「所以现在 skill 里所有硬性规则都是这么做的吗，还是只有我提到的你才这么改了」。
当时队长只能手工 grep 逐条回答。这个脚本把那次数的手工检查变成可复跑的命令。

## 判据（重要：证据等级）

旧版只看「源码里出现某个字符串」，然后把规则标成「机械」——字符串在注释、
错误提示、甚至没被调用的函数里都能通过，这会给出过强的可靠性结论。
现在分成：

  【机械】/【半机械】 **行为测试证实**：tests/unit/test_skill_guards.py 里有可复跑的探针，
                  在临时副本里真实执行脚本，证明违规输入会被拒绝；
  【静态线索】**未行为验证**：只在源码里找到依据，运行时会怎样尚未证明；
  【纯自觉】文档里有文字，没有任何工具检查。

所以「机械」这一栏只在探针跑通时出现；探针失败会直接让 audit 非零退出。

用法：python3 scripts/audit.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

SCRIPTS = store.PROJECT_ROOT / "scripts"
SKILL = store.PROJECT_ROOT / "skills" / "task-navigator" / "SKILL.md"
PROBE_SCRIPT = store.PROJECT_ROOT / "tests" / "unit" / "test_skill_guards.py"


def read(name: str) -> str:
    p = SCRIPTS / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def check_rule(rule_no: str, title: str, probes: list[tuple[str, str, str]]) -> tuple[str, list[str]]:
    """源码线索：probes = [(文件, 特征串, 说明)]，任一命中即返回证据。"""
    for filename, needle, desc in probes:
        if needle and needle in read(filename):
            return desc, [f"{filename} 含 `{needle}`"]
    return "", []


# (编号, 标题, 声称强度, 源码线索, 行为探针 key)
# 编号必须与 SKILL.md §0 的编号一致；tests/unit/test_audit_consistency.py 守着这一点。
RULES: list[tuple[str, str, str, list[tuple[str, str, str]], str | None]] = [
    ("1", "先读状态再开口", "机械",
     [("task_show.py", "PRECONDITIONS", "task_show 每次输出都打印开工必读")],
     "task-show-preconditions"),
    ("2", "状态变更必须走脚本", "半机械",
     [("store.py", "单一入口", "store.py 声明所有读写必须经过它；但无机制阻止直接编辑 JSON")],
     None),  # 没有可复跑的行为测试：不能宣称已被证明
    ("3", "不假装（没执行不说已执行）", "纯自觉",
     [("", "", "")],
     None),
    ("4", "写计划前先读规则", "半机械",
     [("task_show.py", "硬前置自检", "规则随 task_show 输出送到眼前；但「是否真的读了」无法检查")],
     None),
    ("5", "主路径不可被后续问答推翻", "半机械",
     [("deliver.py", "primary_path_respected", "交付检查会逐条提问并要求留痕")],
     "deliver-judgment"),
    ("6", "出交付物前对照 constraints", "半机械",
     [("deliver.py", "constraints_checked", "交付检查会逐条提问并要求留痕")],
     "deliver-judgment"),
    ("7", "交付位置/格式/命名", "机械",
     [("deliver.py", "naming_ok", "命名规则被代码检查（任务 ID 前缀 / >25 字符）"),
      ("deliver.py", "DESKTOP", "桌面可达性被代码检查")],
     "deliver-naming"),
    ("8", "承诺必配方案", "机械",
     [("deliver.py", "scan_commitments", "承诺句被代码扫描")],
     "deliver-commitments"),
    ("9", "交付前必须跑交付检查", "机械",
     [("task_update.py", "_has_deliverables", "有交付物但无 delivery_check 时 close 直接拒绝")],
     "close-gate"),
    ("10", "交付必须包含行动清单", "机械",
     [("deliver.py", "缺少「行动清单」文件", "交付目录无行动清单时直接报错、不得交付")],
     "deliver-action-list"),
    # 编号跟随 SKILL.md：文档里这条写作「10-2」，不是 102。
    ("10-2", "流程图必须渲染（禁止手写ASCII）", "机械",
     [("deliver.py", "缺少流程图（渲染版）", "只认渲染出的 HTML/PNG/PDF；主动报出手写 ASCII 框图")],
     "deliver-flowchart"),
    ("11", "绝不擅自合并用户文件", "机械",
     [("deliver.py", "GENERATED-MERGE-BUNDLE", "合并本带标记，检测只认标记")],
     "deliver-merge-marker"),
    # 第 12 条没有脚本检查：如实标「纯自觉」，不编机械依据。
    ("12", "交付物过多时软删（移出视线）", "纯自觉",
     [("", "", "")],
     None),
]


def run_behavior_probes() -> tuple[dict[str, dict], str]:
    """跑一次行为探针脚本，返回 ({key: {ok, detail}}, 错误说明)。"""
    if not PROBE_SCRIPT.is_file():
        return {}, f"找不到行为探针：{PROBE_SCRIPT}"
    with tempfile.TemporaryDirectory(prefix="tc-audit-") as td:
        out = Path(td) / "probes.json"
        try:
            proc = subprocess.run(
                [sys.executable, str(PROBE_SCRIPT), "--json", str(out)],
                cwd=str(store.PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {}, f"行为探针执行失败：{type(exc).__name__}: {exc}"
        if not out.is_file():
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-300:]
            return {}, "行为探针没有产出结果（脚本提前失败）：" + (tail or "（无输出）")
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"行为探针结果无法解析：{exc}"
    return data.get("probes", {}) or {}, ""


def evaluate(
    rule: tuple[str, str, str, list[tuple[str, str, str]], str | None],
    probe_results: dict[str, dict],
) -> tuple[str, str, str]:
    """返回 (显示强度, 证据, 基础档位)。基础档位用于统计。"""
    no, title, claimed, sources, behavior = rule
    _, evidence = check_rule(no, title, sources)

    if behavior:
        result = probe_results.get(behavior)
        if result is None:
            return "未证实", f"行为探针 {behavior} 未运行", "未证实"
        if result.get("ok"):
            detail = f"行为探针 {behavior} ✅"
            if evidence:
                detail += f"｜源码线索：{evidence[0]}"
            return f"{claimed}（行为测试）", detail, claimed
        return "未证实", f"行为探针 {behavior} ❌：{result.get('detail', '未通过')}", "未证实"

    if evidence:
        return "静态线索", f"仅源码线索：{evidence[0]}（未行为验证，不能宣称机械约束）", "静态线索"
    return "纯自觉", "无", "纯自觉"


def main() -> int:
    print("═══ SKILL.md 硬前置审计 ═══")
    print(f"规则文件：{SKILL.relative_to(store.PROJECT_ROOT)}")
    print(f"行为探针：{PROBE_SCRIPT.relative_to(store.PROJECT_ROOT)}"
          f"（{len({key for _, _, _, _, key in RULES if key})} 个）")
    print()

    text = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""
    doc_rules = len(re.findall(r"^\d+(?:-\d+)?\. \*\*", text.split("### 4.1")[0], re.M))

    probe_results, probe_error = run_behavior_probes()
    if probe_error:
        print(f"⚠️ {probe_error}")
        print()

    counts = {"机械": 0, "半机械": 0, "静态线索": 0, "纯自觉": 0, "未证实": 0}
    rows = []
    for rule in RULES:
        level, evidence, base = evaluate(rule, probe_results)
        counts[base] += 1
        rows.append((rule[0], rule[1], level, evidence))

    print(f"{'#':<4}{'硬前置':<26}{'约束强度':<16}证据")
    print("─" * 96)
    for no, title, level, evidence in rows:
        mark = {"机械": "🔒", "半机械": "🔸", "静态线索": "◻️ ", "纯自觉": "⚠️ ", "未证实": "❓"}.get(
            level.split("（")[0], "•")
        print(f"{no:<4}{title:<26}{mark}{level:<14}{evidence}")

    print()
    print("【统计】")
    print(f"  文档中写的条数：{doc_rules}　审计表条数：{len(RULES)}"
          + ("" if doc_rules == len(RULES) else "　⚠️ 两者不一致，审计表需同步"))
    print(f"  机械（行为测试证实）：{counts['机械']}")
    print(f"  半机械（行为测试证实）：{counts['半机械']}")
    print(f"  静态线索（未行为验证）：{counts['静态线索']}")
    print(f"  纯自觉：{counts['纯自觉']}")
    if counts["未证实"]:
        print(f"  未证实（行为测试失败/缺失）：{counts['未证实']}")

    print()
    print("【行为探针】")
    if probe_results:
        for key in sorted(probe_results):
            item = probe_results[key]
            print(f"  {'✅' if item.get('ok') else '❌'} {key}：{item.get('detail', '')}")
    else:
        print("  （没有跑到任何探针）")

    print()
    print("【结论】")
    self_rules = [no for no, _, level, _ in rows if level == "纯自觉"]
    if self_rules:
        print("  只靠自觉的规则：" + "、".join(f"第{n}条" for n in self_rules)
              + "——这些仍然无法由脚本阻止，报告里不得说成「已强制」。")
    static_rules = [no for no, _, level, _ in rows if level == "静态线索"]
    if static_rules:
        print("  仅有源码线索、尚无行为验证的规则：" + "、".join(f"第{n}条" for n in static_rules))
    print("  「机械」= 行为测试证明不满足会被拒绝；「静态线索」= 只在源码里找到依据。")

    ok = doc_rules == len(RULES) and counts["未证实"] == 0 and not probe_error
    return 0 if ok else 1


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    sys.exit(main())
