#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_samples.py —— 生成 validate.py 的反例样本（只写 tests/invalid/ 内部）。

为什么要生成而不是手抄
----------------------
每个反例都是「同一份合法基线 + 恰好一处违规」。用生成器可以保证：
1. 基线样本（baseline/）本身必须让校验器 exit 0；
2. 每个反例只注入一处违规，校验器报错才能归因到那一条规则；
3. 备份反例里的 sha256 是真实计算出来的（不是猜的），重复运行结果一致。

安全边界
--------
* 本脚本**只**在 tests/invalid/ 下写文件；开头有硬断言，越界立即退出。
* 不读写 state/，因此不需要 store.create_backup（也不允许碰真实用户数据）。
* 不使用 store 的写函数，只用 store.sha256_file / store.count_records 计算真实值。

用法
----
    python3 tests/invalid/make_samples.py          # 重新生成全部样本
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import store  # noqa: E402

TS = "2026-01-01T00:00:00+08:00"


def guard(path: Path) -> Path:
    """硬断言：所有写入必须落在 tests/invalid/ 内部。"""
    resolved = Path(path).resolve()
    if HERE not in resolved.parents and resolved != HERE:
        raise SystemExit(f"拒绝写入 tests/invalid/ 之外的路径：{resolved}")
    return resolved


def write_json(path: Path, data) -> None:
    path = guard(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 固定 LF：Windows 的文本模式会把 \n 翻成 \r\n，生成的样本会与仓库里的 LF 版本
    # 不一致（哈希/指纹全变，test_line_endings 也会失败）。
    # 不用 write_text(newline=...)——那是 Python 3.10 才有的参数。
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- 合法基线

_BASELINE_CACHE: dict[str, object] | None = None


def _load_baseline_from_disk() -> dict[str, object] | None:
    """读取仓库里现有的 baseline/ 作为真源；不存在时返回 None（回落到引导模板）。

    为什么要有这条路径：硬编码模板 `_bootstrap_tree()` 会随字段演进过期。
    实测：模板里 risks_and_fallbacks / communication / time_estimate 都是空的，
    而 committed baseline 早已补全——直接用模板生成会把现有样本**降级**。
    baseline 是全部反例的对照真源，生成器应该从它派生，而不是从另一份会过期的副本派生。
    """
    root = HERE / "baseline"
    if not (root / "state" / "tasks.json").is_file():
        return None
    tree: dict[str, object] = {}
    for relative in _bootstrap_tree():          # 用模板的键表决定读取哪些文件
        path = root / relative
        if path.is_file():
            tree[relative] = json.loads(path.read_text(encoding="utf-8"))
    return tree or None


def baseline_tree() -> dict[str, object]:
    """返回基线树（深拷贝）。首次调用优先读现有 baseline/，之后走缓存。

    缓存很关键：main() 会先清空 tests/invalid/ 再生成，而 seam/conflict/privacy
    等样本树都调用本函数——不缓存就会在清空后回落到过期模板。
    """
    global _BASELINE_CACHE
    if _BASELINE_CACHE is None:
        _BASELINE_CACHE = _load_baseline_from_disk() or _bootstrap_tree()
    return copy.deepcopy(_BASELINE_CACHE)


def _bootstrap_tree() -> dict[str, object]:
    task = {
        "task_id": "TN-20260101-001",
        "title": "基线样本：证明反例失败来自注入的违规",
        "original_request": "（tests/invalid/ 基线样本，不是真实用户任务）",
        "domain": "work",
        "task_type": "execution",
        "goal": "提供一个字段完整的任务记录，作为全部反例的对照",
        "requester_or_beneficiary": None,
        "success_criteria": ["validate.py --all 对该样本 exit 0"],
        "deadline": None,
        "constraints": [],
        "assumptions": ["仅用于校验器回归测试"],
        "unknowns": [],
        "planning_depth": "standard",
        "plan": [
            {
                "step_id": "S1",
                "name": "写一份字段完整的任务记录",
                "purpose": "让反例有可对照的合法基线",
                "actions": ["补齐 schema.tasks.required_fields"],
                "required_skills": [{"skill_ref": "JSON 字段对照（自由文本，不查档案）"}],
                "executor": "user",
                "executor_basis": "样本：字段对照涉及用户自己的数据，必须本人确认，AI 不能替他决定",
                "deliverable": "一份合法的 tasks.json",
                "completion_criteria": "validate.py --all 对基线 exit 0",
                "inputs_or_dependencies": [],
                "risks_and_fallbacks": [],
                "communication": [],
                "status": "done",
            },
            {
                "step_id": "S2",
                "name": "注入一处违规并断言失败",
                "purpose": "证明规则真的会失败，而不是只对合法数据静默通过",
                "actions": ["复制基线", "只改一处", "运行校验器并断言非零退出"],
                "required_skills": [{"skill_id": "SK-20260101-001"}],  # 故意保留 1.0 字段名：验证 legacy 警告路径
                "executor": "joint",
                "executor_basis": "样本：AI 起草反例、用户核对规则，属共同做",
                "deliverable": "tests/invalid/rules/ 下的反例样本",
                "completion_criteria": "校验器非零退出且报出预期规则 id",
                "inputs_or_dependencies": ["S1"],
                "risks_and_fallbacks": [],
                "communication": [],
                "status": "pending",
            },
            {
                # t21：合法的 AI 代做形态——必须写明四选一的理由，否则校验器/写入侧都拒绝
                "step_id": "S3",
                "name": "把样本数据排成对比表",
                "purpose": "纯机械劳动，没有学习价值，适合 AI 代做",
                "actions": ["按列宽把 200 行样本数据排版", "导出为表格文本"],
                "required_skills": [{"skill_ref": "表格排版（自由文本，不查档案）"}],
                "executor": "ai",
                "executor_basis": "样本：纯机械排版，用户无需亲自做，AI 代做更省时间",
                "delegation_reason": "纯机械劳动",
                "deliverable": "排好版的对比表",
                "completion_criteria": "表格可直接复制使用且列对齐",
                "inputs_or_dependencies": ["S1"],
                "risks_and_fallbacks": [],
                "communication": [],
                "status": "pending",
            },
        ],
        "deliverables": [],
        "status": "in_progress",
        "completed_steps": [
            {
                "step_id": "S1",
                "completed_at": TS,
                "evidence": "基线样本自检：validate.py --all --state-dir tests/invalid/baseline/state 退出码 0",
                "notes": "样本数据",
            }
        ],
        "evidence": [],
        "decisions": [],
        "risks": [],
        "blockers": [],
        "changes": [],
        "next_best_action": {
            "action": "保持基线样本合法",
            "reason": "反例回归需要一个稳定的对照基线",
        },
        "retrospective_status": "not_reviewed",
        "history": [{"at": TS, "action": "created", "summary": "建立基线样本"}],
        "created_at": TS,
        "updated_at": TS,
    }

    skill = {
        "skill_id": "SK-20260101-001",
        "skill_name": "按字段清单核对 JSON 结构",
        "scope": "能做：按给定字段清单逐项核对 JSON。不包括：独立设计数据契约。",
        "status": "can_with_checklist",
        "evidence": [
            {
                "kind": "guided_practice",
                "description": "基线样本中照清单核对了一次（刻意构造的样本数据）",
                "task_id": "TN-20260101-001",
                "at": TS,
            }
        ],
        "confidence": {"level": "medium", "basis": "样本自述，属构造数据"},
        "last_verified_at": None,
        "known_gaps": ["未验证独立设计契约的能力"],
        "related_tasks": ["TN-20260101-001"],
        "privacy_scope": "general",
    }

    experience = {
        "experience_id": "EXP-20260101-001",
        "title": "基线样本：先写反例再写校验规则",
        "conclusion": "先为每条规则准备违规样本，再实现规则，才能证明校验真的生效",
        "domain": "work",
        "task_type": "execution",
        "tags": ["校验器", "反例", "数据契约"],
        "context": "基线样本：为 validate.py 建立反例回归",
        "trigger_conditions": ["需要实现依赖 schema 的校验器时"],
        "recommended_action": "为每条规则准备一个只注入一处违规的样本，并断言校验器非零退出",
        "reasoning": "只有反例能证明规则在数据被破坏时真的会失败",
        "observed_outcome": {
            "executed": True,
            "result": "基线样本：该做法在本次实现中已执行（构造数据，不代表真实用户经验）",
        },
        "evidence": ["tests/invalid/rules/ 下每个反例的校验器输出（样本）"],
        "source_task_id": "TN-20260101-001",
        "status": "single_observation",
        "confidence": {"level": "low", "basis": "构造样本，非真实观察"},
        "limitations": ["样本数据，不代表真实项目经验"],
        "counterexamples": [],
        "created_at": TS,
        "last_reviewed_at": None,
        "privacy_scope": "general",
        "related_skill_ids": ["SK-20260101-001"],
        "related_method_ids": ["MT-20260101-001"],
        "review_history": [
            {
                "at": TS,
                "from_status": "to_verify",
                "to_status": "single_observation",
                "note": "样本：已执行并留下证据，故从待验证改为单次观察",
                "evidence_count": 1,
                "previous_last_reviewed_at": None,
            }
        ],
        "counterexample_resolutions": [
            {
                "at": TS,
                "from_status": "challenged_by_counterexample",
                "resolution": "样本：反例发生在条件不满足的场景，本条适用条件已限定，故不再阻断",
            }
        ],
    }

    method = {
        "method_id": "MT-20260101-001",
        "name": "反例先行：先写违规样本，再写校验规则",
        "applicable_task_types": ["execution"],
        "problem_solved": "校验器可能只对合法数据静默通过，无法证明规则生效",
        "expected_outcome": "每条规则都有一个能让校验器非零退出的样本",
        "preconditions": ["已有明确的数据契约（schema.json）"],
        "not_applicable_when": ["契约本身仍在频繁变动时，先稳定契约再写反例"],
        "inputs": ["schema 中的规则清单"],
        "outputs": ["tests/invalid/ 下的违规样本与回归脚本"],
        "steps": [
            "列出规则",
            "为每条规则构造一个最小违规样本",
            "断言校验器非零退出且报出对应规则 id",
        ],
        "checkpoints": ["每个样本只注入一处违规；基线样本必须通过"],
        "failure_handling": ["若样本未被检出，先怀疑规则没实现，而不是删掉样本"],
        "source": {
            "kind": "own_experience",
            "citation": "本项目 reports/STORAGE_VERIFICATION.md 的实施记录",
            "retrieved_at": TS,
        },
        "verification_status": "single_use",
    }

    return {
        "state/tasks.json": {"tasks": [task], "last_updated": TS},
        "state/user_skills.json": {"skills": [skill], "last_updated": TS},
        "state/experience/EXP-20260101-001.json": experience,
        # schema.methods.file = "methods/index.json"：相对项目根（= 样本树根），不在 state/ 下
        "methods/index.json": {"methods": [method], "last_updated": TS},
    }


def materialise(root: Path, tree: dict[str, object]) -> None:
    for relative, payload in tree.items():
        write_json(root / relative, payload)


def load_tree(root: Path) -> dict[str, object]:
    return {
        relative: json.loads((root / relative).read_text(encoding="utf-8"))
        for relative in baseline_tree()
    }


# ---------------------------------------------------------------- 反例定义

def mutate(tree: dict, mutation: str) -> dict:
    """对基线副本注入恰好一处违规。"""
    data = copy.deepcopy(tree)
    tasks = data["state/tasks.json"]["tasks"]
    skills = data["state/user_skills.json"]["skills"]
    exp = data["state/experience/EXP-20260101-001.json"]
    methods = data["methods/index.json"]["methods"]

    if mutation == "drop_required_field":
        tasks[0].pop("next_best_action")
    elif mutation == "task_id_format":
        tasks[0]["task_id"] = "TN-2026-001"
    elif mutation == "task_id_duplicate":
        tasks.append(copy.deepcopy(tasks[0]))
    elif mutation == "completed_step_without_evidence":
        tasks[0]["completed_steps"][0]["evidence"] = ""
    elif mutation == "completed_step_unknown":
        tasks[0]["completed_steps"][0]["step_id"] = "S9"
    elif mutation == "step_missing_completion_criteria":
        tasks[0]["plan"][1].pop("completion_criteria")
    elif mutation == "skill_false_upgrade":
        skills[0]["status"] = "can_independently"
    elif mutation == "skill_weak_name":
        skills[0]["skill_name"] = "沟通能力很好"
    elif mutation == "skill_evidence_dangling_task":
        skills[0]["evidence"][0]["task_id"] = "TN-20260101-999"
    elif mutation == "plan_skill_id_dangling":
        tasks[0]["plan"][1]["required_skills"] = [{"skill_id": "SK-20260101-999"}]
    elif mutation == "exp_unexecuted_as_single_observation":
        exp["observed_outcome"]["executed"] = False
    elif mutation == "exp_claim_without_execution":
        exp["observed_outcome"]["executed"] = False
        exp["status"] = "to_verify"
        exp["conclusion"] = "按照这个做法做对比，显著提升效率"
    elif mutation == "exp_dangling_source_task":
        exp["source_task_id"] = "TN-20260101-999"
    elif mutation == "exp_empty_trigger_conditions":
        exp["trigger_conditions"] = []
    elif mutation == "exp_challenged_without_counterexample":
        exp["status"] = "challenged_by_counterexample"
        exp["counterexamples"] = []
    elif mutation == "method_unverified_without_limitation":
        methods[0]["verification_status"] = "unverified"
    elif mutation == "task_completed_without_closed_at":
        tasks[0]["status"] = "completed"
    elif mutation == "next_best_action_empty":
        tasks[0]["next_best_action"] = {"action": "", "reason": ""}
    elif mutation == "history_missing_summary":
        tasks[0]["history"][0].pop("summary")
    elif mutation == "skill_ref_dangling_id":
        tasks[0]["plan"][1]["required_skills"] = [{"skill_ref": "SK-20260101-999"}]
    elif mutation == "skill_ref_free_text":
        tasks[0]["plan"][1]["required_skills"] = [{"skill_ref": "自由文本技能描述（不是档案 id）"}]
    elif mutation == "legacy_missing_skill_ref":
        tasks[0]["plan"][1]["required_skills"] = [{"free_text": "旧写法的技能需求"}]
    elif mutation == "acceptance_missing_basis":
        tasks[0]["acceptance"] = {
            "closed_at": TS,
            "actions_completed": {"verdict": "yes", "basis": ""},
            "deliverables_ok": {"verdict": "yes", "basis": "样本：交付物已完成"},
            "goal_achieved": {"verdict": "partial", "basis": "样本：待外部确认"},
            "pending_external": [],
            "verdict": "auto",
        }
    elif mutation == "acceptance_verdict_invalid":
        tasks[0]["acceptance"] = {
            "closed_at": TS,
            "actions_completed": {"verdict": "yes", "basis": "样本：行动完成"},
            "deliverables_ok": {"verdict": "yes", "basis": "样本：交付物完成"},
            "goal_achieved": {"verdict": "partial", "basis": "样本：待确认"},
            "verdict": "maybe",
        }
    elif mutation == "task_verdict_invalid":
        tasks[0]["verdict"] = "随便写的一句话结论"
    elif mutation == "plan_history_missing_plan":
        tasks[0]["plan_history"] = [{"archived_at": TS, "reason": "样本：改成更短的对比维度"}]
    elif mutation == "review_history_missing_note":
        exp["review_history"] = [{"at": TS, "from_status": "to_verify", "to_status": "single_observation"}]
    elif mutation == "counterexample_resolution_missing_resolution":
        exp["counterexample_resolutions"] = [{"at": TS, "from_status": "challenged_by_counterexample"}]
    elif mutation == "method_unverified_with_limitation":
        methods[0]["verification_status"] = "unverified"
        methods[0]["limitations"] = ["未验证范围：样本只覆盖单团队执行，未覆盖跨团队协作与合规审查场景"]
    elif mutation == "step_missing_executor":
        # t21：S1 有 executor_basis 但没有 executor → 缺执行者
        tasks[0]["plan"][0].pop("executor")
    elif mutation == "step_missing_executor_basis":
        # t21：S2 有 executor 但没有依据 → 只写执行者名字不算表态
        tasks[0]["plan"][1].pop("executor_basis")
    elif mutation == "step_ai_without_delegation_reason":
        # t21：S3 是 AI 代做步骤，清掉理由 → AI 代做必须有理由
        tasks[0]["plan"][2]["delegation_reason"] = ""
    elif mutation == "light_step_missing_executor":
        # t21：light 深度同样强制（没有执行者的步骤同样不是步骤）
        tasks[0]["planning_depth"] = "light"
        tasks[0]["completed_steps"] = []
        tasks[0]["plan"] = [
            {
                "step_id": "S1",
                "name": "只写了动作与依据，却没有执行者",
                "actions": ["做一件轻量的事"],
                "executor_basis": "样本：本人顺手就能做",
                "status": "pending",
            }
        ]
    elif mutation == "usage_ref_unknown_method":
        tasks[0]["methods_used"] = [{"method_id": "no-such-method", "why": "测试用"}]
    elif mutation == "usage_ref_unknown_experience":
        tasks[0]["experiences_used"] = [{"experience_id": "EXP-99999999-999", "why_applicable": "测试用"}]
    elif mutation == "usage_ref_missing_why":
        tasks[0]["experiences_used"] = [{"experience_id": "EXP-20260101-001", "why_applicable": ""}]
    elif mutation == "step_dep_unknown":
        # schema 1.8：结构化依赖精确匹配；引用不存在的 S9 必须报错
        tasks[0]["plan"][1]["depends_on_step_ids"] = ["S9"]
    elif mutation == "step_dep_self":
        # schema 1.8：自依赖永远无法满足
        tasks[0]["plan"][1]["depends_on_step_ids"] = ["S2"]
    elif mutation == "inputs_dependency_legacy":
        # schema 1.8：旧字段里裸写 S1 仍按旧语义参与依赖判断，但必须提示迁移
        tasks[0]["plan"][1]["inputs_or_dependencies"] = ["S1"]
    elif mutation == "unchanged":
        pass
    elif mutation == "new_fields_valid_shape":
        tasks[0]["acceptance"] = {
            "closed_at": TS,
            "actions_completed": {"verdict": "yes", "basis": "样本：计划内步骤都已处理"},
            "deliverables_ok": {"verdict": "yes", "basis": "样本：产出物已完成"},
            "goal_achieved": {"verdict": "partial", "basis": "样本：仍待外部确认"},
            "pending_external": ["样本：等对方确认"],
            "verdict": "auto",
        }
        tasks[0]["verdict"] = "我方工作已完成，最终目标尚待确认"
        tasks[0]["plan_history"] = [
            {
                "archived_at": TS,
                "reason": "样本：把对比维度从 5 个压到 3 个",
                "plan": [{"step_id": "S1", "name": "旧计划的第一步"}],
            }
        ]
    else:  # pragma: no cover - 防御
        raise SystemExit(f"未知变异：{mutation}")
    return data


# kind = "fail"（必须非零退出并报出 rule）/ "pass"（必须 exit 0）/ "pass_with_warning"（exit 0 且报出 rule）
_BASE_CASES: list[tuple[str, str, str, str]] = [
    # (目录名, 变异, 预期规则 id, 说明)
    ("R01_missing_required_field", "drop_required_field", "T-REQ",
     "必填字段缺失：删掉 next_best_action"),
    ("R02_task_id_format", "task_id_format", "T-ID-FMT",
     "task_id 格式违规：TN-2026-001"),
    ("R03_task_id_duplicate", "task_id_duplicate", "T-ID-DUP",
     "task_id 不唯一：复制同一任务"),
    ("R04_completed_step_without_evidence", "completed_step_without_evidence", "T-EVIDENCE-EMPTY",
     "completed_steps 无 evidence：无证据不得标记完成"),
    ("R05_completed_step_unknown", "completed_step_unknown", "T-XREF-STEP",
     "completed_steps 引用不存在的步骤 S9"),
    ("R06_step_missing_completion_criteria", "step_missing_completion_criteria", "T-STEP-REQ",
     "standard 深度步骤缺 completion_criteria"),
    ("R07_skill_false_upgrade", "skill_false_upgrade", "S-UPGRADE",
     "技能虚假升级：只有 guided_practice 却写 can_independently"),
    ("R08_skill_weak_name", "skill_weak_name", "S-WEAK-NAME",
     "技能名使用不可验证弱表述「沟通能力很好」"),
    ("R09_skill_evidence_dangling_task", "skill_evidence_dangling_task", "S-XREF-TASK",
     "技能证据指向不存在的任务（悬空引用）"),
    ("R10_plan_skill_id_dangling", "plan_skill_id_dangling", "T-XREF-SKILL",
     "计划技能需求指向不存在的 skill_id"),
    ("R11_exp_unexecuted_as_single_observation", "exp_unexecuted_as_single_observation", "E-STATUS-CTX",
     "经验未执行却写成 single_observation"),
    ("R12_exp_claim_without_execution", "exp_claim_without_execution", "E-CLAIM",
     "未执行却写结果性结论「显著提升效率」"),
    ("R13_exp_dangling_source_task", "exp_dangling_source_task", "E-SOURCE",
     "经验 source_task_id 悬空"),
    ("R14_exp_empty_trigger_conditions", "exp_empty_trigger_conditions", "E-TRIGGER",
     "经验没有适用条件（trigger_conditions 为空）"),
    ("R15_exp_challenged_without_counterexample", "exp_challenged_without_counterexample", "E-COUNTEREXAMPLE",
     "标为被反例挑战却没有记录反例"),
    ("R16_method_unverified_without_limitation", "method_unverified_without_limitation", "M-UNVERIFIED",
     "方法标为 unverified 却没有未验证范围说明"),
    ("R17_task_completed_without_closed_at", "task_completed_without_closed_at", "T-CLOSED-AT",
     "任务标为 completed 却缺 closed_at"),
    ("R18_next_best_action_empty", "next_best_action_empty", "T-NBA",
     "next_best_action 的 action/reason 为空"),
    ("R19_history_missing_summary", "history_missing_summary", "T-HISTORY",
     "history 条目缺 summary"),
]

# schema 1.1：skill_ref 并集语义与新登记字段的第二组样本（t6 追加）
_EXTRA_CASES: list[tuple[str, str, str, str, tuple, str]] = [
    ("R21_skill_ref_dangling_id", "skill_ref_dangling_id", "fail", "T-XREF-SKILL", (),
     "skill_ref 形如 ^SK-\\d{8}-\\d{3}$ 但档案中不存在 → 必须硬失败（规则不得弱化）"),
    ("R22_skill_ref_free_text_ok", "skill_ref_free_text", "pass", "", ("T-XREF-SKILL",),
     "自由文本 skill_ref 合法（schema 1.1 并集语义）→ 必须 exit 0 且不得误报 T-XREF-SKILL"),
    ("R23_legacy_missing_skill_ref_warn", "legacy_missing_skill_ref", "pass_with_warning", "T-STEP-SKILL-LEGACY", (),
     "1.0 字段名（仅 free_text、缺 skill_ref）→ exit 0 但必须报警告并列出迁移清单"),
    ("R24_acceptance_missing_basis", "acceptance_missing_basis", "fail", "T-ACCEPTANCE", (),
     "tasks[].acceptance 三问之一 basis 为空 → 失败"),
    ("R25_acceptance_verdict_invalid", "acceptance_verdict_invalid", "fail", "T-VERDICT", (),
     "acceptance.verdict 取值不在 yes|partial|no|auto 内 → 失败"),
    ("R26_task_verdict_invalid", "task_verdict_invalid", "fail", "T-VERDICT-TEXT", (),
     "tasks[].verdict 不在 close 流程结论枚举内 → 失败"),
    ("R27_plan_history_missing_plan", "plan_history_missing_plan", "fail", "T-PLAN-HISTORY", (),
     "plan_history 归档项缺 plan → 失败"),
    ("R28_review_history_missing_note", "review_history_missing_note", "fail", "E-REVIEW-HISTORY", (),
     "review_history 记录缺 note（复核无理由）→ 失败"),
    ("R29_counterexample_resolution_missing_resolution", "counterexample_resolution_missing_resolution", "fail",
     "E-COUNTEREXAMPLE-RES", (),
     "counterexample_resolutions 记录缺 resolution → 失败"),
    ("R30_new_fields_valid_shape", "new_fields_valid_shape", "pass", "",
     ("T-PLAN-HISTORY", "T-ACCEPTANCE", "T-VERDICT", "T-VERDICT-TEXT", "E-REVIEW-HISTORY", "E-COUNTEREXAMPLE-RES"),
     "schema 1.1 新字段的合法形态必须 exit 0 且不被误报（acceptance 三问/verdict/plan_history/review_history/反例处理记录）"),
    ("R31_missing_methods_file", "unchanged", "fail", "M-FILE", (),
     "methods/index.json 缺失（必需数据域）→ 必须非零退出并指明缺哪个文件；不得记作「未执行=通过」"),
    ("R32_method_unverified_with_limitation_ok", "method_unverified_with_limitation", "pass", "",
     ("M-UNVERIFIED", "M-FILE"),
     "unverified 但写明未验证范围的合法方法 → exit 0 且不得误报 M-UNVERIFIED"),
    # t21：执行者机械门禁的三条反例 + light 档同样强制
    ("R33_step_missing_executor", "step_missing_executor", "fail", "T-STEP-EXECUTOR", (),
     "步骤缺 executor → 非零退出并报 T-STEP-EXECUTOR（缺执行者视为计划不完整）"),
    ("R34_step_missing_executor_basis", "step_missing_executor_basis", "fail", "T-STEP-EXECUTOR-BASIS", (),
     "步骤有 executor 但缺 executor_basis → 非零退出（只写执行者名字不算表态）"),
    ("R35_ai_step_without_delegation_reason", "step_ai_without_delegation_reason", "fail", "T-STEP-DELEGATION", (),
     "executor=ai 但缺 delegation_reason → 非零退出（AI 代做必须有理由）"),
    ("R36_light_step_missing_executor", "light_step_missing_executor", "fail", "T-STEP-EXECUTOR", (),
     "light 深度步骤同样必须声明执行者 → 非零退出（没有执行者的步骤同样不是步骤）"),
    # R37–R39 此前是手工补进 rules/ 的，没写进生成器——直接跑 make_samples.py 会把它们删掉。
    # 本轮补进生成器，保证「生成器跑一遍 = 样本集合」。
    ("R37_usage_ref_unknown_method", "usage_ref_unknown_method", "fail", "T-USAGE-REF", (),
     "methods_used 引用了不存在于 methods/index.json 的 method_id → 应非零退出（核审 t25 的 N6）"),
    ("R38_usage_ref_unknown_experience", "usage_ref_unknown_experience", "fail", "T-USAGE-REF", (),
     "experiences_used 引用了不存在的 experience_id → 应非零退出（核审 t25 的 N6）"),
    ("R39_usage_ref_missing_why", "usage_ref_missing_why", "fail", "T-USAGE-REF", (),
     "experiences_used 缺 why_applicable → 应非零退出：说了用哪条经验却不说什么适用，等于没留痕"),
    # schema 1.8：步骤依赖必须是精确 step_id；旧字段只做迁移提示
    ("R40_step_dep_unknown", "step_dep_unknown", "fail", "T-STEP-DEP-UNKNOWN", (),
     "depends_on_step_ids 引用不存在的 S9 → 非零退出（未知依赖不得静默当作已满足）"),
    ("R41_step_dep_self", "step_dep_self", "fail", "T-STEP-DEP-SELF", (),
     "步骤依赖自己 → 非零退出（自依赖永远无法开始）"),
    ("R42_inputs_dependency_legacy", "inputs_dependency_legacy", "pass_with_warning", "T-STEP-DEP-LEGACY",
     ("T-STEP-DEP-UNKNOWN", "T-STEP-DEP-SELF"),
     "旧字段 inputs_or_dependencies 里裸写 S1 → exit 0 但必须报迁移警告（旧字段不参与阻塞判断）"),
]

# 需要「删掉某个文件」的样本：额外数据域缺失的反例（R31 不写 methods/index.json）
OMIT_FILES = {"R31_missing_methods_file": ("methods/index.json",)}

CASES: list[dict] = [
    {"dir": dirname, "mutation": mutation, "kind": "fail", "rule": rule, "absent": (), "why": why,
     "omit": OMIT_FILES.get(dirname, ())}
    for dirname, mutation, rule, why in _BASE_CASES
] + [
    {"dir": d, "mutation": m, "kind": k, "rule": r, "absent": a, "why": w, "omit": OMIT_FILES.get(d, ())}
    for d, m, k, r, a, w in _EXTRA_CASES
]

# 文件名与 experience_id 不一致（需要单独处理文件名，不能只在 JSON 里改）
FILENAME_CASE = ("R20_experience_filename_mismatch", "E-FILENAME",
                 "经验文件名与 experience_id 不一致（一条一文件）")


# ---------------------------------------------------------------- 经验检索接缝样本

def seam_tree() -> dict[str, object]:
    tree = copy.deepcopy(baseline_tree())

    def entry(exp_id: str, title: str, *, domain: str, task_type: str, tags: list[str],
              triggers: list[str], status: str, executed: bool, evidence: list[str],
              conclusion: str, counterexamples: list[str] | None = None,
              limitations: list[str] | None = None) -> dict:
        return {
            "experience_id": exp_id,
            "title": title,
            "conclusion": conclusion,
            "domain": domain,
            "task_type": task_type,
            "tags": tags,
            "context": "样本：用于验证 exp.py search 的适用性判断与排除逻辑",
            "trigger_conditions": triggers,
            "recommended_action": "先把对比维度压到 3 个，再补细节",
            "reasoning": "维度越少越容易在短期限内得出可用结论",
            "observed_outcome": {"executed": executed, "result": "样本观察结果（构造数据，非真实项目经验）"} if executed
            else {"executed": False, "result": "计划从未执行（构造样本）"},
            "evidence": evidence,
            "source_task_id": "TN-20260101-001",
            "status": status,
            "confidence": {"level": "low", "basis": "构造样本"},
            "limitations": limitations if limitations is not None else ["样本数据，不代表真实经验"],
            "counterexamples": counterexamples if counterexamples is not None else [],
            "created_at": TS,
            "last_reviewed_at": None,
            "privacy_scope": "general",
            "related_skill_ids": ["SK-20260101-001"],
            "related_method_ids": ["MT-20260101-001"],
        }

    tree["state/experience/EXP-20260201-001.json"] = entry(
        "EXP-20260201-001", "竞品对比：先把维度压到三个",
        domain="work", task_type="research", tags=["竞品", "调研", "汇报"],
        triggers=["需要对比 3 家以上竞品并向经理汇报时"],
        status="single_observation", executed=True,
        evidence=["TN-20260101-001：三家竞品按三个维度对比，汇报一次通过"],
        conclusion="先定 3 个必比维度再补细节，比全量对比更快得出可汇报的结论",
    )
    tree["state/experience/EXP-20260201-002.json"] = entry(
        "EXP-20260201-002", "竞品对比：旧官网检索路径",
        domain="work", task_type="research", tags=["竞品", "调研", "官网"],
        triggers=["需要在竞品官网抓参数时"],
        status="obsolete", executed=True,
        evidence=["TN-20260101-001：当时官网静态页可直接抓取"],
        conclusion="直接抓竞品官网静态参数页最省事",
        limitations=["2026-03 起竞品官网改为动态渲染，原检索路径失效"],
    )
    tree["state/experience/EXP-20260201-003.json"] = entry(
        "EXP-20260201-003", "竞品对比：只比价格会翻车",
        domain="work", task_type="research", tags=["竞品", "调研", "价格"],
        triggers=["对比竞品价格并给出推荐时"],
        status="challenged_by_counterexample", executed=True,
        evidence=["TN-20260101-001：首轮只比价格被经理驳回"],
        conclusion="价格维度足以支撑推荐结论",
        counterexamples=["另一家公司在数据严重缺失时套用「只比价格」，结论被决策人驳回"],
    )
    tree["state/experience/EXP-20260201-004.json"] = entry(
        "EXP-20260201-004", "净水器选购：对比多款机型",
        domain="life", task_type="admin", tags=["净水器", "对比", "研究"],
        triggers=["需要对比多款净水器型号并考虑厨下安装条件时"],
        status="single_observation", executed=True,
        evidence=["TN-20260101-001：按三个维度筛出候选机型"],
        conclusion="先量厨下尺寸再比机型，能砍掉一半候选",
    )
    tree["state/experience/EXP-20260201-005.json"] = entry(
        "EXP-20260201-005", "竞品对比：只看三个维度（假设，未执行）",
        domain="work", task_type="research", tags=["竞品", "汇报", "维度"],
        triggers=["需要对比 3 家以上竞品并向上汇报时"],
        status="to_verify", executed=False, evidence=[],
        conclusion="把维度压到三个可能比全量对比更省时间（尚未执行，仅为待验证假设）",
    )
    tree["state/experience/EXP-20260201-006.json"] = entry(
        "EXP-20260201-006", "竞品对比：结论前置先给经理看一页",
        domain="work", task_type="research", tags=["竞品", "汇报", "结论前置"],
        triggers=["需要向经理汇报竞品对比结论时"],
        status="single_observation", executed=True,
        evidence=["TN-20260101-001：一页结论前置稿被经理直接采用"],
        conclusion="结论前置的一页稿比长报告更容易被采用",
    )
    return tree


# ---------------------------------------------------------------- 冲突 / 隐私样本树（t8）

def _sample_entry(exp_id: str, title: str, *, tags: list[str], triggers: list[str],
                  conclusion: str, action: str, counterexamples: list[str] | None = None,
                  status: str = "single_observation") -> dict:
    return {
        "experience_id": exp_id,
        "title": title,
        "conclusion": conclusion,
        "domain": "work",
        "task_type": "research",
        "tags": tags,
        "context": "样本：用于验证 exp.py search 的冲突提示（G3）",
        "trigger_conditions": triggers,
        "recommended_action": action,
        "reasoning": "样本理由：先核实条件再决定做法",
        "observed_outcome": {"executed": True, "result": "样本观察结果（构造数据，非真实项目经验）"},
        "evidence": [f"{exp_id} 样本证据：一次任务实例（构造数据）"],
        "source_task_id": "TN-20260101-001",
        "status": status,
        "confidence": {"level": "low", "basis": "构造样本"},
        "limitations": ["样本数据，不代表真实经验"],
        "counterexamples": counterexamples if counterexamples is not None else [],
        "created_at": TS,
        "last_reviewed_at": None,
        "privacy_scope": "work",
        "related_skill_ids": ["SK-20260101-001"],
        "related_method_ids": ["MT-20260101-001"],
    }


def conflict_tree() -> dict[str, object]:
    """G3 反例：三对互相冲突的经验 + 1 条干净经验。"""
    tree = copy.deepcopy(baseline_tree())
    common_tags = ["竞品", "汇报", "经理"]
    entries = [
        # ① recommended_action 语义相反（一侧带否定）
        _sample_entry(
            "EXP-20260401-001", "竞品研究：先确认范围再收集资料",
            tags=common_tags, triggers=["研究范围由他人定义时"],
            conclusion="先确认研究范围能避免整轮返工",
            action="动手收集资料前先与经理确认研究范围",
        ),
        _sample_entry(
            "EXP-20260401-002", "竞品研究：不要先确认范围",
            tags=common_tags, triggers=["研究范围由他人定义时"],
            conclusion="直接开始收集资料更快出结果",
            action="不要先与经理确认研究范围，直接开始收集资料",
        ),
        # ② trigger_conditions 互斥（齐全 / 缺失）
        _sample_entry(
            "EXP-20260401-003", "竞品研究：资料齐全时按三个维度对比",
            tags=common_tags, triggers=["竞品资料齐全时"],
            conclusion="资料齐全时按三个维度对比即可",
            action="按三个维度做竞品对比",
        ),
        _sample_entry(
            "EXP-20260401-004", "竞品研究：资料缺失时也要按三个维度对比",
            tags=common_tags, triggers=["竞品资料缺失时"],
            conclusion="资料缺失时也先按三个维度搭框架",
            action="按三个维度做竞品对比",
        ),
        # ③ 一条的 counterexamples 指向另一条的结论
        _sample_entry(
            "EXP-20260401-005", "竞品研究：短期限内先定维度再补细节",
            tags=common_tags, triggers=["短期限内需要提交竞品对比结论时"],
            conclusion="短期限内先定三个维度再补细节是可行的",
            action="先定三个维度，再补细节",
            counterexamples=["先定三个维度再补细节，比全量对比更快得出可用结论——在资料缺失时导致结论被经理驳回"],
        ),
        _sample_entry(
            "EXP-20260401-006", "竞品研究：先定三个维度再补细节",
            tags=common_tags, triggers=["短期限内需要提交竞品对比结论时"],
            conclusion="先定三个维度再补细节，比全量对比更快得出可用结论",
            action="先定三个维度，再补细节",
        ),
        # ④ 干净经验（应出现在「可采用」区）
        _sample_entry(
            "EXP-20260401-007", "竞品研究：先给一页结论稿",
            tags=common_tags, triggers=["需要向经理汇报竞品对比结论时"],
            conclusion="先给一页结论稿更容易被经理采用",
            action="先写一页结论稿给经理看",
        ),
    ]
    for entry in entries:
        tree[f"state/experience/{entry['experience_id']}.json"] = entry
    return tree


def privacy_warn_tree() -> dict[str, object]:
    """t13 常驻断言样本树：证明数据层隐私警告**真的会出现**（且只在 general 域）。

    三条经验：
    * EXP-20260501-001：privacy_scope=general + 机密特征（标记/客户名/指标+数值）→ **必须报警告**
    * EXP-20260501-002：privacy_scope=general + 干净正文 → 不应报警告（防止「见 general 就报」）
    * EXP-20260501-003：privacy_scope=work + 同样的机密正文 → 不报警告（跨域检查只针对 general）
    另含基线自带的 EXP-20260101-001（general、干净）。
    """
    tree = copy.deepcopy(baseline_tree())
    confidential_context = (
        "样本：公司内部资料，涉及未公开的竞品对比口径；客户名称：XX 集团；该季度毛利率 42.3%"
    )
    clean_context = "样本：只用公开可核实的资料做整理，不含任何受限信息"

    def entry(exp_id: str, title: str, scope: str, *, confidential: bool) -> dict:
        """confidential=True 的条目**所有字段**都含机密特征；False 的条目所有字段都干净。

        这样 EXP-20260501-002 才能证明「不是见到 general 就报」——它每条字段都必须无命中。
        """
        if confidential:
            conclusion = "先按内部指标核对口径再对外汇报（样本数据）"
            action = "先从内部数据取数，核对口径后再写汇报"
            reasoning = "内部指标与对外披露口径不同，混用会被质疑"
            triggers = ["需要向经理汇报带内部指标的对比结论时"]
            context = confidential_context
        else:
            conclusion = "先把公开资料整理成三栏对比（样本数据）"
            action = "先收集公开可核实的资料，再整理成对比表"
            reasoning = "公开资料可复核，结论更容易被接受"
            triggers = ["需要整理公开资料做对比时"]
            context = clean_context
        return {
            "experience_id": exp_id,
            "title": title,
            "conclusion": conclusion,
            "domain": "work",
            "task_type": "research",
            "tags": ["竞品", "汇报"],
            "context": context,
            "trigger_conditions": triggers,
            "recommended_action": action,
            "reasoning": reasoning,
            "observed_outcome": {"executed": True, "result": "样本观察结果（构造数据，非真实项目经验）"},
            "evidence": [f"{exp_id} 样本证据：一份汇报稿（构造数据）"],
            "source_task_id": "TN-20260101-001",
            "status": "single_observation",
            "confidence": {"level": "low", "basis": "构造样本"},
            "limitations": ["样本数据，不代表真实经验"],
            "counterexamples": [],
            "created_at": TS,
            "last_reviewed_at": None,
            "privacy_scope": scope,
            "related_skill_ids": ["SK-20260101-001"],
            "related_method_ids": ["MT-20260101-001"],
        }

    tree["state/experience/EXP-20260501-001.json"] = entry(
        "EXP-20260501-001", "样本：带内部口径的竞品研究（general 域，必然命中）", "general", confidential=True
    )
    tree["state/experience/EXP-20260501-002.json"] = entry(
        "EXP-20260501-002", "样本：公开资料整理（general 域，任何字段都不应命中）", "general", confidential=False
    )
    tree["state/experience/EXP-20260501-003.json"] = entry(
        "EXP-20260501-003", "对照组：同样的内部内容留在 work 域（scope 边界）", "work", confidential=True
    )
    return tree


def privacy_tree() -> dict[str, object]:
    """G4 样本树：合法基线（含 1 条 general 经验，正文无机密特征）。"""
    return copy.deepcopy(baseline_tree())


# ---------------------------------------------------------------- 备份反例

def backup_fixtures() -> list[tuple[str, str, str]]:
    """生成两个备份反例；sha256 与记录数用 store 的真实函数计算。"""
    cases: list[tuple[str, str, str]] = []

    # 1) sha256 不符：manifest 记录原始哈希，随后文件被改动（模拟损坏）
    stamp = "20260101T000000Z"
    root = guard(HERE / "backups" / "hash_mismatch" / "backups" / stamp)
    target = root / "state" / "tasks.json"
    pristine = {"tasks": [{"task_id": "TN-20260101-001"}], "last_updated": TS}
    write_json(target, pristine)
    good_hash = store.sha256_file(target)
    records = store.count_records(target)
    write_json(root / "manifest.json", {
        "created_at": TS,
        "reason": "反例：备份内文件哈希与 manifest 不一致",
        "schema_version": "1.0",
        "files": [{"path": "state/tasks.json", "sha256": good_hash, "records": records}],
    })
    tampered = dict(pristine)
    tampered["tampered"] = "备份后在备份目录内被改动，哈希必然不符"
    write_json(target, tampered)
    cases.append(("backups/hash_mismatch", "B-HASH", "备份内文件 sha256 与 manifest 不符"))

    # 2) 记录数不符：sha256 正确，manifest 记录的 records 是错的
    stamp = "20260101T000000Z"
    root = guard(HERE / "backups" / "records_mismatch" / "backups" / stamp)
    target = root / "state" / "tasks.json"
    payload = {
        "tasks": [{"task_id": "TN-20260101-001"}, {"task_id": "TN-20260101-002"}],
        "last_updated": TS,
    }
    write_json(target, payload)
    write_json(root / "manifest.json", {
        "created_at": TS,
        "reason": "反例：manifest 记录数与备份文件实际记录数不一致",
        "schema_version": "1.0",
        "files": [{"path": "state/tasks.json", "sha256": store.sha256_file(target), "records": 7}],
    })
    cases.append(("backups/records_mismatch", "B-RECORDS", "备份内文件记录数与 manifest 不符"))

    return cases


# ---------------------------------------------------------------- 主流程

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="生成 validate.py 的反例样本（只写 tests/invalid/）")
    parser.parse_args()

    # 先读出真源（现有 baseline/），再清空目录。
    # 顺序反了会出事：baseline 被删后 baseline_tree() 只能回落到过期模板，
    # 生成的样本会缺字段（实测：risks/communication/time_estimate 全部丢失）。
    base = baseline_tree()

    for sub in ("baseline", "rules", "exp_seam", "exp_conflict", "exp_privacy", "exp_privacy_warn", "backups"):
        target = guard(HERE / sub)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

    # 基线：必须通过
    materialise(HERE / "baseline", base)

    # 反例：基线 + 一处违规（omit 里的文件不写，用于「必需数据域缺失」这类反例）
    for case in CASES:
        case_root = HERE / "rules" / case["dir"]
        tree = mutate(baseline_tree(), case["mutation"])
        for omitted in case.get("omit", ()):
            tree.pop(omitted, None)
        materialise(case_root, tree)
        write_json(case_root / "expect.json", {
            "kind": case["kind"],
            "rule": case["rule"],
            "absent": list(case["absent"]),
            "why": case["why"],
        })

    # 文件名与 id 不一致的反例
    dirname, rule, why = FILENAME_CASE
    case_root = HERE / "rules" / dirname
    tree = baseline_tree()
    wrong_name = "EXP-20260101-002.json"
    for relative, payload in tree.items():
        if relative == "state/experience/EXP-20260101-001.json":
            write_json(case_root / "state/experience" / wrong_name, payload)
        else:
            write_json(case_root / relative, payload)
    write_json(case_root / "expect.json", {"kind": "fail", "rule": rule, "absent": [], "why": why})

    # 经验检索接缝样本（合法数据，用于验证 search 的排除逻辑）
    materialise(HERE / "exp_seam", seam_tree())

    # t8：冲突提示（G3）与隐私门禁（G4）样本树
    materialise(HERE / "exp_conflict", conflict_tree())
    materialise(HERE / "exp_privacy", privacy_tree())
    # t13：隐私警告常驻断言样本（data 层警告必须出现）
    materialise(HERE / "exp_privacy_warn", privacy_warn_tree())

    # 备份反例
    backup_cases = backup_fixtures()
    write_json(HERE / "backups" / "index.json", {
        "cases": [{"dir": d, "rule": r, "why": w} for d, r, w in backup_cases]
    })

    total = len(CASES) + 1  # 含 R20 文件名不一致一例
    failing = sum(1 for case in CASES if case["kind"] == "fail") + 1
    print(
        f"已生成：baseline（1 个合法基线）+ rules（{total} 个样本：必失败 {failing} 个 + 必通过 {total - failing} 个）"
        f" + exp_seam（6 条经验样本）+ exp_conflict（7 条冲突样本：3 对冲突 + 1 条干净）"
        f" + exp_privacy（合法基线，供隐私门禁样本使用）"
        f" + exp_privacy_warn（3 条样本：必命中 general / 干净 general / 机密 work）+ backups（{len(backup_cases)} 个反例）"
    )
    print(f"输出目录：{HERE}")
    print("下一步  ：python3 tests/invalid/run_rules.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
