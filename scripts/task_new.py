#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_new.py —— 接收一个任务并建立任务记录（生命周期 A/B/E 阶段的落盘动作）。

用法
----
    python3 scripts/task_new.py --input <task.json> [--domain work] [--task-type research] [--planning-depth standard]

`--input` 指向一个 UTF-8 JSON 文件，字段见下（未提供的可选字段会补成契约要求的默认值）：

必填：title, original_request, goal, success_criteria
可选：requester_or_beneficiary, decision_authority, deadline, constraints, assumptions, unknowns,
      deliverables, plan, evidence, domain, task_type, planning_depth

`plan` 为步骤数组，standard/deep 深度下每个步骤必须包含：
    name, purpose, actions, required_skills, deliverable, completion_criteria
可选步骤字段：inputs_or_dependencies, time_estimate, estimate_basis,
      risks_and_fallbacks, communication, status

脚本只负责"把已决定的东西如实落盘"；判断（任务类型、复杂度、方法论）由 Skill 层负责。

字段约定（schema 1.1）：`plan[].required_skills` 一律写 `skill_ref`（可指向技能档案里的
skill_id，也可以是描述性自由文本）。输入里若仍用历史写法 `skill_id` / `free_text`，
本脚本会**自动归一为 skill_ref 并如实打印**；但不会因此放宽必填校验——
三种写法一个都没有时仍然拒绝建档。
脚本不会替用户编造事实：缺必填字段就报错退出，不做静默补全。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

REQUIRED_INPUT = ("title", "original_request", "goal", "success_criteria")
STEP_REQUIRED = ("name", "purpose", "actions", "required_skills", "deliverable", "completion_criteria")
DEPTHS = ("light", "standard", "deep")
# t21：执行者机械门禁（SKILL.md §0.4.1 计划自检表 / reference/skill_adaptation.md §6.1）
# 「缺执行者视为计划不完整」——规则写在文件里不算执行，写进这里才算。
EXECUTORS = ("user", "ai", "joint")
EXECUTOR_ZH = {"user": "用户做", "ai": "AI 代做", "joint": "共同做"}
DELEGATION_REASONS = ("极紧期限", "高代价", "纯机械劳动", "用户明确要求")


def die(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(2)


def load_input(path: Path) -> dict:
    if not path.exists():
        die(f"输入文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"输入文件不是合法 JSON：{path}（{exc}）")
    if not isinstance(payload, dict):
        die("输入文件的顶层必须是 JSON 对象。")
    return payload


def normalise_plan(raw_plan, depth: str) -> tuple[list[dict], list[tuple]]:
    """归一化 plan：其中 required_skills 一律改写成 skill_ref（兼容历史写法）。

    返回 (steps, normalised)。normalised 记录「第几步 / 哪个旧字段名 / 什么值」被归一，
    供建档时如实打印——不静默改写用户输入。
    """
    if raw_plan is None:
        raw_plan = []
    if not isinstance(raw_plan, list):
        die("plan 必须是数组。")

    steps: list[dict] = []
    normalised: list[tuple] = []
    for index, raw in enumerate(raw_plan, start=1):
        if not isinstance(raw, dict):
            die(f"plan 第 {index} 项必须是对象。")
        step = dict(raw)
        step.setdefault("step_id", f"S{index}")
        # 档位只控制「规划成本与结构完整度」，不豁免「步骤必须有动作」（G2 修复）：
        # light 允许省略 purpose/deliverable/completion_criteria，但 name 与 actions 必须有实质内容；
        # 这与 validate.py 对 light 步骤的必填集合（step_id/name/actions）保持一致，
        # 避免写入路径产出自家校验器判定为 T-STEP-REQ 的数据。
        required_fields = ("name", "actions") if depth == "light" else STEP_REQUIRED
        for field in required_fields:
            if not step.get(field):
                die(
                    f"plan 第 {index} 步缺少必填字段 {field}"
                    + (
                        "（light 深度可省略 purpose/deliverable/completion_criteria，"
                        "但 name 与 actions 不能为空——没有动作的步骤不是步骤）"
                        if depth == "light"
                        else f"（{depth} 深度要求完整字段：只有 light 深度允许省略"
                        " purpose/deliverable/completion_criteria 等）"
                    )
                )
        # 列表字段类型校验：与 validate.py 同一套判断标准（字符串/对象会被校验器判为违规）
        for field in ("actions", "required_skills", "inputs_or_dependencies",
                      "risks_and_fallbacks", "communication", "depends_on_step_ids"):
            if field in step and not isinstance(step[field], list):
                die(f"plan 第 {index} 步的 {field} 必须是数组，收到 {type(step[field]).__name__}。")

        # t21：每一步必须表态「谁来做」；AI 代做必须写明理由。
        # 与档位无关——light 也强制：没有动作的步骤不是步骤，没有执行者的步骤同样不是。
        executor = step.get("executor")
        if not executor:
            die(
                f"plan 第 {index} 步缺少必填字段 executor（谁来做？"
                "user=用户做 / ai=AI 代做 / joint=共同做）"
                "——缺执行者视为计划不完整，先想清楚这一步该谁做再建档。"
            )
        if executor not in EXECUTORS:
            die(f"plan 第 {index} 步的 executor 必须是 {EXECUTORS} 之一，收到 {executor!r}。")
        if not step.get("executor_basis"):
            die(
                f"plan 第 {index} 步缺少必填字段 executor_basis（为什么由该方执行）"
                "——默认规则：用户自己的生活/工作/学习事务默认用户做、AI 指导；"
                "只写执行者名字不算表态。"
            )
        reason = step.get("delegation_reason")
        if executor == "ai":
            if not reason:
                die(
                    f"plan 第 {index} 步 executor=ai 时必须写明 delegation_reason"
                    f"（四选一：{'/'.join(DELEGATION_REASONS)}）——AI 代做必须有理由。"
                )
            if reason not in DELEGATION_REASONS:
                die(
                    f"plan 第 {index} 步的 delegation_reason 必须是 {DELEGATION_REASONS} 之一，"
                    f"收到 {reason!r}。"
                )
        elif reason:
            die(
                f"plan 第 {index} 步 executor={executor!r} 却写了 delegation_reason={reason!r}"
                "——那是 AI 代做的理由，请二选一：去掉理由，或把 executor 改成 ai。"
            )
        step.setdefault("required_skills", [])
        for skill in step["required_skills"]:
            if not isinstance(skill, dict):
                die(f"plan 第 {index} 步的 required_skills 每项必须是对象。")
            # schema 1.1：一律写 skill_ref（可指向档案 skill_id，也可以是描述性自由文本）。
            # 兼容读取历史写法 skill_id / free_text 并自动归一，但不放宽必填校验：
            # 三种写法一个都没有（或值为空）时仍然拒绝建档。
            ref = skill.get("skill_ref") or skill.get("skill_id") or skill.get("free_text")
            if not ref:
                die(
                    f"plan 第 {index} 步的 required_skills 每项必须含 skill_ref"
                    "（也接受历史写法 skill_id / free_text，会自动归一为 skill_ref）——信息不全时不得建档。"
                )
            if not skill.get("skill_ref"):
                normalised.append(
                    (index, "skill_id" if skill.get("skill_id") else "free_text", str(ref))
                )
            for legacy in ("skill_id", "free_text"):
                skill.pop(legacy, None)
            skill["skill_ref"] = ref
        step.setdefault("status", "pending")

        # G4（spec/01 §4E）：standard/deep 下这四项必须有内容或显式写「不适用」+理由。
        # 实测依据：此前这四项可选，32 个步骤里 risks_and_fallbacks 有内容的仅 9 条（28%）、
        # communication 仅 8 条（25%）——「可选」的实际后果就是基本没人填。
        if depth != "light":
            for field in ("inputs_or_dependencies", "risks_and_fallbacks", "communication"):
                values = step.get(field) or []
                if not values:
                    die(
                        f"plan 第 {index} 步缺少必填字段 {field}（{depth} 深度要求每步完整）。"
                        f"确实不适用时请显式写明理由，例如 "
                        f"{field}=[\"不适用：本步无需对外沟通\"]，但不要留空。"
                    )
            if not step.get("time_estimate"):
                die(
                    f"plan 第 {index} 步缺少必填字段 time_estimate（{depth} 深度要求每步给出预计耗时）。"
                    "不确定时写区间并给出估算依据，不要留空。"
                )
        if depth in ("standard", "deep") and not step.get("time_estimate"):
            # 允许缺省，但必须显式标注这是估算假设，避免假装精确
            step["time_estimate"] = "未估算"
            step["estimate_basis"] = "本次未做时间估算（避免无依据的精确数字）"
        steps.append(step)

    # 步骤依赖（schema 1.8）：写入侧也挡一次——未知/自依赖/重复必须在建档时拒绝，
    # 而不是等校验器报错或让 next_best_action 永远卡住。
    # 数据契约：depends_on_step_ids 是调度依赖（精确 step_id）；
    # inputs_or_dependencies 是自然语言的前置说明，不参与阻塞判断。
    plan_step_ids = {str(item.get("step_id")) for item in steps}
    for index, step in enumerate(steps, start=1):
        deps = step.get("depends_on_step_ids")
        if deps is None:
            continue
        seen: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str) or not dep.strip():
                die(f"plan 第 {index} 步的 depends_on_step_ids 每项必须是非空字符串（步骤 ID）。")
            if dep == str(step.get("step_id")):
                die(f"plan 第 {index} 步不能依赖自己（{dep}）——那会让它永远无法开始。")
            if dep not in plan_step_ids:
                known = "、".join(sorted(plan_step_ids)) or "（无）"
                die(f"plan 第 {index} 步依赖的步骤 {dep!r} 不存在。已知步骤：{known}")
            if dep in seen:
                die(f"plan 第 {index} 步的依赖 {dep!r} 重复登记。")
            seen.add(dep)
    return steps, normalised


def build_task(payload: dict, task_id: str) -> dict:
    depth = payload.get("planning_depth", "standard")
    if depth not in DEPTHS:
        die(f"planning_depth 必须是 {DEPTHS} 之一，收到 {depth!r}。")

    for field in REQUIRED_INPUT:
        value = payload.get(field)
        if value in (None, "", [], {}):
            die(f"输入缺少必填字段 {field}。任务信息不完整时不得建档——缺什么就问用户什么。")

    normalised_plan, normalised_skills = normalise_plan(payload.get("plan"), depth)
    timestamp = store.now_iso()
    task = {
        "task_id": task_id,
        "title": payload["title"],
        "original_request": payload["original_request"],
        "domain": payload.get("domain", "other"),
        "task_type": payload.get("task_type", "other"),
        "goal": payload["goal"],
        "requester_or_beneficiary": payload.get("requester_or_beneficiary"),
        # spec/01 §4A：有外部发起人时应记录决策权限。
        # 此前 task_new 完全不处理该字段 → 传了也被静默丢弃 →
        # 与 validate.py 的 T-DECISION-AUTH 冲突（要求填，但建档时填不进去）
        "decision_authority": payload.get("decision_authority"),
        "success_criteria": payload["success_criteria"],
        "deadline": payload.get("deadline"),
        "constraints": payload.get("constraints", []),
        "assumptions": payload.get("assumptions", []),
        "unknowns": payload.get("unknowns", []),
        "planning_depth": depth,
        "plan": normalised_plan,
        "deliverables": payload.get("deliverables", []),
        "status": payload.get("status", "not_started"),
        "completed_steps": [],
        "evidence": payload.get("evidence", []),
        "decisions": payload.get("decisions", []),
        "risks": payload.get("risks", []),
        "blockers": payload.get("blockers", []),
        "changes": payload.get("changes", []),
        "next_best_action": payload.get(
            "next_best_action",
            {"action": "确认任务理解是否准确", "reason": "任务刚建立，先让用户确认目标与完成标准再投入执行"},
        ),
        "retrospective_status": "not_reviewed",
        "history": [{"at": timestamp, "action": "created", "summary": "建立任务记录"}],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if not isinstance(task["success_criteria"], list) or not task["success_criteria"]:
        die("success_criteria 必须是非空数组——没有可判断的完成标准就不算一个任务。")
    task["_normalised_skills"] = normalised_skills  # 供 main 打印后丢弃，不写入数据
    return task


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="建立一个新的 任务导航 任务记录")
    parser.add_argument("--input", required=True, type=Path, help="任务内容 JSON 文件")
    parser.add_argument("--domain", help="work/life/study/personal_project/other")
    parser.add_argument("--task-type", dest="task_type", help="research/decision/execution/writing/coordination/learning/admin/other")
    parser.add_argument("--planning-depth", dest="planning_depth", help="light/standard/deep")
    parser.add_argument("--id", dest="forced_id", help="强制指定 task_id（仅测试用）")
    args = parser.parse_args(argv[1:])

    store.find_project_root()
    payload = load_input(args.input)
    if args.domain:
        payload["domain"] = args.domain
    if args.task_type:
        payload["task_type"] = args.task_type
    if args.planning_depth:
        payload["planning_depth"] = args.planning_depth

    data = store.load_tasks()
    task_id = args.forced_id or store.next_task_id(data["tasks"])
    if any(t.get("task_id") == task_id for t in data["tasks"]):
        die(f"task_id {task_id} 已存在。")

    task = build_task(payload, task_id)
    normalised_skills = task.pop("_normalised_skills", [])
    data["tasks"].append(task)
    backup = store.save_tasks(data, f"新建任务 {task_id}")
    store.append_event(task_id, "created", {"title": task["title"], "depth": task["planning_depth"]})

    print(f"已建立任务 {task_id}：《{task['title']}》")
    print(f"  规划深度：{task['planning_depth']}    步骤数：{len(task['plan'])}")
    print(f"  领域/类型：{task['domain']} / {task['task_type']}")
    print(f"  写前备份：{backup.relative_to(store.PROJECT_ROOT)}")
    print(f"  下一步建议：{task['next_best_action']['action']}")
    if normalised_skills:
        listing = "；".join(f"S{index}.{field}={value}" for index, field, value in normalised_skills)
        print(f"  字段归一：{len(normalised_skills)} 条 required_skills 的历史写法已归一为 skill_ref（{listing}）")
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
