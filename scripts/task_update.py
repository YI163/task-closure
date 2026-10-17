#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_update.py —— 把用户的自然语言更新如实映射成任务状态变更。

对应生命周期 F（执行、跟踪与恢复）与 D（技能缺口）、E（重规划）。

用法
----
    python3 scripts/task_update.py step    --task TN-20261014-001 --file done.json
    python3 scripts/task_update.py evidence--task TN-20261014-001 --file ev.json
    python3 scripts/task_update.py decision--task TN-20261014-001 --file dec.json
    python3 scripts/task_update.py blocker --task TN-20261014-001 --file blk.json
    python3 scripts/task_update.py change  --task TN-20261014-001 --file chg.json
    python3 scripts/task_update.py next    --task TN-20261014-001 --file next.json
    python3 scripts/task_update.py status  --task TN-20261014-001 --file st.json
    python3 scripts/task_update.py unknown --task TN-20261014-001 --file unk.json
    python3 scripts/task_update.py skillgap--task TN-20261014-001 --file gap.json
    python3 scripts/task_update.py close   --task TN-20261014-001 --file close.json

硬规则（由脚本强制，不靠模型自觉）
--------------------------------
* 标记步骤完成必须提供非空 evidence —— 没有证据不得算完成；
* 已完成的步骤不能重复标记（防止把同一件事重复算作进展）；
* 重规划必须写明 what/why/impact 并追加到 changes，旧计划不被静默覆盖；
* 状态改为 completed 必须经过 close 子命令（三问验收），不能直接改；
* 技能需求一律写 skill_ref（schema 1.1）；历史写法 skill_id / free_text 会被自动归一并提示，
  但信息不全（三种写法都没有）仍然拒绝写入；
* 每次写入前自动备份。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402
import task_new  # noqa: E402  —— 复用建档侧的 plan 校验/归一（G1 修复：写入路径只允许一套判断标准）

ALLOWED_STATUS = (
    "not_started", "in_progress", "waiting_external", "blocked",
    "awaiting_acceptance", "completed", "cancelled",
)
NON_TERMINAL = ("not_started", "in_progress", "waiting_external", "blocked", "awaiting_acceptance")


def die(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(2)


def load_payload(path: Path) -> dict:
    if not path.exists():
        die(f"输入文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"输入文件不是合法 JSON：{path}（{exc}）")
    if not isinstance(payload, dict):
        die("输入文件的顶层必须是 JSON 对象。")
    return payload


def require(payload: dict, *fields: str) -> None:
    missing = [f for f in fields if payload.get(f) in (None, "", [], {})]
    if missing:
        die(f"缺少必填字段：{', '.join(missing)}（信息不全时不得写入猜测值）")


def step_by_id(task: dict, step_id: str) -> dict:
    for step in task.get("plan", []):
        if step.get("step_id") == step_id:
            return step
    known = ", ".join(s.get("step_id", "?") for s in task.get("plan", []))
    die(f"任务 {task['task_id']} 中没有步骤 {step_id}。已知步骤：{known or '（无）'}")


def recompute_next_action(task: dict) -> None:
    """按现状推导下一步建议（不是硬编码答案，而是从状态里读出来的）。"""
    if task.get("status") == "awaiting_acceptance":
        acceptance = task.get("acceptance") or {}
        external = acceptance.get("pending_external") or []
        pending_steps = [s for s in task.get("plan", []) if s.get("status") not in ("done", "skipped")]
        if external:
            task["next_best_action"] = {
                "action": "等待并跟催外部确认：" + "；".join(map(str, external)),
                "reason": "我方交付已完成，但目标是否实现取决于他人决定；在对方确认前不得宣称任务完成",
            }
            if pending_steps:
                task["next_best_action"]["action"] += (
                    "（注意：计划中仍有未完成步骤 "
                    + "、".join(s.get("step_id", "?") for s in pending_steps)
                    + "，需与用户确认这些是否已实际完成）"
                )
            return
        task["next_best_action"] = {
            "action": "与用户确认最终结论后收尾",
            "reason": "我方工作已完成，正在等待目标是否实现的判断",
        }
        return

    pending = [s for s in task.get("plan", []) if s.get("status") not in ("done", "skipped")]
    done_ids = {c.get("step_id") for c in task.get("completed_steps", [])}
    for step in pending:
        if step.get("step_id") in done_ids:
            continue
        blocked_by = [d for d in step.get("inputs_or_dependencies", []) if d]
        unmet = [d for d in blocked_by if not any(str(d) in str(c) for c in done_ids)]
        if unmet:
            task["next_best_action"] = {
                "action": f"先完成前置条件：{', '.join(map(str, unmet))}",
                "reason": f"步骤 {step['step_id']}《{step.get('name')}》被依赖阻塞，跳过前置会返工",
            }
            return
        task["next_best_action"] = {
            "action": f"{step.get('step_id')} {step.get('name')}",
            "reason": "这是当前计划中最早未完成且前置已满足的步骤",
        }
        return
    if any(t.get("status") not in ("completed", "cancelled") for t in [task]):
        task["next_best_action"] = {
            "action": "进入验收：逐条核对成功标准",
            "reason": "计划中的步骤都已处理，接下来要判断目标是否真正实现",
        }


def cmd_step(task: dict, payload: dict) -> list[str]:
    require(payload, "step_id", "evidence")
    step = step_by_id(task, payload["step_id"])
    if step.get("status") == "done" or any(
        c.get("step_id") == payload["step_id"] for c in task["completed_steps"]
    ):
        die(f"步骤 {payload['step_id']} 已经标记完成，不重复记录（避免把同一进展算两次）。")

    record = {
        "step_id": payload["step_id"],
        "completed_at": store.now_iso(),
        "evidence": payload["evidence"],
        "notes": payload.get("notes"),
    }
    if payload.get("actual_duration"):
        record["actual_duration"] = payload["actual_duration"]
    task["completed_steps"].append(record)
    step["status"] = "done"
    if payload.get("evidence_id"):
        task["evidence"].append(
            {
                "evidence_id": payload["evidence_id"],
                "kind": payload.get("evidence_kind", "other"),
                "description": payload["evidence"],
                "source": payload.get("source"),
                "recorded_at": record["completed_at"],
            }
        )
    if task["status"] == "not_started":
        task["status"] = "in_progress"

    # 用户在指导下完成一次 → 只记 guided_practice，绝不自动升级技能状态
    verification = payload.get("verification")
    if verification:
        record["verification"] = verification
    return [f"步骤 {payload['step_id']} 已标记完成，证据：{payload['evidence']}"]


def cmd_evidence(task: dict, payload: dict) -> list[str]:
    require(payload, "description")
    entry = {
        "evidence_id": payload.get("evidence_id") or f"EV-{len(task['evidence']) + 1:03d}",
        "kind": payload.get("kind", "other"),
        "description": payload["description"],
        "source": payload.get("source"),
        "recorded_at": store.now_iso(),
    }
    if any(e.get("evidence_id") == entry["evidence_id"] for e in task["evidence"]):
        die(f"证据编号 {entry['evidence_id']} 已存在，不覆盖已有证据。")
    task["evidence"].append(entry)
    return [f"已记录证据 {entry['evidence_id']}：{entry['description']}"]


def cmd_decision(task: dict, payload: dict) -> list[str]:
    require(payload, "what", "why")
    task["decisions"].append(
        {
            "decided_at": store.now_iso(),
            "what": payload["what"],
            "why": payload["why"],
            "alternatives_considered": payload.get("alternatives_considered", []),
            "decided_by": payload.get("decided_by", "user"),
        }
    )
    return [f"已记录决定：{payload['what']}"]


def cmd_blocker(task: dict, payload: dict) -> list[str]:
    action = payload.get("action", "add")
    if action == "resolve":
        require(payload, "blocker_id")
        for blocker in task["blockers"]:
            if blocker.get("blocker_id") == payload["blocker_id"]:
                blocker["resolved_at"] = store.now_iso()
                blocker["resolution"] = payload.get("resolution", "（未说明）")
                return [f"阻碍 {payload['blocker_id']} 已解除：{blocker['resolution']}"]
        die(f"找不到阻碍 {payload['blocker_id']}")

    require(payload, "description")
    blocker_id = payload.get("blocker_id") or f"BL-{len(task['blockers']) + 1:03d}"
    task["blockers"].append(
        {
            "blocker_id": blocker_id,
            "description": payload["description"],
            "impact": payload.get("impact"),
            "raised_at": store.now_iso(),
            "resolved_at": None,
            "resolution": None,
            "fallback": payload.get("fallback"),
        }
    )
    if task["status"] in ("not_started", "in_progress") and payload.get("hard", False):
        task["status"] = "blocked"
    return [f"已记录阻碍 {blocker_id}：{payload['description']}"]


def cmd_change(task: dict, payload: dict) -> list[str]:
    require(payload, "what", "why", "impact")

    # G1 修复：替换计划**之前**先按建档侧同一套规则校验（含 light/standard/deep 档位差异），
    # 校验失败即 die(2) 且不触碰 task 的任何字段——写入路径不得产出自家校验器拒绝的数据。
    new_plan: list[dict] | None = None
    plan_note = ""
    if "plan" in payload:
        depth = task.get("planning_depth", "standard")
        new_plan, normalised = task_new.normalise_plan(payload["plan"], depth)
        if not new_plan:
            die("新的计划不能为空数组——重规划必须给出可执行的步骤。")
        if normalised:
            listing = "；".join(f"S{index}.{field}={value}" for index, field, value in normalised)
            plan_note = f"（{len(normalised)} 条 required_skills 的历史写法已归一为 skill_ref：{listing}）"

    task["changes"].append(
        {
            "changed_at": store.now_iso(),
            "what": payload["what"],
            "why": payload["why"],
            "impact": payload["impact"],
            "trigger": payload.get("trigger"),
            "quality_floor": payload.get("quality_floor"),
        }
    )
    messages = [f"已记录变更：{payload['what']}（原因：{payload['why']}）"]

    if payload.get("new_deadline"):
        task["deadline"] = payload["new_deadline"]
        messages.append(f"期限已更新为 {payload['new_deadline']}")

    if new_plan is not None:
        if payload.get("archive_plan", True):
            task.setdefault("plan_history", []).append(
                {"archived_at": store.now_iso(), "reason": payload["why"], "plan": task["plan"]}
            )
        task["plan"] = new_plan
        messages.append(f"计划已替换（旧计划已归档，共 {len(task['plan'])} 步）{plan_note}")

    if payload.get("status"):
        if payload["status"] not in ALLOWED_STATUS:
            die(f"status 必须是 {ALLOWED_STATUS} 之一")
        task["status"] = payload["status"]
        messages.append(f"任务状态已改为 {payload['status']}")

    return messages


def cmd_next(task: dict, payload: dict) -> list[str]:
    require(payload, "action", "reason")
    task["next_best_action"] = {"action": payload["action"], "reason": payload["reason"]}
    return [f"下一步建议已更新：{payload['action']}"]


def cmd_status(task: dict, payload: dict) -> list[str]:
    require(payload, "status")
    new_status = payload["status"]
    if new_status not in ALLOWED_STATUS:
        die(f"status 必须是 {ALLOWED_STATUS} 之一")
    if new_status == "completed":
        die("不允许用 status 直接结束任务。完成必须走 close 子命令，逐条核对成功标准（防止把勾选步骤当成目标达成）。")
    if new_status == "cancelled":
        require(payload, "reason")
        task["changes"].append(
            {
                "changed_at": store.now_iso(),
                "what": "任务取消",
                "why": payload["reason"],
                "impact": "任务不再推进",
                "trigger": "user_cancel",
            }
        )
    task["status"] = new_status
    return [f"任务状态已改为 {new_status}"]


def cmd_unknown(task: dict, payload: dict) -> list[str]:
    action = payload.get("action", "add")
    if action == "resolve":
        require(payload, "unknown_id")
        for item in task["unknowns"]:
            if item.get("unknown_id") == payload["unknown_id"]:
                item["resolved_at"] = store.now_iso()
                item["resolution"] = payload.get("resolution", "（未说明）")
                if payload.get("became_fact"):
                    task["evidence"].append(
                        {
                            "evidence_id": payload.get("evidence_id", f"EV-{len(task['evidence']) + 1:03d}"),
                            "kind": "fact_check",
                            "description": payload["resolution"],
                            "source": payload.get("source"),
                            "recorded_at": store.now_iso(),
                        }
                    )
                return [f"未知项 {payload['unknown_id']} 已解决：{item['resolution']}"]
        die(f"找不到未知项 {payload['unknown_id']}")
    require(payload, "description")
    unknown_id = payload.get("unknown_id") or f"UN-{len(task['unknowns']) + 1:03d}"
    task["unknowns"].append(
        {
            "unknown_id": unknown_id,
            "description": payload["description"],
            "why_it_matters": payload.get("why_it_matters"),
            "how_to_verify": payload.get("how_to_verify"),
            "raised_at": store.now_iso(),
            "resolved_at": None,
            "resolution": None,
        }
    )
    return [f"已记录未知项 {unknown_id}：{payload['description']}"]


def cmd_skillgap(task: dict, payload: dict) -> list[str]:
    """记录某步骤的技能需求与是否缺口；不改个人技能档案的状态（那是 skills.py 的门禁职责）。

    schema 1.1：一律写 skill_ref（可指向档案 skill_id，也可以是描述性自由文本）。
    兼容历史写法：payload 里写 skill_id / free_text 会被自动归一为 skill_ref 并如实提示；
    但三种写法一个都没有时仍然拒绝写入（信息不全不得落盘）。
    """
    require(payload, "step_id", "adaptation")
    skill_ref = payload.get("skill_ref") or payload.get("skill_id") or payload.get("free_text")
    if not skill_ref:
        die("缺少必填字段：skill_ref（也接受历史写法 skill_id / free_text，会自动归一为 skill_ref）")
    step = step_by_id(task, payload["step_id"])
    entry = {
        "skill_ref": skill_ref,
        "gap": payload.get("gap", "unknown"),
        "adaptation": payload["adaptation"],
        "recorded_at": store.now_iso(),
    }
    step.setdefault("required_skills", []).append(entry)
    legacy_note = ""
    if not payload.get("skill_ref"):
        legacy_field = "skill_id" if payload.get("skill_id") else "free_text"
        legacy_note = f"（历史写法 {legacy_field} 已归一为 skill_ref）"
    return [
        f"步骤 {payload['step_id']} 已记录技能需求 {skill_ref} → 适配方式：{payload['adaptation']}{legacy_note}"
    ]


def _has_deliverables(task: dict) -> bool:
    """任务是否产出过交付物（项目内目录下有文件）。"""
    d = store.PROJECT_ROOT / "outputs" / "deliverables" / task["task_id"]
    return d.is_dir() and any(p for p in d.glob("*") if p.is_file())


def cmd_close(task: dict, payload: dict) -> list[str]:
    """三问验收（对应生命周期 H 与验收 T13）。"""
    require(payload, "actions_completed", "deliverables_ok", "goal_achieved")

    # 第⑨条硬前置的机械落点：产出了交付物却没跑交付检查，不许收尾。
    # 为什么挂在 close 上：close 是交付链路的必经关口，也是唯一能保证
    # 「交付前检查」这件事一定会被要求的地方。
    if _has_deliverables(task) and not task.get("delivery_check"):
        die(
            "本任务已有交付物，但没有交付检查记录，不允许收尾。\n"
            f"  请先运行：python3 scripts/deliver.py check --task {task['task_id']}\n"
            "  再运行：python3 scripts/deliver.py seal  --task "
            f"{task['task_id']} --file <答案.json>\n"
            "  （对应 SKILL.md §0 第⑨条硬前置：交付前必须跑交付检查，不通过不许交付）"
        )
    for key in ("actions_completed", "deliverables_ok", "goal_achieved"):
        if not isinstance(payload[key], dict):
            die(f"{key} 必须是对象，形如 {{\"verdict\": \"yes|partial|no\", \"basis\": \"依据\"}}")
        if payload[key].get("verdict") not in ("yes", "partial", "no"):
            die(f"{key}.verdict 必须是 yes/partial/no")
        if not payload[key].get("basis"):
            die(f"{key}.basis 不能为空——没有依据的判断不算验收")

    # 一致性门禁：不能说「承诺的行动已完成」，却在计划里留着未完成的步骤。
    unfinished = [s for s in task.get("plan", []) if s.get("status") not in ("done", "skipped")]
    if unfinished and payload["actions_completed"]["verdict"] == "yes" and not payload.get("allow_incomplete_steps"):
        listing = "、".join(f"{s.get('step_id')}《{s.get('name')}》" for s in unfinished)
        die(
            "计划中仍有未完成步骤（"
            + listing
            + "），不能同时声称「承诺的行动已完成」。"
            "请先如实处理这些步骤；若它们确实已不再需要，请用 change 记录范围调整，"
            "或在 close 里显式传 allow_incomplete_steps=true 并说明理由。"
        )
    if payload["actions_completed"]["verdict"] != "yes" and payload["goal_achieved"]["verdict"] == "yes":
        die("行动尚未完成，不能判定目标已实现。")

    task["acceptance"] = {
        "closed_at": store.now_iso(),
        "actions_completed": payload["actions_completed"],
        "deliverables_ok": payload["deliverables_ok"],
        "goal_achieved": payload["goal_achieved"],
        "pending_external": payload.get("pending_external", []),
        "verdict": payload.get("verdict", "auto"),
        "incomplete_steps_at_close": [s.get("step_id") for s in unfinished],
    }
    goal_verdict = payload["goal_achieved"]["verdict"]
    if goal_verdict == "yes":
        task["verdict"] = "目标已实现"
        task["status"] = "completed"
    elif goal_verdict == "partial":
        task["verdict"] = "我方工作已完成，最终目标尚待确认"
        task["status"] = "awaiting_acceptance"
    else:
        task["verdict"] = "目标未实现"
        task["status"] = "awaiting_acceptance"

    task["closed_at"] = store.now_iso()
    task["retrospective_status"] = "pending_triage"
    messages = [f"验收结论：{task['verdict']}（任务状态 {task['status']}）", "复盘状态：待筛选（复盘不等于必须新增经验）"]
    if payload.get("pending_external"):
        messages.append("尚待外部确认：" + "；".join(map(str, payload["pending_external"])))
    if unfinished:
        messages.append(
            "注意：关闭时计划中仍有未完成步骤 "
            + "、".join(s.get("step_id", "?") for s in unfinished)
            + "——已如实记入验收记录，不会被当作已完成"
        )
    return messages


COMMANDS = {
    "step": cmd_step,
    "evidence": cmd_evidence,
    "decision": cmd_decision,
    "blocker": cmd_blocker,
    "change": cmd_change,
    "next": cmd_next,
    "status": cmd_status,
    "unknown": cmd_unknown,
    "skillgap": cmd_skillgap,
    "close": cmd_close,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="更新 任务导航 任务状态")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--task", required=True, help="task_id，或标题关键词")
    parser.add_argument("--file", required=True, type=Path, help="变更内容 JSON 文件")
    args = parser.parse_args(argv[1:])

    store.find_project_root()
    data = store.load_tasks()
    if not data["tasks"]:
        die("目前没有任何任务记录。先创建任务再更新。")
    task = store.resolve_task(data["tasks"], args.task)
    payload = load_payload(args.file)

    handler = COMMANDS[args.command]
    messages = handler(task, payload)

    action_name = f"{args.command}"
    store.append_history(task, action_name, "；".join(messages))
    if args.command in ("step", "blocker", "change", "close", "status") and "next" not in payload:
        recompute_next_action(task)
    backup = store.save_tasks(data, f"{args.command} 更新 {task['task_id']}")
    store.append_event(task["task_id"], action_name, {"messages": messages})

    for line in messages:
        print(f"✓ {line}")
    print(f"  任务状态：{task['status']}    已完成步骤：{len(task['completed_steps'])}/{len(task['plan'])}")
    if task.get("next_best_action"):
        print(f"  下一步建议：{task['next_best_action']['action']}")
    print(f"  写前备份：{backup.relative_to(store.PROJECT_ROOT)}")
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
