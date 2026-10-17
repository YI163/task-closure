#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_check.py —— 把「我的产出」和「来源里写明的清单」并排列出来，缺口自己显形。

## 为什么需要它（用户追问促成）

用户问：「有没有什么能让你做得更好、更准确的办法，比如给奖励引导你按规则做」。

**奖励对这类问题无效**，原因是：我没有跨会话记忆（奖励无处累积）、没有动机系统，
**而且一旦有分数，我会优化分数而不是目标**——本会话已出现过一次：
把「缺口清单走完」当成「要求全做到了」，因为前者可打分。

**真正有效的机制有个共同点：越"物理"越有效。**
  · 教训库（可检索）→ 同一错犯两次
  · 硬前置（送达到眼前）→ 违反率大降
  · deliver.py 拦截（会拒绝）→ **从未被违反**

**更深一层**：我的错误不全是「不知道」或「无视」，而是**「写的时候规则不在场」**。
  · 读规则时它在场 ✅
  · 动手写 HTML / 拼文件名时它不在场 ❌
  · deliver.py 有效，是因为它在「写完之后、发出去之前」又把规则带回来了

## 本工具补的是另一块：不需要判断力的对照

实测最有用的三个动作，都是「换个角度重看」：
  · 用户问「自我介绍呢」→ 抓到流程图漏环节
  · 用户说「回头看规则原文」→ 抓到格式被擅自改
  · 审查员造了 11 个反例 → 抓到 11 条

**但这件事一直依赖用户或专门派 agent。** 本工具把其中**纯机械的那部分**自动化：
**把两边列出来并排看**——我不需要判断「完整不完整」，
只要缺口在并排视图里显形就够了。

## 用法

    python3 scripts/coverage_check.py --task TN-20261015-005 \\
        --source "自我介绍 + 讲题 10-15 分钟 + 5 分钟结构化面试"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402


def split_items(text: str) -> list[str]:
    """把来源里的一句话流程拆成环节。只用分隔符拆，不做语义判断。"""
    parts = re.split(r"[+＋、,，;；]|\s*→\s*|\s*->\s*", text)
    return [p.strip() for p in parts if p.strip()]


def gather_output(task_id: str) -> tuple[list[str], str]:
    """收集：交付文件清单 + 全部文本内容（供对照）。

    递归子目录（数据附件常放在 `数据/` 之类的子目录里），并且把 `.json/.jsonl/.csv`
    也计入对照正文——否则「取回 N 条原文」这类产出会被误报为缺口：文件确实是产出了，
    只是格式不是 .md/.html。误报会让真缺口淹没在噪音里。
    """
    d = store.PROJECT_ROOT / "outputs" / "deliverables" / task_id
    names: list[str] = []
    body = ""
    if d.is_dir():
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = f.relative_to(d).as_posix()
            names.append(rel)
            if f.suffix.lower() in (".md", ".html", ".json", ".jsonl", ".csv", ".txt"):
                body += f.read_text(encoding="utf-8", errors="ignore")
    desc = store.PROJECT_ROOT / "state" / "flowcharts"
    if desc.is_dir():
        for f in desc.glob(f"{task_id}*.json"):
            body += f.read_text(encoding="utf-8", errors="ignore")
    return names, body


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把产出与来源清单并排列出，让缺口显形")
    ap.add_argument("--task", required=True)
    ap.add_argument("--source", required=True,
                    help="来源里写明的清单，用 + 或 、 分隔（例如「自我介绍+讲题+面试」）")
    ap.add_argument("--label", default="来源清单")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    data = store.load_tasks()
    store.find_task(data["tasks"], args.task)   # 校验任务存在

    names, body = gather_output(args.task)
    items = split_items(args.source)

    print("═══ 覆盖对照（不判断，只罗列）═══")
    print()
    print(f"【A. 我实际产出了什么】{len(names)} 个文件")
    for n in names:
        print(f"    {n}")
    print()
    print(f"【B. {args.label}】{len(items)} 项")
    for i, s in enumerate(items, 1):
        print(f"    {i}. {s}")
    print()
    print("【C. 逐项对照（只要在产出里找不到，就标缺）】")
    missing = []
    for s in items:
        # 用前 2–3 个字做包含匹配——**故意做粗**，目的是"宁可多报也不漏报"
        keys = [k for k in (s[:3], s[:2]) if len(k) >= 2]
        hit = any(k in body for k in keys)
        print(f"    {'✅' if hit else '❌ 产出里找不到'}  「{s}」")
        if not hit:
            missing.append(s)
    # 记录结果供 deliver.py 查（放在项目内，不进用户视线）
    rec_dir = store.PROJECT_ROOT / "state" / "coverage_checks"
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec_dir.joinpath(f"{args.task}.json").write_text(json.dumps({
        "task_id": args.task,
        "checked_at": store.now_iso(),
        "label": args.label,
        "source_items": items,
        "missing": missing,
        "passed": not missing,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    if missing:
        print(f"❌ 有 {len(missing)} 项在产出里找不到：")
        for m in missing:
            print(f"     · {m}")
        print()
        print("   → 这不是「判定你不合格」，而是「这两边不一样，去看一眼」。")
        print("     可能是：① 真漏了  ② 用词不同（那就改一处让它能对上）")
        return 1
    print(f"✅ {len(items)} 项在产出里都能找到")
    print()
    print("   ⚠️ 注意这个检查的边界：它只查「有没有出现」，**不查「写对不对」**。")
    print("      规则写没写对、流程顺序对不对，仍需人看。")
    return 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
