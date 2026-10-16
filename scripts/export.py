#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export.py —— 导出用户数据。落实 spec/01 §6「提供查看、纠正、删除方式」与 SKILL.md 的导出承诺。

背景：合规审计（t23）发现 G7 —— SKILL.md 写了「可以要求导出」，但 `grep -rniE "导出|export" scripts/*.py`
0 命中。**承诺了却没有实现**，属「只承诺不落地」，与第 8 条硬前置直接冲突。

用法：
    python3 scripts/export.py --all                 # 导出全部数据到一个 Markdown
    python3 scripts/export.py --all --json          # 同时导出机器可读的 JSON
    python3 scripts/export.py --desktop             # 输出到桌面（用户能直接打开）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

DESKTOP = Path.home() / "Desktop" / "任务交付"


def md_table(rows: list[list[str]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("\n", " ").replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def build_markdown() -> str:
    tasks = store.load_tasks()["tasks"]
    skills = store.load_skills()["skills"]
    exps = store.load_experiences()

    L: list[str] = []
    L.append("# 我的数据导出（任务导航）")
    L.append("")
    L.append(f"> 导出时间：{store.now_iso()}　共 {len(tasks)} 个任务、{len(skills)} 条技能、{len(exps)} 条经验")
    L.append("> **这份文件是给你看的**：你的全部数据，可读、可核对、可带走。")
    L.append("")

    L.append("## 一、任务")
    L.append("")
    rows = []
    for t in tasks:
        done = len(t.get("completed_steps", []))
        total = len(t.get("plan", []))
        rows.append([
            t["task_id"], t["title"], t["status"], f"{done}/{total}",
            t.get("planning_depth", ""), (t.get("primary_path") or {}).get("description", "—"),
        ])
    L.append(md_table(rows, ["任务编号", "标题", "状态", "进度", "档位", "主路径"]))
    L.append("")

    for t in tasks:
        L.append(f"### {t['task_id']}《{t['title']}》")
        L.append("")
        L.append(f"- 原始请求：{t.get('original_request', '')}")
        L.append(f"- 目标：{t.get('goal', '')}")
        L.append(f"- 成功标准：{'；'.join(t.get('success_criteria', []))}")
        if t.get("verdict"):
            L.append(f"- 验收结论：{t['verdict']}")
        if t.get("completed_steps"):
            L.append("- 已完成步骤与证据：")
            for c in t["completed_steps"]:
                L.append(f"    - {c.get('step_id')}：{c.get('evidence')}")
        if t.get("next_best_action"):
            L.append(f"- 下一步：{t['next_best_action'].get('action')}")
        L.append("")

    L.append("## 二、我的技能档案")
    L.append("")
    rows = []
    for s in skills:
        rows.append([
            s["skill_id"], s["skill_name"], s["status"],
            str(len(s.get("evidence", []))), ",".join(s.get("related_tasks") or []) or "—",
        ])
    L.append(md_table(rows, ["技能编号", "技能", "状态", "证据数", "关联任务"]))
    L.append("")
    L.append("> 状态含义：`can_independently`=有独立操作证据；`can_with_checklist`=照清单能做；")
    L.append("> `not_yet`=暂未掌握；`not_assessed`=未评估。**「AI 讲解过」不构成升级依据。**")
    L.append("")

    L.append("## 三、经验库")
    L.append("")
    if not exps:
        L.append("（暂无）")
    for e in exps:
        L.append(f"### {e.get('experience_id')}《{e.get('title')}》")
        L.append("")
        L.append(f"- 状态：{e.get('status')}（`single_observation`=单次观察，不等于普遍规律）")
        L.append(f"- 来源任务：{e.get('source_task_id')}")
        L.append(f"- 结论：{e.get('conclusion')}")
        L.append(f"- 适用条件：{'；'.join(e.get('trigger_conditions', []))}")
        if e.get("limitations"):
            L.append(f"- 限制：{'；'.join(e['limitations'])}")
        L.append("")

    L.append("## 四、怎么查看 / 纠正 / 删除")
    L.append("")
    L.append(f"- 全部原件在本机：`{store.PROJECT_ROOT}/state/`")
    L.append("- 想改哪条：直接编辑对应 JSON，或告诉我「改第 X 条」")
    L.append("- 想删除：直接删文件，或告诉我「删掉关于 X 的记录」")
    L.append("- **删除前系统会自动备份**，后悔了可以从 `state/backups/` 找回")
    L.append("")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="导出用户数据（可读 Markdown + 可选 JSON）")
    ap.add_argument("--all", action="store_true", help="导出全部数据")
    ap.add_argument("--json", action="store_true", help="同时导出机器可读 JSON")
    ap.add_argument("--desktop", action="store_true", help="输出到桌面（可直接打开）")
    ap.add_argument("--out", type=Path, help="指定输出目录")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    out_dir = args.out or (DESKTOP if args.desktop else store.PROJECT_ROOT / "outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = store.now_iso().replace(":", "").replace("-", "")[:15]

    md_path = out_dir / f"我的数据导出-{stamp}.md"
    md_path.write_text(build_markdown(), encoding="utf-8")
    print(f"✅ 已导出 Markdown：{md_path}")

    if args.json:
        payload = {
            "exported_at": store.now_iso(),
            "tasks": store.load_tasks(),
            "skills": store.load_skills(),
            "experiences": [store.read_json(p) for p in sorted(store.EXPERIENCE_DIR.glob("*.json"))],
        }
        json_path = out_dir / f"我的数据导出-{stamp}.json"
        store.write_json(json_path, payload)
        print(f"✅ 已导出 JSON：{json_path}")

    print()
    print("下一步：双击 .md 若打不开，用 `python3 scripts/md2html.py <文件> <输出.html>` 转成网页格式")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
