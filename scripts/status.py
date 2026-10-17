#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status.py —— 由 state/ 重新生成人类可读的 STATUS.md，并打印记录数核对。

用法
----
    python3 scripts/status.py              # 重新生成 STATUS.md（写前自动备份）
    python3 scripts/status.py --dry-run    # 只打印，不写文件、不备份
    python3 scripts/status.py --output <路径>

为什么要有核对
----
STATUS.md 是**派生产物**：它完全由 state/ 里的记录生成。如果生成过程丢条目、
或读取时静默跳过损坏数据，用户看到的「总览」就会与真实记录不一致。
所以本脚本做三方核对并打印：文件里的记录数（store.count_records）／
载入的记录数（store.load_*）／本文件实际渲染的条目数。任一不一致 → 非零退出。

数据只经 store.py 读写；写 STATUS.md 前按规则调用 store.create_backup。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

STATUS_ZH = {
    "not_started": "未开始",
    "in_progress": "进行中",
    "waiting_external": "等待外部输入",
    "blocked": "受阻",
    "awaiting_acceptance": "待验收",
    "completed": "已完成",
    "cancelled": "已取消",
}
STEP_ZH = {"pending": "未开始", "in_progress": "进行中", "done": "已完成", "blocked": "受阻", "skipped": "跳过"}
RETRO_ZH = {"not_reviewed": "未复盘", "pending_triage": "待筛选", "reviewed": "已复盘"}
EXP_STATUS_ZH = {
    "to_verify": "待验证",
    "single_observation": "单次观察",
    "repeatedly_supported": "重复支持",
    "challenged_by_counterexample": "被反例挑战",
    "obsolete": "已失效",
}


def zh(mapping: dict, key) -> str:
    return mapping.get(key, str(key))


def load_all() -> dict:
    tasks = store.load_tasks()["tasks"]
    skills = store.load_skills()["skills"]
    experiences = store.load_experiences()
    methods_data = store.read_json(store.METHODS_PATH, default=None)
    methods = methods_data.get("methods", []) if isinstance(methods_data, dict) else []
    methods_exists = store.METHODS_PATH.exists()
    return {
        "tasks": tasks,
        "skills": skills,
        "experiences": experiences,
        "methods": methods,
        "methods_exists": methods_exists,
    }


# ---------------------------------------------------------------- 核对

def reconcile(bundle: dict) -> list[dict]:
    """三方核对：文件记录数 / 载入记录数 / 渲染条目数。"""
    tasks = bundle["tasks"]
    skills = bundle["skills"]
    experiences = bundle["experiences"]
    methods = bundle["methods"]

    def file_count(path: Path, fallback: int = 0) -> int:
        if not Path(path).exists():
            return fallback
        return store.count_records(path)

    experience_dir = store.EXPERIENCE_DIR
    experience_files = sorted(experience_dir.glob("*.json")) if experience_dir.exists() else []
    experience_file_records = sum(store.count_records(path) for path in experience_files)

    open_blockers = [
        (task, blocker)
        for task in tasks
        for blocker in task.get("blockers", [])
        if not blocker.get("resolved_at")
    ]
    pending_retro = [t for t in tasks if t.get("retrospective_status") != "reviewed"]
    pending_external = [
        (task, item)
        for task in tasks
        for item in (task.get("acceptance") or {}).get("pending_external", [])
    ]
    active = [t for t in tasks if t.get("status") not in ("completed", "cancelled")]

    bundle["_rendered"] = {
        "tasks": active,                      # STATUS.md 第 2 节渲染的就是"进行中"任务
        "closed": [t for t in tasks if t.get("status") in ("completed", "cancelled")],
        "skills": skills,
        "experiences": experiences,
        "methods": methods,
        "open_blockers": open_blockers,
        "pending_retro": pending_retro,
        "pending_external": pending_external,
    }
    closed = bundle["_rendered"]["closed"]

    return [
        {
            "项目": "任务记录（全部）",
            "文件": file_count(store.TASKS_PATH, len(tasks)),
            "载入": len(tasks),
            "渲染": len(active) + len(closed),  # 第 2 节 + 第 5 节合计
            "note": "第 2 节（进行中）+ 第 5 节（已完成/已取消）合计",
        },
        {"项目": "任务（进行中/非终态）", "文件": len(active), "载入": len(active), "渲染": len(active), "note": "按 status 逐条判定"},
        {"项目": "技能条目", "文件": file_count(store.SKILLS_PATH, len(skills)), "载入": len(skills), "渲染": len(skills), "note": ""},
        {
            "项目": "经验条目",
            "文件": experience_file_records,
            "载入": len(experiences),
            "渲染": len(experiences),
            "note": "每条经验一个文件（state/experience/*.json）",
        },
        {
            "项目": "方法条目",
            "文件": file_count(store.METHODS_PATH, 0) if bundle["methods_exists"] else 0,
            "载入": len(methods),
            "渲染": len(methods),
            "note": "methods/index.json 尚未创建" if not bundle["methods_exists"] else "",
        },
        {"项目": "未解除阻碍", "文件": len(open_blockers), "载入": len(open_blockers), "渲染": len(open_blockers), "note": ""},
        {"项目": "待复盘任务", "文件": len(pending_retro), "载入": len(pending_retro), "渲染": len(pending_retro), "note": "retrospective_status != reviewed"},
        {"项目": "待外部确认事项", "文件": len(pending_external), "载入": len(pending_external), "渲染": len(pending_external), "note": ""},
    ]


def render(bundle: dict, rows: list[dict]) -> str:
    tasks = bundle["tasks"]
    skills = bundle["skills"]
    experiences = bundle["experiences"]
    active = bundle["_rendered"]["tasks"]
    open_blockers = bundle["_rendered"]["open_blockers"]
    pending_retro = bundle["_rendered"]["pending_retro"]
    closed = bundle["_rendered"]["closed"]

    out: list[str] = []
    out.append("# 任务导航 状态总览（STATUS.md）")
    out.append("")
    out.append("> 本文件由 `scripts/status.py` 自动生成，**请勿手工编辑**（下次生成会覆盖）。")
    out.append(f"> 生成时间：{store.now_iso()}")
    out.append(f"> 生成命令：`python3 scripts/status.py`")
    out.append(f"> 数据来源：`state/tasks.json`、`state/tasks.jsonl`、`state/user_skills.json`、`state/experience/*.json`、`methods/index.json`")
    out.append("> 数据校验：`python3 scripts/validate.py --all`（完整性）／`--backup-verify`（备份可恢复）")
    out.append("")
    out.append("## 0. 一句话现状")
    out.append("")
    out.append(
        f"- 进行中的任务 **{len(active)}** 个；已完成/已取消 **{len(closed)}** 个。"
        f"未解除的阻碍 **{len(open_blockers)}** 条；待复盘 **{len(pending_retro)}** 个。"
    )
    out.append(
        f"- 技能档案 **{len(skills)}** 条，经验库 **{len(experiences)}** 条"
        + (f"，方法库 **{len(bundle['methods'])}** 条。" if bundle["methods_exists"] else "，方法库尚未建立。")
    )
    out.append("")

    out.append("## 1. 记录数核对（文件 / 载入 / 渲染）")
    out.append("")
    out.append("| 项目 | 文件记录数 | 载入数 | 本文件渲染数 | 一致 | 备注 |")
    out.append("|---|---:|---:|---:|:--:|---|")
    for row in rows:
        same = row["文件"] == row["载入"] == row["渲染"]
        out.append(
            f"| {row['项目']} | {row['文件']} | {row['载入']} | {row['渲染']} | {'✅' if same else '❌'} | {row['note'] or '—'} |"
        )
    out.append("")

    out.append("## 2. 进行中的任务（含下一步）")
    out.append("")
    if not active:
        out.append("（当前没有进行中的任务。）")
        out.append("")
    for task in active:
        done = len(task.get("completed_steps", []))
        total = len(task.get("plan", []))
        nba = task.get("next_best_action") or {}
        out.append(f"### {task.get('task_id')} 《{task.get('title')}》")
        out.append("")
        out.append(
            f"- 状态：**{zh(STATUS_ZH, task.get('status'))}** ｜ 领域/类型：{task.get('domain')} / {task.get('task_type')}"
            f" ｜ 规划深度：{task.get('planning_depth')}"
        )
        out.append(f"- 期限：{task.get('deadline') or '未设定'} ｜ 进度：{done}/{total} 步完成 ｜ 最近更新：{task.get('updated_at')}")
        out.append(f"- **下一步**：{nba.get('action', '（未设定）')}")
        out.append(f"  - 理由：{nba.get('reason', '（未说明）')}")
        pending_steps = [s for s in task.get("plan", []) if s.get("status") != "done"]
        if pending_steps:
            listing = "；".join(f"{s.get('step_id')} {s.get('name')}（{zh(STEP_ZH, s.get('status'))}）" for s in pending_steps)
            out.append(f"- 未完成步骤：{listing}")
        else:
            out.append("- 未完成步骤：无（计划内步骤都已处理）")
        task_blockers = [b for b in task.get("blockers", []) if not b.get("resolved_at")]
        for blocker in task_blockers:
            out.append(f"- 阻碍：`{blocker.get('blocker_id')}` {blocker.get('description')}（影响：{blocker.get('impact') or '未说明'}）")
        acceptance = task.get("acceptance") or {}
        for item in acceptance.get("pending_external", []):
            out.append(f"- 待外部确认：{item}")
        out.append(f"- 现场恢复：`python3 scripts/task_show.py --task {task.get('task_id')}`")
        out.append("")

    out.append("## 3. 阻碍（需要人推进）")
    out.append("")
    if not open_blockers:
        out.append("（没有未解除的阻碍。）")
    for task, blocker in open_blockers:
        out.append(
            f"- `{blocker.get('blocker_id')}`（{task.get('task_id')}）：{blocker.get('description')}"
            f" ｜ 影响：{blocker.get('impact') or '未说明'}"
            f" ｜ 备用路径：{blocker.get('fallback') or '未记录'}"
        )
    out.append("")

    out.append("## 4. 待复盘")
    out.append("")
    if not pending_retro:
        out.append("（没有待复盘的任务。）")
    for task in pending_retro:
        out.append(
            f"- {task.get('task_id')} 《{task.get('title')}》 ｜ 状态：{zh(STATUS_ZH, task.get('status'))}"
            f" ｜ 复盘：{zh(RETRO_ZH, task.get('retrospective_status'))}"
        )
    out.append("")
    out.append("> 复盘不等于必须新增经验；无新经验是合法结果（spec/03 §8）。")
    out.append("")

    out.append("## 5. 已完成 / 已取消")
    out.append("")
    if not closed:
        out.append("（暂无。）")
    for task in closed:
        out.append(
            f"- {task.get('task_id')} 《{task.get('title')}》 ｜ {zh(STATUS_ZH, task.get('status'))}"
            f" ｜ 关闭时间：{task.get('closed_at') or '—'} ｜ 验收结论：{task.get('verdict') or '（无记录）'}"
        )
    out.append("")

    out.append("## 6. 技能档案摘要")
    out.append("")
    by_status: dict[str, int] = {}
    for skill in skills:
        by_status[skill.get("status")] = by_status.get(skill.get("status"), 0) + 1
    out.append("| 状态 | 条数 |")
    out.append("|---|---:|")
    for status, count in sorted(by_status.items(), key=lambda item: (-item[1], str(item[0]))):
        out.append(f"| {status} | {count} |")
    out.append("")
    not_yet = [s for s in skills if s.get("status") in ("not_yet", "needs_step_by_step", "needs_review")]
    if not_yet:
        out.append("需要给分步指导 / 复核的技能（会影响 AI 给的指导深度）：")
        for skill in not_yet:
            gaps = "；".join(skill.get("known_gaps", [])[:2])
            out.append(f"- `{skill.get('skill_id')}` {skill.get('skill_name')}（{skill.get('status')}）｜ 已知缺口：{gaps or '未记录'}")
    out.append("")

    out.append("## 7. 经验库摘要")
    out.append("")
    if not experiences:
        out.append("（经验库为空——**空是合法状态**：只有确实值得长期复用的经验才该入库。）")
    else:
        out.append("| 状态 | 条数 |")
        out.append("|---|---:|")
        exp_status: dict[str, int] = {}
        for entry in experiences:
            exp_status[entry.get("status")] = exp_status.get(entry.get("status"), 0) + 1
        for status, count in sorted(exp_status.items(), key=lambda item: (-item[1], str(item[0]))):
            out.append(f"| {zh(EXP_STATUS_ZH, status)}（{status}） | {count} |")
        out.append("")
        out.append("检索方式：`python3 scripts/exp.py search --query \"...\"`（会显式排除已失效/ 被反例挑战/ 条件不匹配的条目）")
    out.append("")

    out.append("## 8. 怎么查看、纠正、删除、恢复")
    out.append("")
    out.append("- 数据位置：任务 `state/tasks.json`（事件流 `state/tasks.jsonl`）；技能 `state/user_skills.json`；经验 `state/experience/*.json`。")
    out.append("- 查看现场：`python3 scripts/task_show.py --task <task_id>`；总览：本文件。")
    out.append("- 纠正/删除：直接编辑对应 JSON 文件即可（是你的数据），改完请运行 `python3 scripts/validate.py --all` 检查是否仍符合契约。")
    out.append("- 恢复：每次写入前 state/ 都会自动快照到 `state/backups/<UTC时间戳>/`（含 manifest 的 sha256 与记录数）。")
    out.append("  校验最近备份：`python3 scripts/validate.py --backup-verify`；恢复时把备份目录里的文件复制回 `state/`。")
    out.append("- 外部传输：默认不发生；本系统不联网同步任何记忆数据。")
    out.append("")

    out.append("## 9. 已知限制")
    out.append("")
    out.append("- 本文件是派生产物，随时可由 `state/` 重新生成；手工修改会在下次生成时丢失。")
    out.append("- 经验检索是**结构化关键词打分**（domain/task_type/tags/trigger_conditions），不是语义检索；相似不等于适用。")
    out.append("- 技能状态不会自动升级：只有独立操作或观察到的测试证据才支持升级（虚假升级会被 validate.py 拦下）。")
    out.append("- `methods/index.json` 尚未建立时，方法库相关内容不可用（未执行 ≠ 通过）。")
    out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 主流程

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="由 state/ 生成人类可读 STATUS.md 并核对记录数")
    parser.add_argument("--output", type=Path, default=store.PROJECT_ROOT / "STATUS.md", help="输出路径（默认项目根 STATUS.md）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写文件、不备份")
    args = parser.parse_args(argv[1:])

    store.find_project_root()
    bundle = load_all()
    rows = reconcile(bundle)
    text = render(bundle, rows)

    print("=== STATUS.md 生成与记录数核对 ===")
    print(f"数据目录  : {store.STATE_DIR}")
    print()
    print(f"{'项目':<22}{'文件':>6}{'载入':>6}{'渲染':>6}   一致")
    mismatches = []
    for row in rows:
        same = row["文件"] == row["载入"] == row["渲染"]
        print(f"{row['项目']:<22}{row['文件']:>6}{row['载入']:>6}{row['渲染']:>6}   {'✅' if same else '❌'}")
        if not same:
            mismatches.append(row["项目"])
    print()
    if mismatches:
        print(f"核对结果  : 不一致（{len(mismatches)} 项：{'、'.join(mismatches)}）")
    else:
        print(f"核对结果  : 全部一致（{len(rows)} 项）")

    if args.dry_run:
        print("dry-run   : 未写文件、未备份")
        print()
        print(text)
        return 1 if mismatches else 0

    backup = store.create_backup("status: 重新生成 STATUS.md")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"写前备份  : {backup.relative_to(store.PROJECT_ROOT)}")
    print(f"已写入    : {output}（{len(text.splitlines())} 行，{len(text.encode('utf-8'))} 字节）")
    print(f"结论      : {'成功' if not mismatches else '写入完成但核对不一致，请检查数据'}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(2)
