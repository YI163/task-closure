#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_show.py —— 任务现场恢复与状态总览（生命周期 F：跟踪与恢复）。

用法
----
    python3 scripts/task_show.py                # 列出所有进行中的任务
    python3 scripts/task_show.py --all          # 包括已完成/取消的任务
    python3 scripts/task_show.py --task TN-...  # 单个任务完整现场
    python3 scripts/task_show.py --task TN-... --brief   # 只给可粘贴的上下文摘要

设计意图
--------
用户在中断后回来时，**不应该被要求重讲一遍背景**。
本脚本输出的内容就是"系统记得的东西"：已完成（含证据）、未完成、阻碍、未知、决定、
时间线变更与下一步。它不判断、不建议新方向，只如实还原现场。
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
# t21：把「谁来做」直接摆到用户眼前（缺失时如实显示「未声明」而不是假装没这回事）
EXECUTOR_ZH = {"user": "用户做", "ai": "AI 做", "joint": "共同做"}


def line(char: str = "─", width: int = 68) -> str:
    return char * width


def render_summary(tasks: list[dict]) -> None:
    if not tasks:
        print("目前没有任何任务记录。")
        return
    print(line("═"))
    print(f"{'任务编号':<18}{'状态':<10}{'进度':<10}标题")
    print(line("═"))
    for task in tasks:
        done = len(task.get("completed_steps", []))
        total = len(task.get("plan", []))
        print(
            f"{task['task_id']:<18}{STATUS_ZH.get(task['status'], task['status']):<10}"
            f"{f'{done}/{total}':<10}{task['title']}"
        )
    print(line("═"))
    print(f"共 {len(tasks)} 个任务。")


# 硬前置。**写「可照做的动作」，不写标题**。
#
# 为什么这样改（2026-10-15，用户追问促成）：
#   用户问「为什么非要我一直问你规则里怎么写的，你不能自己问自己吗」
#   审计发现：第 4 条「写计划前先读规则」是**半机械**——task_show 只把规则**标题**
#   打出来，从不检查有没有真读过。而第 7/8/9 条（机械强制）从未被违反。
#   实测事故：流程图那条规则（必须渲染、不得手写 ASCII、必须覆盖完整流程）
#   写在 SKILL.md 第 10-2 条**正文**里，而 task_show 只打「流程图」几个字，
#   于是我每次动手前都没看到具体要求，同一件事被用户纠正四次。
#   → 规律：**规则要被遵守，必须送到动手前那一刻，且是完整内容而非标题。**
#   所以这里列的是「可直接照做的检查项」。
# ══ 开工必读（唯一一块）══
#
# 设计原则（2026-10-15 做减法）：
#   ① **一句话一条动作**，不写「为什么单列这条」——那些历史叙述已移到
#      reference/preconditions_history.md（每次开工不需要读）
#   ② 三块（硬前置/搜经验库/交付核对表）**归并成一块**——它们此前各占 10-11 行、内容重叠
#   ③ 已被机械强制的规则（deliver.py 会直接拒绝的）**不在这里重复**——
#      那些绕不过去，讲两遍是浪费注意力
#   ④ 只留「闸门管不到、必须靠我记住」的部分
PRECONDITIONS = [
    "① 先读状态再开口（你正在做）",
    "② 状态变更走 task_update.py，不许只在对话里说「已记录」",
    "③ 不假装：没执行/没核实/不确定的，都标出来",
    "④ 写计划前重读 §0 与 reference/——凭记忆不算",
    "⑤ 主路径不得被后续问答推翻",
    "⑥ 交付前逐条对照本任务 constraints",
]

# 动手前先搜经验库（用户设计流程的必经一步）。
# 查询词实测过三版：完整标题→0 条命中；正则抽词→碎片无意义；固定短词→4/3/3 条。
# **只用实测有效的，不自动生成**——任务专属的查询由执行者自己按内容写。
SEARCH_HINTS = [
    ("交付规矩", "交付 格式 命名 位置"),
    ("范围规矩", "合并 删除 副本 范围"),
    ("检查有效性", "检查 静默 吞掉"),
]

# 闸门管不到、必须靠记住的交付要点。
# **已被 deliver.py 机械强制的不列**（命名/格式/流程图存在性/行动清单/自审/覆盖对照），
# 只列**闸门查不出**的那些。
DELIVERY_MUSTS = [
    "流程图必须**渲染**（flowchart.py），禁止手写 ASCII；且覆盖来源里写明的**全部**环节",
    "各份文档**保持独立**——只做同内容格式去重，不做多文档合并",
    "引用二手/转写素材时，写明其准确率与不确定处",
    "用户说「一个/只留/精简」时：先复述范围，**涉及合并删除宁可不做**",
]


def render_skill_gaps() -> None:
    """打印「此人明确不会／需分步指导的技能」。

    为什么总览与单任务都要打印（2026-10-15 修）：
    执行者通常先跑不带参数的 task_show 看全局，此时若不打印，
    就仍然不知道「该教还是该替」——而这个信息是决定指导深度的唯一依据。
    """
    try:
        skills = store.load_skills().get("skills", [])
    except Exception:
        skills = []
    needs_help = [s for s in skills
                  if s.get("status") in ("not_yet", "needs_step_by_step", "needs_review")]
    if not needs_help:
        return
    print()
    print("【此人明确不会／需分步指导的技能（决定该教还是该替）】")
    for s in needs_help:
        name = s.get("skill_name", s.get("skill_id", "?"))
        gaps = "；".join((s.get("known_gaps") or [])[:1])
        print(f"  · {name}（{s.get('status')}）" + (f"　已知缺口：{gaps}" if gaps else ""))
    print("  → 涉及这些技能的任务步骤，默认「用户做、AI 指导」，不要默认代做")


def render_preconditions() -> None:
    """把「开工必读」打到执行者眼前。**不依赖具体任务**——总览与单任务模式都要打。

    为什么放在这里：实测发现「规则写在文件里」并不等于「执行时会看」。
    本函数挂在 task_show.py 上——而第①条硬前置要求每次任务对话先跑它，
    因此这是唯一能保证规则被送到执行者眼前的挂点。
    """
    print(line("─"))
    print("【开工必读】")
    for item in PRECONDITIONS:
        print(f"  {item}")
    print()
    print("  动手前先搜经验库（不搜就动手 = 违反）。实测有效的查询：")
    for label, q in SEARCH_HINTS:
        print(f"    · {label}：exp.py search --query \"{q}\"")
    print(f"    · 或按本任务主题自拟（用短词，长句搜不到；无命中也是合法结果）")
    print()
    print("  闸门查不出、必须记住的交付要点：")
    for item in DELIVERY_MUSTS:
        print(f"    · {item}")
    print(line("─"))
    print()


def render_detail(task: dict, brief: bool) -> None:
    done = len(task.get("completed_steps", []))
    total = len(task.get("plan", []))

    print(line("═"))
    print(f"任务 {task['task_id']}：《{task['title']}》")
    print(line("═"))
    print(f"状态        : {STATUS_ZH.get(task['status'], task['status'])}")
    print(f"领域/类型   : {task['domain']} / {task['task_type']}")
    print(f"规划深度    : {task['planning_depth']}")
    print(f"进度        : {done}/{total} 步完成")
    print(f"期限        : {task.get('deadline') or '未设定'}")
    print(f"创建/更新   : {task.get('created_at')} → {task.get('updated_at')}")
    if task.get("closed_at"):
        print(f"关闭时间    : {task['closed_at']}    验收结论：{task.get('verdict', '（无）')}")
    print(f"复盘状态    : {RETRO_ZH.get(task.get('retrospective_status'), task.get('retrospective_status'))}")

    print(f"\n■ 原始请求（用户原话，未经改写）\n  {task['original_request']}")
    print(f"\n■ 任务目标\n  {task['goal']}")
    if task.get("requester_or_beneficiary"):
        print(f"\n■ 提出/使用结果的人\n  {task['requester_or_beneficiary']}")
    print("\n■ 完成标准（判断任务是否成功的依据）")
    for index, criterion in enumerate(task.get("success_criteria", []), start=1):
        print(f"  {index}. {criterion}")

    if brief:
        print("\n■ 下一步最值得做什么")
        action = task.get("next_best_action") or {}
        print(f"  {action.get('action', '（未设定）')}")
        print(f"  理由：{action.get('reason', '（未说明）')}")
        print(line("═"))
        return

    print("\n■ 计划与逐步状态")
    completed = {c.get("step_id"): c for c in task.get("completed_steps", [])}
    for step in task.get("plan", []):
        mark = "✔" if step.get("status") == "done" else ("▶" if step.get("status") == "in_progress" else "○")
        print(f"  {mark} {step['step_id']} {step['name']}  [{STEP_ZH.get(step.get('status'), step.get('status'))}]")
        executor_line = EXECUTOR_ZH.get(step.get("executor"), "（未声明执行者）")
        if step.get("executor_basis"):
            executor_line += f"（依据：{step['executor_basis']}）"
        if step.get("executor") == "ai" and step.get("delegation_reason"):
            executor_line += f"｜代做理由：{step['delegation_reason']}"
        print(f"      执行者：{executor_line}")
        print(f"      目的：{step.get('purpose')}")
        if step.get("deliverable"):
            print(f"      产出：{step['deliverable']}")
        if step.get("completion_criteria"):
            print(f"      完成标准：{step['completion_criteria']}")
        if step.get("time_estimate"):
            basis = step.get("estimate_basis")
            print(f"      预计耗时：{step['time_estimate']}" + (f"（依据：{basis}）" if basis else ""))
        if step.get("inputs_or_dependencies"):
            print(f"      前置：{'；'.join(map(str, step['inputs_or_dependencies']))}")
        skills = step.get("required_skills") or []
        if skills:
            readable = [
                f"{s.get('skill_ref') or s.get('skill_id') or s.get('free_text')}"
                + (f"（缺口：{s.get('gap')} → {s.get('adaptation')}）" if s.get("adaptation") else "")
                for s in skills
            ]
            print(f"      技能：{'；'.join(readable)}")
        for risk in step.get("risks_and_fallbacks") or []:
            print(f"      风险/备用：{risk}")
        for comm in step.get("communication") or []:
            print(f"      沟通点：{comm}")
        record = completed.get(step.get("step_id"))
        if record:
            print(f"      ✅ 完成证据：{record.get('evidence')}")

    print("\n■ 已完成步骤及证据")
    if not task.get("completed_steps"):
        print("  （暂无）")
    for record in task.get("completed_steps", []):
        print(f"  · {record['step_id']} @ {record['completed_at']}")
        print(f"    证据：{record['evidence']}")
        if record.get("notes"):
            print(f"    备注：{record['notes']}")
        if record.get("verification"):
            print(f"    验证方式：{record['verification']}")

    print("\n■ 未完成步骤")
    pending = [s for s in task.get("plan", []) if s.get("status") != "done"]
    if not pending:
        print("  （无）")
    for step in pending:
        who = EXECUTOR_ZH.get(step.get("executor"), "（未声明执行者）")
        print(f"  · {step['step_id']} {step['name']}　→ {who}")

    print("\n■ 阻碍")
    open_blockers = [b for b in task.get("blockers", []) if not b.get("resolved_at")]
    if not open_blockers:
        print("  （无未解除阻碍）")
    for blocker in open_blockers:
        print(f"  ! {blocker['blocker_id']} {blocker['description']}")
        if blocker.get("impact"):
            print(f"    影响：{blocker['impact']}")
        if blocker.get("fallback"):
            print(f"    备用路径：{blocker['fallback']}")

    print("\n■ 未解决的未知项")
    # 兼容两种历史写法：契约要求的对象，以及早期误写成纯字符串的情况。
    # 坏数据必须显示出来，而不是让工具崩溃——现场恢复工具挂掉，用户就看不到任何东西了。
    open_unknowns = []
    for index, unknown in enumerate(task.get("unknowns", []), start=1):
        if isinstance(unknown, dict):
            if not unknown.get("resolved_at"):
                open_unknowns.append(unknown)
        elif unknown:
            open_unknowns.append({"_raw": str(unknown), "unknown_id": f"(第{index}项·格式不合契约)"})
    if not open_unknowns:
        print("  （无）")
    for unknown in open_unknowns:
        if "_raw" in unknown:
            print(f"  ? {unknown['unknown_id']} {unknown['_raw']}")
            continue
        # unknowns 的实际契约以 question 作正文字段（见 state/tasks.json）；
        # 早期写法是 unknown_id/description。两者都认，缺失时显式降级而不是抛 KeyError
        # ——同一条「坏数据要显示出来，而不是让现场恢复工具崩溃」的理由。
        unknown_id = unknown.get("unknown_id") or unknown.get("id") or "(未编号)"
        body = unknown.get("question") or unknown.get("description")
        if not body:
            body = f"(字段不合契约，原文：{unknown})"
        print(f"  ? {unknown_id} {body}")
        if unknown.get("why_it_matters"):
            print(f"    为什么重要：{unknown['why_it_matters']}")
        if unknown.get("how_to_verify"):
            print(f"    如何核实：{unknown['how_to_verify']}")

    print("\n■ 已做的决定")
    if not task.get("decisions"):
        print("  （暂无）")
    for decision in task.get("decisions", []):
        print(f"  · {decision.get('decided_at')} {decision['what']}（原因：{decision['why']}）")

    print("\n■ 计划变更记录（为什么计划不是原来那样）")
    if not task.get("changes"):
        print("  （计划未变更过）")
    for change in task.get("changes", []):
        print(f"  · {change.get('changed_at')} {change['what']}")
        print(f"    原因：{change['why']}    影响：{change['impact']}")

    print("\n■ 证据清单")
    if not task.get("evidence"):
        print("  （暂无）")
    for evidence in task.get("evidence", []):
        print(f"  · [{evidence.get('kind')}] {evidence.get('evidence_id')} {evidence.get('description')}")

    print(f"\n■ 下一步最值得做什么")
    action = task.get("next_best_action") or {}
    print(f"  {action.get('action', '（未设定）')}")
    print(f"  理由：{action.get('reason', '（未说明）')}")

    print("\n■ 最近变更时间线（最后 8 条）")
    for entry in task.get("history", [])[-8:]:
        print(f"  · {entry.get('at')} [{entry.get('action')}] {entry.get('summary')}")
    print(line("═"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="恢复任务现场 / 查看任务总览")
    parser.add_argument("--task", help="task_id 或标题关键词；省略则列出总览")
    parser.add_argument("--all", action="store_true", help="总览中包含已完成/取消的任务")
    parser.add_argument("--brief", action="store_true", help="只输出可粘贴的上下文摘要")
    args = parser.parse_args(argv[1:])

    store.find_project_root()
    data = store.load_tasks()
    tasks = data["tasks"]

    if not tasks:
        print("目前没有任何任务记录。可以直接用自然语言告诉我你要做的事，我会先厘清目标再建档。")
        return 0

    # ══ 开工必读：**两种模式都要打** ══
    # 为什么改成在分支之前无条件调用（2026-10-16 修 bug）：
    #  此前它只在 render_detail（带 --task）里打，**总览模式完全没有**。
    #  而我通常先跑总览看有哪些任务——于是最该读的那块，在我最常用的模式里不出现。
    #  实测后果：2026-10-15 那个会话里，用户问「你在用那个 skill 吗」，
    #  根因就是我跑总览时没看到「开工必读」，于是没走流程。
    #  这块不依赖具体任务（constraints 由 render_detail 单独打），所以可以无条件调。
    render_preconditions()
    render_skill_gaps()

    if args.task:
        task = store.resolve_task(tasks, args.task)
        render_detail(task, args.brief)
        return 0

    visible = tasks if args.all else [t for t in tasks if t["status"] not in ("completed", "cancelled")]
    render_summary(visible)
    if not args.all:
        hidden = len(tasks) - len(visible)
        if hidden:
            print(f"（另有 {hidden} 个已完成/已取消的任务，用 --all 查看）")
    return 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(1)
