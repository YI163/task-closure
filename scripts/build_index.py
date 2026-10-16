#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_index.py —— 生成经验库与方法库的可读索引。

为什么需要它：SKILL.md 的「数据存在哪」表里承诺了 `state/experience_index.md`
（可读索引），但**从来没有这个文件**——store.py 只定义了常量 EXPERIENCE_INDEX，无任何写入方。
用户是非程序员，能直接翻开看「系统到底学到了什么」比让他跑命令更有用。

索引是从数据**派生**的：每次经验/教训变更后重新生成，不会过期。

用法：
    python3 scripts/build_index.py            # 重新生成
    python3 scripts/build_index.py --check    # 只检查是否与数据一致（不一致则 exit 1）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

HEADER = """# 经验库索引

> **这份文件是从数据自动生成的**（`python3 scripts/build_index.py`），不要手工编辑。
> 数据源：`state/experience/*.json`（领域经验）与 `state/lessons/*.json`（流程类教训）。

## 这是什么

系统在真实任务里积累下来的东西，分两类：

| 类型 | 存哪 | 特点 |
|---|---|---|
| **领域经验** | `state/experience/` | 关于某类任务的结论，按领域（工作/生活）检索 |
| **流程类教训** | `state/lessons/` | 关于「怎么做事」的教训，跨所有任务，按六类归档 |

**重要**：这里每一条都有「证据强度」。`single_observation` = 只观察过一次，
**不等于普遍规律**。系统在检索时会标注这一点，不会拿单次观察当定论。

---

"""


def fmt_status(e: dict) -> str:
    st = e.get("status", "?")
    conf = (e.get("confidence") or {}).get("level", "?")
    return f"`{st}` / 置信度 `{conf}`"


def render_experience(e: dict) -> list[str]:
    out = [f"### {e.get('experience_id')}　{e.get('title', '')}", ""]
    out.append(f"- **证据强度**：{fmt_status(e)}")
    out.append(f"- **来源任务**：{e.get('source_task_id') or '（未记录）'}")
    out.append(f"- **领域 / 类型**：{e.get('domain', '?')} / {e.get('task_type', '?')}")
    if e.get("tags"):
        out.append(f"- **标签**：{'、'.join(e['tags'])}")
    out.append("")
    out.append(f"**结论**：{e.get('conclusion', '')}")
    out.append("")
    if e.get("recommended_action"):
        out.append(f"**建议做法**：{e['recommended_action']}")
        out.append("")
    if e.get("trigger_conditions"):
        out.append("**适用条件**：")
        for c in e["trigger_conditions"]:
            out.append(f"- {c}")
        out.append("")
    if e.get("limitations"):
        out.append("**限制 / 不适用**：")
        for c in e["limitations"]:
            out.append(f"- {c}")
        out.append("")
    if e.get("counterexamples"):
        out.append("**反例**：")
        for c in e["counterexamples"]:
            out.append(f"- {c}")
        out.append("")
    return out


def render_lesson(lesson: dict) -> list[str]:
    ltype = lesson.get("lesson_type", "?")
    out = [f"### [{ltype}] {lesson.get('experience_id')}　{lesson.get('title', '')}", ""]
    out.append(f"- **证据强度**：{fmt_status(lesson)}")
    out.append(f"- **来源**：{lesson.get('source') or '（未记录）'}")
    out.append("")
    out.append(f"**结论**：{lesson.get('conclusion', '')}")
    out.append("")
    if lesson.get("observed_outcome", {}).get("result"):
        out.append(f"**为什么**：{lesson['observed_outcome']['result']}")
        out.append("")
    if lesson.get("trigger_conditions"):
        out.append("**适用条件**：")
        for c in lesson["trigger_conditions"]:
            out.append(f"- {c}")
        out.append("")
    if lesson.get("limitations"):
        out.append("**不适用**：")
        for c in lesson["limitations"]:
            out.append(f"- {c}")
        out.append("")
    return out


def build() -> str:
    exps = store.load_experiences()
    lessons = []
    if store.LESSONS_DIR.is_dir():
        for p in sorted(store.LESSONS_DIR.glob("*.json")):
            try:
                lessons.append(store.read_json(p))
            except Exception:
                pass

    L = [HEADER]
    L.append(f"## 一、流程类教训（{len(lessons)} 条）")
    L.append("")
    L.append("按 SKILL.md §J 的六类归档。这些教训跨所有任务，检索时与领域经验合并。")
    L.append("")
    if not lessons:
        L.append("（暂无）")
    else:
        import collections
        groups: dict[str, list[dict]] = collections.OrderedDict()
        for t in ("失败原因", "技能差距", "流程改进", "有效做法", "无效做法", "方法适用条件"):
            got = [x for x in lessons if x.get("lesson_type") == t]
            if got:
                groups[t] = got
        for t, items in groups.items():
            L.append(f"### 【{t}】{len(items)} 条")
            L.append("")
            for x in items:
                L.extend(render_lesson(x))
                L.append("---")
                L.append("")

    L.append(f"## 二、领域经验（{len(exps)} 条）")
    L.append("")
    if not exps:
        L.append("（暂无）")
    else:
        for e in exps:
            L.extend(render_experience(e))
            L.append("---")
            L.append("")

    L.append("## 三、怎么用这些经验")
    L.append("")
    L.append("```bash")
    L.append("python3 scripts/exp.py search --query \"你的任务关键词\"")
    L.append("```")
    L.append("")
    L.append("系统只会把**条件匹配**的经验作为建议给出，不会自动套用；")
    L.append("若经验与当前事实冲突，以当前事实为准。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成经验库可读索引")
    ap.add_argument("--check", action="store_true", help="只检查是否与数据一致")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    new = build()
    target = store.EXPERIENCE_INDEX
    if args.check:
        old = target.read_text(encoding="utf-8") if target.is_file() else ""
        if old != new:
            print(f"  ❌ 索引与数据不一致：{target}", file=sys.stderr)
            print("     请运行 python3 scripts/build_index.py 重新生成", file=sys.stderr)
            return 1
        print("  ✅ 索引与数据一致")
        return 0

    target.write_text(new, encoding="utf-8")
    print(f"  ✅ 已生成：{target.relative_to(store.PROJECT_ROOT)}（{len(new.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
