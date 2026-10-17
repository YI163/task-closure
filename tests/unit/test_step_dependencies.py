#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：任务依赖判断必须按**精确 step_id**，不能靠字符串包含或自然语言猜测。

## 防止什么问题

审查报告 P1-1：旧实现是

    unmet = [d for d in blocked_by if not any(str(d) in str(c) for c in done_ids)]

只要「依赖字符串」是「已完成 step_id」的子串就算满足——步骤 `S1` 会被已完成的 `S10`
错误满足，于是 next_best_action 在**前置没做完**时就把下一步放行。
同时，`inputs_or_dependencies` 里的自然语言（如「依赖 S1 的核对结果」）被当成步骤 ID
做包含比较，实际永远匹配不上，导致任务被永久阻塞。

## 新契约（schema 1.8）

- `depends_on_step_ids`：调度依赖，精确匹配、必须存在、不得自依赖/重复；
- `inputs_or_dependencies`：自然语言说明，**不参与阻塞判断**；
- 旧数据兼容：旧字段里「整串恰好等于某个真实 step_id」的条目仍按旧语义参与判断，
  但只做精确相等，不做子串。
"""

import contextlib
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import task_new  # noqa: E402
import task_update  # noqa: E402


def make_task(plan, completed_ids=()):
    return {
        "task_id": "TN-20260101-001",
        "title": "依赖判断样本",
        "status": "in_progress",
        "plan": plan,
        "completed_steps": [
            {"step_id": sid, "completed_at": "2026-01-01T00:00:00+08:00", "evidence": "样本"}
            for sid in completed_ids
        ],
    }


def step(step_id, status="pending", **extra):
    base = {"step_id": step_id, "name": f"步骤{step_id}", "status": status}
    base.update(extra)
    return base


def action_of(task):
    task_update.recompute_next_action(task)
    return task["next_best_action"]["action"]


def check(condition, label, failures, detail=""):
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


def test_next_action(failures):
    print("next_best_action：")

    # 1) 前缀重合：S10 已完成，不能因此放行依赖 S1 的 S2
    task = make_task(
        [step("S10", "done"), step("S2", depends_on_step_ids=["S1"]), step("S1")],
        completed_ids=["S10"],
    )
    action = action_of(task)
    check("S1" in action and "S2" not in action,
          "只完成 S10 不能满足对 S1 的依赖", failures, action)

    # 2) 精确匹配：S1 完成后依赖满足，下一步是 S2
    task = make_task(
        [step("S10", "done"), step("S2", depends_on_step_ids=["S1"]), step("S1", "done")],
        completed_ids=["S10", "S1"],
    )
    action = action_of(task)
    check(action.startswith("S2 "), "完成 S1 后依赖满足，下一步是 S2", failures, action)

    # 3) 不存在的依赖：保持阻塞，并明确报出「不存在的步骤 ID」
    task = make_task([step("S2", depends_on_step_ids=["S99"])])
    action = action_of(task)
    check("S99" in action and "不存在" in action,
          "未知依赖保持阻塞并报出不存在", failures, action)

    # 4) 旧数据：inputs 里裸写 S1 仍按旧语义阻塞（精确相等）
    task = make_task([step("S2", inputs_or_dependencies=["S1"]), step("S1")])
    action = action_of(task)
    check("S1" in action and "S2" not in action,
          "旧字段裸写 S1 仍能阻塞（兼容旧数据）", failures, action)

    # 5) 自然语言不能被当成 step ID 做子串比较
    task = make_task(
        [step("S2", inputs_or_dependencies=["依赖 S1 的核对结果"]), step("S1")],
    )
    action = action_of(task)
    check(action.startswith("S2 "), "自然语言依赖不参与阻塞判断（不误判为步骤 ID）", failures, action)

    # 6) 显式空数组 = 确认无依赖，不回落到旧字段
    task = make_task(
        [step("S2", depends_on_step_ids=[], inputs_or_dependencies=["S1"]), step("S1")],
    )
    action = action_of(task)
    check(action.startswith("S2 "), "depends_on_step_ids=[] 覆盖旧字段，不阻塞", failures, action)


def base_step(step_id, depends=None):
    item = {
        "step_id": step_id,
        "name": f"步骤{step_id}",
        "purpose": "样本",
        "actions": ["做一件事"],
        "required_skills": [{"skill_ref": "自由文本技能", "gap": "未评估"}],
        "executor": "user",
        "executor_basis": "样本：本人做",
        "deliverable": "样本产出",
        "completion_criteria": "样本完成标准",
        "inputs_or_dependencies": ["不适用：样本"],
        "risks_and_fallbacks": ["不适用：样本"],
        "communication": ["不适用：样本"],
        "time_estimate": "10 分钟",
        "estimate_basis": "样本估算",
    }
    if depends is not None:
        item["depends_on_step_ids"] = depends
    return item


def expect_reject(failures, label, plan, fragment):
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            task_new.normalise_plan(plan, "standard")
    except SystemExit as exc:
        text = stderr.getvalue()
        check(exc.code == 2 and fragment in text, label, failures, text.strip()[:120])
        return
    check(False, label, failures, "未拒绝，反而成功返回")


def test_write_side(failures):
    print("写入侧（task_new）：")

    ok_steps, _ = task_new.normalise_plan(
        [base_step("S1"), base_step("S2", depends=["S1"])], "standard"
    )
    check(ok_steps[1]["depends_on_step_ids"] == ["S1"],
          "合法依赖可以建档", failures)

    expect_reject(failures, "未知依赖 S9 被拒绝", [base_step("S1"), base_step("S2", depends=["S9"])], "S9")
    expect_reject(failures, "自依赖被拒绝", [base_step("S1"), base_step("S2", depends=["S2"])], "依赖自己")
    expect_reject(failures, "重复依赖被拒绝",
                  [base_step("S1"), base_step("S2", depends=["S1", "S1"])], "重复")
    expect_reject(failures, "依赖不是字符串时被拒绝",
                  [base_step("S1"), base_step("S2", depends=[1])], "非空字符串")


def main() -> int:
    failures: list[str] = []
    test_next_action(failures)
    test_write_side(failures)
    print()
    if failures:
        print(f"结论：失败：{failures}")
        return 1
    print("结论：通过")
    return 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    sys.path.insert(0, str(ROOT / "scripts"))
    import console  # noqa: E402

    console.setup()
    sys.exit(main())
