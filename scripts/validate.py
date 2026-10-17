#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py —— 依据 state/schema.json 强制校验四域数据 + 跨引用 + 备份完整性。

用法
----
    python3 scripts/validate.py --all                         # 校验四域（默认动作）
    python3 scripts/validate.py --tasks --skills              # 只校验指定域
    python3 scripts/validate.py --all --state-dir <目录>       # 校验别的 state 目录（反例样本用）
    python3 scripts/validate.py --backup-verify               # 校验最新备份的 sha256 与记录数
    python3 scripts/validate.py --backup-verify --backup <备份目录>
    python3 scripts/validate.py --list-rules                  # 打印规则清单（规则 id ↔ 说明）

设计原则（对应 spec/02 §7「优先把验证放进工具/脚本」）
----------------------------------------
1. **只读**：本脚本不写任何文件（不写 state/，也不写别处），因此不需要备份。
2. **契约唯一权威**：必填字段、枚举、字段规则全部从 state/schema.json 读取；
   本文件不复制第二份契约，避免「改了 schema 但校验器没跟上」。
3. **反例必须失败**：--state-dir 可以把校验指向 tests/invalid/ 下的故意违规样本，
   用来证明每条规则真的会失败（见 tests/invalid/run_rules.py）。
4. **诚实降级**：数据文件损坏 / 缺少必需域 → 报错并非零退出，绝不静默通过。

退出码
------
    0 = 通过（可能带警告）
    1 = 存在校验错误
    2 = 用法错误 / 数据文件无法读取（StoreError 等）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

# ---------------------------------------------------------------- 常量

TASK_ID_RE = re.compile(r"^TN-\d{8}-\d{3}$")
EXPERIENCE_ID_RE = re.compile(r"^EXP-\d{8}-\d{3}$")
# 技能档案 id 的形态（schema 未定义格式，取自 store.next_skill_id 的实际写法 SK-<YYYYMMDD>-<序号>）
SKILL_ID_RE = re.compile(r"^SK-\d{8}-\d{3}$")

# 验收三问（task_update.py cmd_close 强制要求）
ACCEPTANCE_QUESTIONS = ("actions_completed", "deliverables_ok", "goal_achieved")
QUESTION_VERDICTS = ("yes", "partial", "no")
# acceptance.verdict 取值来源：task_update.py cmd_close 的 payload.get("verdict", "auto")
DEFAULT_ACCEPTANCE_VERDICTS = ("yes", "partial", "no", "auto")
# tasks[].verdict 取值来源：task_update.py cmd_close 写入的三条 machine 结论
DEFAULT_TASK_VERDICTS = ("目标已实现", "我方工作已完成，最终目标尚待确认", "目标未实现")

# 不可验证的弱表述（schema: skill_name 必须具体到可验证；validate.py 用弱词黑名单拒绝）
WEAK_SKILL_NAME_TERMS = (
    "沟通能力好", "沟通能力很好", "沟通能力强", "沟通能力不错", "沟通能力较强",
    "擅长沟通", "沟通良好", "团队协作好", "性格开朗", "认真负责",
    "良好", "优秀", "较强", "不错", "比较强", "还行", "挺好",
)

# 未执行却写成结果性结论的禁用词（schema: 不得把未执行的方法写成「显著提升效率」这类结论）
RESULT_CLAIM_TERMS = (
    "显著提升", "大幅提升", "提升效率", "提高效率", "效率提高", "效果显著",
    "实测有效", "已验证有效", "行之有效", "明显改善", "被证明有效", "证明有效",
    "非常有效", "效果很好",
)

UNVERIFIED_HINTS = ("未验证", "未经验证", "没验证", "尚未验证", "未予验证", "未经检验")

TASK_ARRAY_FIELDS = (
    "success_criteria", "plan", "completed_steps", "evidence", "decisions",
    "risks", "blockers", "changes", "assumptions", "unknowns", "history",
)

OPEN_TASK_STATUSES = ("not_started", "in_progress", "waiting_external", "blocked", "awaiting_acceptance")

# schema 明确允许为 null 的必填字段（"iso8601 或 null"）：
# 只要求字段存在，不要求非空，具体格式由 *_TIME 规则校验。
NULLABLE_REQUIRED_FIELDS = {
    "user_skills": {"last_verified_at"},
    "experiences": {"last_reviewed_at"},
}

_MISSING = object()
_BROKEN = object()

# 规则清单（--list-rules 与报告使用；id 会出现在每条错误前，便于反例回归断言）
RULES: dict[str, str] = {
    "JSON-BROKEN": "数据文件必须是合法 JSON（损坏时非零退出，不静默）",
    "T-FILE": "state/tasks.json 必须存在（任务状态是必需域）",
    "T-ROOT": "tasks.json 根结构 = {tasks: array, last_updated: iso8601}",
    "T-REQ": "每个任务必须含 schema.tasks.required_fields 的全部字段",
    "T-ARRAY": "任务的数组字段必须是数组（success_criteria 等）",
    "T-CRITERIA": "success_criteria 必须是非空数组，且每项为非空文字",
    "T-ID-FMT": r"task_id 必须匹配 ^TN-\d{8}-\d{3}$",
    "T-ID-DUP": "task_id 必须全局唯一",
    "T-ENUM": "domain/task_type/status/planning_depth/retrospective_status 必须在 schema 枚举内",
    "T-TIME": "created_at/updated_at/closed_at 必须是 ISO8601",
    "T-PLAN": "plan 必须是数组",
    "T-PLAN-ITEM": "plan 每项必须是对象",
    "T-STEP-REQ": "standard/deep 的步骤必须含 step_required_fields（含完成标准与产出）",
    "T-STEP-DUP": "同一任务内 step_id 必须唯一",
    "T-STEP-SKILL": "required_skills 每项必须可解析（schema 1.1：skill_ref 必填；1.0 字段名按 T-STEP-SKILL-LEGACY 报警告）",
    "T-STEP-SKILL-LEGACY": "【警告】required_skills 仍用 1.0 字段名（缺 skill_ref）——输出迁移清单，不硬失败",
    "T-STEP-STATUS": "步骤 status 必须在 schema.step_status 枚举内",
    "E-INDEX-STALE": "【警告】state/experience_index.md 应与经验/教训数据一致——"
                      "它是派生文件，过期会让人读到旧的「系统学到了什么」",
    "T-EXP-SELF-REF": "任务不得把「源自本任务自身」的经验列为 experiences_used——"
                      "那是循环论证：用自己的产出去论证自己的做法（实测发生过一次）",
    "T-USAGE-REF": "methods_used[].method_id 必须存在于 methods/index.json；"
                    "experiences_used[].experience_id 必须存在于 state/experience/，且 why_applicable 非空"
                    "——「用了哪条方法/经验」必须可追溯（spec/03 §7-6）",
    "L-TYPE": "lessons/*.json 的 lesson_type 必须是六类之一（有效做法/无效做法/失败原因/方法适用条件/技能差距/流程改进）——SKILL.md §J 要求按类整理，无类别的教训等于流水账",
    "T-SKILL-GAP": "【警告】standard/deep 下，required_skills 的自由文本引用宜给出 gap 或 archive_status"
                    "（写明该技能状态未评估）——否则技能适配路径在这条路径上无落点。"
                    "做成警告而非错误：既有契约（R22）明确允许自由文本引用，不应因新增建议而破约",
    "T-RETRO-COVERAGE": "【警告】已达验收状态的任务应完成复盘——复盘机制存在但常被跳过"
                        "（实测：7 个任务只有 3 个 reviewed）。警告不阻断，只是让它每次都被看见",
    "T-DECISION-AUTH": "有外部发起人的任务应填 decision_authority（spec/01 §4A）：记录可自行决定什么、必须询问谁——缺它会让人分不清哪些动作可直接推进",
    "T-STEP-COMPLETENESS": "standard/deep 档位下，步骤的 inputs_or_dependencies / risks_and_fallbacks / "
                           "communication / time_estimate 必须有内容（确实不适用时须显式写明理由）——"
                           "spec/01 §4E 要求每步九项完整",
    "T-STEP-EXECUTOR": "每一步必须写明执行者 executor（user=用户做 / ai=AI 做 / joint=共同做）——缺执行者视为计划不完整（SKILL.md §0.4.1）",
    "T-STEP-EXECUTOR-ENUM": "executor 必须是 schema.tasks.step_executor_fields.fields.executor.enum 的枚举值",
    "T-STEP-EXECUTOR-BASIS": "每一步必须写明 executor_basis（为什么由该方执行）——只有执行者名字不算表态",
    "T-STEP-DELEGATION": "executor=ai 时必须写明 delegation_reason（AI 代做必须有理由；schema 枚举四选一）",
    "T-STEP-DELEGATION-ENUM": "delegation_reason 必须是 schema 枚举（极紧期限/高代价/纯机械劳动/用户明确要求）之一",
    "T-STEP-DELEGATION-STALE": "【警告】executor≠ai 的步骤不应保留 delegation_reason（那是 AI 代做的理由）",
    "T-XREF-STEP": "completed_steps.step_id 必须存在于同任务的 plan 中",
    "T-XREF-SKILL": "skill_ref/skill_id 仅在「等于档案中现有 skill_id」或「形如 ^SK-\\d{8}-\\d{3}$」时才强制存在于 user_skills.json（schema 1.1 并集语义；自由文本不查档案）",
    "T-ACCEPTANCE": "tasks[].acceptance 结构：三问 {verdict: yes|partial|no, basis: 非空} + closed_at/列表字段类型",
    "T-VERDICT": "tasks[].acceptance.verdict 必须在枚举内（默认 yes|partial|no|auto；schema.enums.task_acceptance_verdict 存在则按其执行）",
    "T-VERDICT-TEXT": "tasks[].verdict 必须在 close 流程结论枚举内（默认 目标已实现|我方工作已完成，最终目标尚待确认|目标未实现；schema.enums.task_verdict 存在则按其执行）",
    "T-PLAN-HISTORY": "tasks[].plan_history 每项必须含 {archived_at(iso8601), reason(非空), plan(数组)}",
    "T-EVIDENCE-EMPTY": "completed_steps[].evidence 非空——无证据不得标记完成",
    "T-EV-ID": "evidence[].evidence_id 非空",
    "T-EV-SHAPE": "evidence 每项必须含 kind/description/source/recorded_at",
    "T-DECISION": "decisions 每项必须含 what/why",
    "T-BLOCKER": "blockers 每项必须含 blocker_id/description",
    "T-CHANGE": "changes 每项必须含 changed_at/what/why/impact（重规划不得就地覆盖旧计划）",
    "T-NBA": "next_best_action 必须含非空 action 与 reason",
    "T-CLOSED-AT": "status=completed 时 closed_at 必填",
    "T-HISTORY": "history 每项必须含 at/action/summary（只增不改）",
    "T-PLAN-EMPTY": "【警告】非终态任务不应是空计划",
    "T-EXTRA": "【说明】任务上的额外字段不拒绝，但会登记（schema.optional_fields 未覆盖）",
    "S-FILE": "state/user_skills.json 必须存在",
    "S-ROOT": "user_skills.json 根结构 = {skills: array, last_updated: iso8601}",
    "S-REQ": "每个技能条目必须含 schema.user_skills.required_fields 的全部字段",
    "S-ID-DUP": "skill_id 必须唯一",
    "S-ENUM": "status/privacy_scope 必须在 schema 枚举内",
    "S-WEAK-NAME": "skill_name 不得使用不可验证的弱表述（弱词黑名单）",
    "S-CONF": "confidence 必须是 {level: high|medium|low, basis: 非空}",
    "S-LASTVERIFIED": "last_verified_at 必须是 iso8601 或 null",
    "S-EVIDENCE-SHAPE": "evidence 每项必须含 kind/description/at，task_id 为 null 或存在的任务",
    "S-EVIDENCE-KIND": "evidence[].kind 必须在 schema.skill_evidence_kind 枚举内",
    "S-EVIDENCE-REQUIRED": "除 not_assessed 外，技能条目必须有证据",
    "S-UPGRADE": "status=can_independently 必须至少有一条 independent_operation 或 observed_test 证据（不得虚假升级）",
    "S-XREF-TASK": "related_tasks[] / evidence[].task_id 必须存在于 tasks.json",
    "S-GAPS": "known_gaps 必须是数组",
    "E-REQ": "每个经验条目必须含 schema.experiences.required_fields 的全部字段",
    "E-ID-FMT": r"experience_id 必须匹配 ^EXP-\d{8}-\d{3}$",
    "E-ID-DUP": "experience_id 必须全局唯一",
    "E-FILENAME": "经验文件名必须是 <experience_id>.json（一条一文件）",
    "E-ENUM": "domain/task_type/status/privacy_scope 必须在 schema 枚举内",
    "E-TRIGGER": "trigger_conditions 必须是非空数组——没有适用条件的经验不允许入库",
    "E-TAGS": "tags 必须是数组",
    "E-CONF": "confidence 必须是 {level,basis} 或非空文字",
    "E-OUTCOME": "observed_outcome.executed 必须是布尔值",
    "E-STATUS-CTX": "single_observation/repeatedly_supported 必须 executed=true 且 evidence 非空；executed=false 只能写 to_verify",
    "E-CLAIM": "executed=false 时不得写成结果性结论（如「显著提升效率」）",
    "E-SOURCE": "source_task_id 必须存在于 tasks.json",
    "E-XREF-SKILL": "related_skill_ids[] 必须存在于 user_skills.json",
    "E-XREF-METHOD": "related_method_ids[] 必须存在于 methods/index.json",
    "E-COUNTEREXAMPLE": "status=challenged_by_counterexample 必须记录具体反例（counterexamples 非空）",
    "E-OBSOLETE-REASON": "【警告】status=obsolete 应说明失效原因（limitations 非空）",
    "E-TIME": "created_at 必须是 iso8601；last_reviewed_at 为 iso8601 或 null；review_after 若存在必须是 iso8601",
    "E-STALE": "【警告】review_after 已过期 → 经验可能过时，需重新复核",
    "E-LIMITATIONS": "limitations/counterexamples 必须是数组",
    "E-PRIVACY-GENERAL": "【警告】privacy_scope=general 的经验条目命中高置信度机密特征（命中 ≠ 违规，需人工判断；本规则不阻断）",
    "E-PRIVACY-DETECTOR": "【未执行】数据层隐私检测无法加载检测器（复用 exp.privacy_hits）时记为未执行，不宣称隐私检查通过",
    "E-REVIEW-HISTORY": "experiences[].review_history 每项必须含 {at(iso8601), to_status(枚举), note(非空)}；from_status 若存在必须在枚举内",
    "E-COUNTEREXAMPLE-RES": "experiences[].counterexample_resolutions 每项必须含 {at(iso8601), resolution(非空)}；from_status 若存在必须在枚举内",
    "M-FILE": "methods/index.json（schema.methods.file，项目根）必须存在——缺失时本域不能记作「未执行=通过」",
    "M-ROOT": "methods/index.json 根结构 = {methods: array, last_updated: iso8601}",
    "M-REQ": "每个方法条目必须含 schema.methods.required_fields 的全部字段",
    "M-ID-DUP": "method_id 必须唯一",
    "M-ENUM": "verification_status 必须在 schema.method_verification 枚举内",
    "M-SOURCE": "source 必须是 {kind, citation, retrieved_at}，kind 在枚举内，公开框架必须给可核实来源",
    "M-UNVERIFIED": "verification_status=unverified 时必须有未验证范围说明（limitations 或含「未验证」的字段）",
    "M-ARRAY": "applicable_task_types/preconditions/not_applicable_when/steps 必须是数组",
    "M-SELECTION-FILE": "methods/selection_rules.json 必须存在（缺失时引用校验会退化为空真）",
    "M-SELECTION-ROOT": "selection_rules 根结构：rules 为数组，每项 recommend/avoid 为字符串数组",
    "M-SELECTION-EMPTY": "selection_rules 的引用总数为 0 → 成员校验必然空真，视为失败",
    "M-SELECTION-REF": "recommend/avoid/combination_rules.sequence 的**每一条字符串**都必须存在于 methods/index.json 的 method_id 集合（禁止任何前缀过滤）",
    "M-SELECTION-BASIS-REF": "basis_refs 中形如「methods/index.json → <method_id>.<字段>」的引用，其 method_id 必须存在",
    "M-INDEX-FILE": "methods/index.md 必须存在（派生产物，缺失即无法做漂移比对）",
    "M-INDEX-HASH": "index.md 文件头记录的「生成来源 SHA256」必须等于当前 methods/index.json 的 sha256",
    "M-INDEX-COVERAGE": "methods/index.json 中的每个 method_id 都必须出现在 index.md 中",
    "M-INDEX-EXTRA": "【警告】index.md 中出现了 methods/index.json 里没有的 method_id",
    "M-INDEX-RENDER": "调用生成器重渲染失败或生成器缺失（后者记为「未执行」，不宣称漂移检查通过）",
    "M-INDEX-DRIFT": "重渲染结果与现有 index.md 不一致（忽略「生成时间（UTC）」行）",
    "B-MANIFEST": "备份目录必须含 manifest.json",
    "B-MISSING": "备份内清单列出的文件必须存在",
    "B-HASH": "备份内每个文件的 sha256 必须与 manifest 一致",
    "B-RECORDS": "备份内每个文件的记录数必须与 manifest 一致",
    "B-SCHEMA": "【警告】备份 manifest 的 schema_version 与当前 schema 不一致",
}


def rule_ids() -> list[str]:
    return sorted(RULES)


# ---------------------------------------------------------------- 输出收集

@dataclass
class Report:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)  # 未能执行的检查（不宣称通过）
    checks: int = 0

    def check(self, count: int = 1) -> None:
        self.checks += count

    def error(self, rule: str, where: str, message: str) -> None:
        self.errors.append({"rule": rule, "where": where, "message": message})

    def warn(self, rule: str, where: str, message: str) -> None:
        self.warnings.append({"rule": rule, "where": where, "message": message})

    def note(self, message: str) -> None:
        self.notes.append(message)

    def skip_check(self, message: str) -> None:
        """记录一项未能执行的检查：既不通过也不失败，但会阻止「结论：通过」。"""
        self.not_run.append(message)

    def marks(self) -> tuple[int, int]:
        return len(self.errors), len(self.warnings)


# ---------------------------------------------------------------- 上下文

@dataclass
class Context:
    state_dir: Path
    schema: dict
    enums: dict
    tasks: list
    skills: list
    experiences: list
    methods: list
    task_ids: set
    skill_ids: set
    method_ids: set
    experience_ids: set
    files: dict  # 域 -> "ok" | "missing" | "broken"
    renderer: Path | None = None  # --renderer 覆盖（默认查 <项目根>/methods/methods-renderer.py）


def enum_or_default(ctx: Context, key: str, defaults: tuple) -> tuple:
    """优先用 schema.enums 的定义；schema 未登记时退回实现来源的默认值（来源写在常量注释与本轮报告里）。"""
    values = ctx.enums.get(key)
    if isinstance(values, list) and values:
        return tuple(values)
    return defaults


def rel(path: Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(store.PROJECT_ROOT))
    except ValueError:
        return str(path)


def _read_json(path: Path, report: Report) -> object:
    """通过 store.read_json 读取（唯一的读入口），损坏时登记错误并返回 _BROKEN。"""
    if not path.exists():
        return _MISSING
    try:
        return store.read_json(path)
    except store.StoreError as exc:
        report.error("JSON-BROKEN", rel(path), f"数据文件无法解析：{exc}")
        return _BROKEN


def _array_of_strings(value) -> bool:
    """非空数组，且每项为非空字符串（空数组不算通过——schema 要求 success_criteria/trigger_conditions 非空）。"""
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _iso_or_null(value) -> bool:
    return value is None or store.is_iso8601(value)


def load_schema(state_dir: Path, report: Report) -> dict:
    local = Path(state_dir) / "schema.json"
    schema_path = local if local.exists() else store.SCHEMA_PATH
    try:
        schema = store.read_json(schema_path)
    except store.StoreError as exc:
        raise store.StoreError(f"数据契约无法解析：{schema_path}（{exc}）") from exc
    if not isinstance(schema, dict):
        raise store.StoreError(f"数据契约格式不符合预期（应为 JSON 对象）：{schema_path}")
    report.note(f"契约文件：{rel(schema_path)}（schema_version {schema.get('schema_version')}）")
    return schema


def project_root_for(state_dir: Path) -> Path:
    """真实 state 目录 → 项目根；--state-dir 样本树 → 样本树的根（state 的父目录）。"""
    if Path(state_dir).resolve() == store.STATE_DIR.resolve():
        return store.PROJECT_ROOT
    return Path(state_dir).resolve().parent


def methods_path(state_dir: Path, schema: dict) -> Path:
    """按 schema.methods.file 解析方法库路径。

    * 真实 state 目录：用 store.METHODS_PATH（项目根 methods/index.json，与 status.py、IMPLEMENTATION_PLAN §4.1 一致）；
    * --state-dir 指向样本树时：用 <state_dir>/../<schema.methods.file>，让样本自带方法库而不去读真实项目文件。
    """
    relative = (schema.get("methods", {}) or {}).get("file", "methods/index.json")
    return project_root_for(state_dir) / relative


def load_context(state_dir: Path, schema: dict, report: Report, renderer: Path | None = None) -> Context:
    state_dir = Path(state_dir)
    tasks_raw = _read_json(state_dir / "tasks.json", report)
    skills_raw = _read_json(state_dir / "user_skills.json", report)
    methods_raw = _read_json(methods_path(state_dir, schema), report)

    experience_dir = state_dir / "experience"
    experiences: list[dict] = []
    exp_map: dict[str, Path] = {}
    if experience_dir.exists():
        for path in sorted(experience_dir.glob("*.json")):
            data = _read_json(path, report)
            if isinstance(data, dict):
                experiences.append(data)
                exp_map[str(data.get("experience_id") or f"(缺 experience_id: {rel(path)})")] = path

    tasks = tasks_raw.get("tasks") if isinstance(tasks_raw, dict) and isinstance(tasks_raw.get("tasks"), list) else []
    skills = skills_raw.get("skills") if isinstance(skills_raw, dict) and isinstance(skills_raw.get("skills"), list) else []
    methods = methods_raw.get("methods") if isinstance(methods_raw, dict) and isinstance(methods_raw.get("methods"), list) else []

    ctx = Context(
        state_dir=state_dir,
        schema=schema,
        enums=schema.get("enums", {}),
        tasks=tasks,
        skills=skills,
        experiences=experiences,
        methods=methods,
        task_ids={t.get("task_id") for t in tasks if isinstance(t, dict) and t.get("task_id")},
        skill_ids={s.get("skill_id") for s in skills if isinstance(s, dict) and s.get("skill_id")},
        method_ids={m.get("method_id") for m in methods if isinstance(m, dict) and m.get("method_id")},
        experience_ids={e.get("experience_id") for e in experiences if isinstance(e, dict) and e.get("experience_id")},
        files={
            "tasks": "missing" if tasks_raw is _MISSING else ("broken" if tasks_raw is _BROKEN else "ok"),
            "skills": "missing" if skills_raw is _MISSING else ("broken" if skills_raw is _BROKEN else "ok"),
            "methods": "missing" if methods_raw is _MISSING else ("broken" if methods_raw is _BROKEN else "ok"),
            "experience": "ok" if experience_dir.exists() else "missing",
        },
        renderer=Path(renderer) if renderer else None,
    )
    ctx.exp_map = exp_map  # type: ignore[attr-defined]
    return ctx


def _root_check(report: Report, rule: str, where: str, data, array_key: str, enums: dict) -> list:
    """校验形如 {<array_key>: [...], last_updated: iso8601} 的根结构，返回数组（异常时为空）。"""
    if not isinstance(data, dict):
        report.check()
        report.error("T-ROOT" if array_key == "tasks" else rule, where, "根结构必须是 JSON 对象")
        return []
    report.check()
    if not isinstance(data.get(array_key), list):
        report.error(rule, where, f"根结构缺少数组字段 {array_key}（或类型不是数组）")
        return []
    report.check()
    if not _iso_or_null(data.get("last_updated")):
        report.error(rule, where, f"last_updated 必须是 ISO8601（收到 {data.get('last_updated')!r}）")
    return data[array_key]


# ---------------------------------------------------------------- 任务域

def check_tasks(ctx: Context, report: Report) -> int:
    spec = ctx.schema.get("tasks", {})
    required = list(spec.get("required_fields", []))
    optional = list(spec.get("optional_fields", []))
    step_required = list(spec.get("step_required_fields", []))
    data = _read_json(ctx.state_dir / "tasks.json", report)

    if data is _MISSING:
        report.check()
        report.error("T-FILE", rel(ctx.state_dir / "tasks.json"), "任务数据文件不存在（任务状态是必需域）")
        return 0
    if data is _BROKEN:
        return 0

    tasks = _root_check(report, "T-ROOT", rel(ctx.state_dir / "tasks.json"), data, "tasks", ctx.enums)

    seen_ids: dict[str, int] = {}
    extras: set[str] = set()
    legacy_refs: list[tuple] = []  # 1.0 字段名待迁移清单：(任务位置, step_id, 字段名, 值)
    for index, task in enumerate(tasks):
        where = f"tasks.json → tasks[{index}]"
        if not isinstance(task, dict):
            report.check()
            report.error("T-PLAN-ITEM", where, "任务记录必须是 JSON 对象")
            continue

        # 必填字段
        for fieldname in required:
            report.check()
            if fieldname not in task:
                report.error("T-REQ", where, f"缺少必填字段：{fieldname}")
                continue
            value = task[fieldname]
            if fieldname in TASK_ARRAY_FIELDS:
                if not isinstance(value, list):
                    report.error("T-ARRAY", where, f"{fieldname} 必须是数组（收到 {type(value).__name__}）")
            elif not _nonempty(value):
                report.error("T-REQ", where, f"必填字段为空：{fieldname}")

        # 额外字段（登记，不失败）
        extras |= set(task) - set(required) - set(optional)

        # task_id
        task_id = task.get("task_id")
        report.check()
        if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
            report.error("T-ID-FMT", where, f"task_id 不符合 ^TN-\\d{{8}}-\\d{{3}}$：{task_id!r}")
        else:
            report.check()
            if task_id in seen_ids:
                report.error("T-ID-DUP", where, f"task_id 重复：{task_id}（已在 tasks[{seen_ids[task_id]}] 出现）")
            else:
                seen_ids[task_id] = index

        # 枚举
        for fieldname, enum_key in (
            ("domain", "domain"),
            ("task_type", "task_type"),
            ("status", "task_status"),
            ("planning_depth", "planning_depth"),
            ("retrospective_status", "retrospective_status"),
        ):
            report.check()
            allowed = ctx.enums.get(enum_key, [])
            if task.get(fieldname) not in allowed:
                report.error("T-ENUM", where, f"{fieldname}={task.get(fieldname)!r} 不在枚举 {allowed} 内")

        # 时间戳
        for fieldname in ("created_at", "updated_at", "closed_at"):
            if fieldname in task and task.get(fieldname) is not None:
                report.check()
                if not store.is_iso8601(task[fieldname]):
                    report.error("T-TIME", where, f"{fieldname} 不是 ISO8601：{task[fieldname]!r}")

        # 成功标准
        report.check()
        if not _array_of_strings(task.get("success_criteria")):
            report.error("T-CRITERIA", where, "success_criteria 必须是非空数组且每项为非空文字")

        # spec/01 §4A：有外部发起人的任务应填 decision_authority
        if _nonempty(task.get("requester_or_beneficiary")):
            report.check()
            da = task.get("decision_authority")
            if not isinstance(da, dict) or not da:
                report.warn(
                    "T-DECISION-AUTH", where,
                    f"该任务有外部发起人（{task['requester_or_beneficiary']}）但未填 decision_authority"
                    "——spec/01 §4A 要求分清「可自行决定什么」与「什么需询问发起人」",
                )
            elif not isinstance(da.get("can_decide_alone"), list) or not isinstance(da.get("must_ask"), list):
                report.error(
                    "T-DECISION-AUTH", where,
                    "decision_authority 必须是 {can_decide_alone: [...], must_ask: [{question, whom}]} 结构",
                )

        # T-USAGE-REF：methods_used / experiences_used 的引用必须真实存在（核审 t25 的 N6）
        for field, id_key, known, label in (
            ("methods_used", "method_id", ctx.method_ids, "methods/index.json"),
            ("experiences_used", "experience_id", ctx.experience_ids, "state/experience/"),
        ):
            entries = task.get(field)
            if not entries:
                continue
            if not isinstance(entries, list):
                report.error("T-USAGE-REF", f"{where}.{field}", f"{field} 必须是数组")
                continue
            for uindex, entry in enumerate(entries):
                uwe = f"{where}.{field}[{uindex}]"
                report.check()
                if not isinstance(entry, dict):
                    report.error("T-USAGE-REF", uwe, "每项必须是对象")
                    continue
                ref = entry.get(id_key)
                if ref and ref not in known:
                    report.error("T-USAGE-REF", uwe, f"{id_key}={ref!r} 不存在于 {label}")
                if field == "experiences_used" and not _nonempty(entry.get("why_applicable")):
                    report.error("T-USAGE-REF", uwe, "experiences_used 每项必须写明 why_applicable（为什么适用）")
                # 循环引用检查：经验不得源自本任务自身
                if field == "experiences_used" and ref:
                    exp_path = ctx.state_dir / "experience" / f"{ref}.json"
                    if exp_path.is_file():
                        try:
                            exp = json.loads(exp_path.read_text(encoding="utf-8"))
                            if exp.get("source_task_id") == task.get("task_id"):
                                report.error(
                                    "T-EXP-SELF-REF", uwe,
                                    f"经验 {ref} 源自本任务自身（source_task_id={task.get('task_id')}）——"
                                    "用本任务的产出去论证本任务的做法属循环论证，应改为引用其他任务的经验，"
                                    "或直接删掉这条 experiences_used",
                                )
                        except Exception as exc:
                            # **不要静默**：这里曾吞掉一个 NameError（validate.py 未 import json），
                            # 导致本规则从未真正执行却看起来正常。
                            report.error(
                                "T-EXP-SELF-REF", uwe,
                                f"读取经验文件失败，无法判定是否循环引用：{type(exc).__name__}: {exc}",
                            )

        # 复盘覆盖率（spec/00 阶段1-9/10）：机制存在但常被跳过。
        # 做成警告而非错误——目的是让它每次校验都被看见，而不是阻断工作。
        if task.get("status") in ("completed", "awaiting_acceptance", "cancelled"):
            report.check()
            if task.get("retrospective_status") != "reviewed":
                report.warn(
                    "T-RETRO-COVERAGE", where,
                    f"任务已达「{task['status']}」但复盘状态为 "
                    f"{task.get('retrospective_status') or '未设置'}——"
                    "复盘机制存在但被跳过（spec/00 阶段1-9/10 要求复盘后筛选性更新经验与技能）",
                )

        # 计划
        plan = task.get("plan")
        report.check()
        if not isinstance(plan, list):
            report.error("T-PLAN", where, "plan 必须是数组")
            plan = []
        depth = task.get("planning_depth")
        step_ids: set[str] = set()
        for sindex, step in enumerate(plan):
            swe = f"{where}.plan[{sindex}]"
            report.check()
            if not isinstance(step, dict):
                report.error("T-PLAN-ITEM", swe, "步骤必须是 JSON 对象")
                continue
            step_id = step.get("step_id")
            report.check()
            if not isinstance(step_id, str) or not step_id.strip():
                report.error("T-STEP-REQ", swe, "step_id 必须是非空字符串")
            elif step_id in step_ids:
                report.error("T-STEP-DUP", swe, f"step_id 重复：{step_id}")
            else:
                step_ids.add(step_id)

            fields = ["step_id", "name", "actions"] if depth == "light" else step_required
            for fieldname in fields:
                report.check()
                if not _nonempty(step.get(fieldname)):
                    report.error(
                        "T-STEP-REQ", swe,
                        f"步骤缺少必填字段 {fieldname}"
                        + ("（standard/deep 深度不允许省略）" if depth != "light" else ""),
                    )
            for fieldname in ("actions", "required_skills", "inputs_or_dependencies", "risks_and_fallbacks", "communication"):
                if fieldname in step:
                    report.check()
                    if not isinstance(step[fieldname], list):
                        report.error("T-STEP-REQ", swe, f"{fieldname} 必须是数组")

            # t21：执行者机械门禁（SKILL.md §0.4.1 计划自检表 / reference/skill_adaptation.md §6.1）。
            # 枚举与必填性取自 schema.tasks.step_executor_fields，避免校验器里写死第二份真相。
            # light 深度同样强制：没有动作的步骤不是步骤，没有执行者的步骤同样不是。
            executor_spec = spec.get("step_executor_fields", {}) or {}
            executor_fields = executor_spec.get("fields", {}) or {}
            executor_enum = list((executor_fields.get("executor", {}) or {}).get("enum", []) or [])
            reason_enum = list((executor_fields.get("delegation_reason", {}) or {}).get("enum", []) or [])
            executor = step.get("executor")
            reason = step.get("delegation_reason")
            report.check()
            if not _nonempty(executor):
                report.error(
                    "T-STEP-EXECUTOR", swe,
                    "步骤缺少执行者 executor（user=用户做 / ai=AI 做 / joint=共同做）"
                    "——缺执行者视为计划不完整，请先想清楚这一步该谁做",
                )
            elif executor_enum and executor not in executor_enum:
                report.error("T-STEP-EXECUTOR-ENUM", swe, f"executor 必须是 {executor_enum} 之一，收到 {executor!r}")
            report.check()
            if not _nonempty(step.get("executor_basis")):
                report.error(
                    "T-STEP-EXECUTOR-BASIS", swe,
                    "步骤缺少 executor_basis（为什么由该方执行）——默认规则：用户自己的生活/工作/学习事务"
                    "默认用户做、AI 指导；只写执行者名字不算表态",
                )
            if executor == "ai":
                report.check()
                if not _nonempty(reason):
                    report.error(
                        "T-STEP-DELEGATION", swe,
                        f"executor=ai 但缺少 delegation_reason（四选一：{'/'.join(reason_enum) or '极紧期限/高代价/纯机械劳动/用户明确要求'}）"
                        "——AI 代做必须有理由",
                    )
                elif reason_enum and reason not in reason_enum:
                    report.error("T-STEP-DELEGATION-ENUM", swe, f"delegation_reason 必须是 {reason_enum} 之一，收到 {reason!r}")
            elif _nonempty(reason):
                report.check()
                report.warn(
                    "T-STEP-DELEGATION-STALE", swe,
                    f"executor={executor!r} 却保留了 delegation_reason={reason!r}（那是 AI 代做的理由）——请删除或改回 executor=ai",
                )

            # G4（spec/01 §4E）：standard/deep 下这四项必须有内容或显式写明理由。
            # 只在提交时强制不够——历史数据与手工编辑也要能被查出来。
            if depth in ("standard", "deep"):
                for field in ("inputs_or_dependencies", "risks_and_fallbacks", "communication"):
                    values = step.get(field)
                    report.check()
                    if not values:
                        report.error(
                            "T-STEP-COMPLETENESS", f"{swe}.{field}",
                            f"{depth} 档位下步骤必须写明 {field}——确实不适用时请显式写理由"
                            "（例如 [\"不适用：无外部依赖方\"]），不要留空。"
                            "spec/01 §4E 要求每步九项完整",
                        )
                report.check()
                if not _nonempty(step.get("time_estimate")):
                    report.error(
                        "T-STEP-COMPLETENESS", f"{swe}.time_estimate",
                        f"{depth} 档位下步骤必须给出预计耗时（不确定时写区间并给估算依据）",
                    )

            # 技能适配落点（spec/01 §4D）：自由文本引用必须写明状态未知
            skills_req = step.get("required_skills") or []
            for rindex, item in enumerate(skills_req):
                rwe = f"{swe}.required_skills[{rindex}]"
                report.check()
                if not isinstance(item, dict):
                    report.error("T-STEP-SKILL", rwe, "每项技能需求必须是对象")
                    continue

                # schema 1.1：skill_ref 必填，取值为并集语义（档案 skill_id 或描述性自由文本）。
                # 1.0 的字段名（free_text / skill_id）仍可读取，但登记为待迁移（警告，不硬失败）。
                ref = item.get("skill_ref")
                if not ref:
                    legacy_field = "skill_id" if item.get("skill_id") else ("free_text" if item.get("free_text") else None)
                    if legacy_field is None:
                        report.error(
                            "T-STEP-SKILL", rwe,
                            "既没有 skill_ref（schema 1.1 必填），也没有 1.0 的 skill_id / free_text——无法解析该技能需求",
                        )
                    else:
                        legacy_refs.append((where, step.get("step_id"), legacy_field, str(item.get(legacy_field))))
                        if legacy_field == "skill_id":
                            ref = item.get("skill_id")  # 旧字段名也可能指向档案 id，仍做交叉引用
                if ref:
                    report.check()
                    # 并集语义：只有「等于档案中现有 skill_id」或「形如 SK-… id」才强制交叉引用；自由文本不查档案
                    if str(ref) in ctx.skill_ids or SKILL_ID_RE.match(str(ref)):
                        if str(ref) not in ctx.skill_ids:
                            report.error(
                                "T-XREF-SKILL", rwe,
                                f"{ref} 形如技能 id（^SK-\\d{{8}}-\\d{{3}}$）但不存在于 user_skills.json——悬空引用",
                            )

                    # 技能适配落点（spec/01 §4D / spec/03 §4）：
                    # 自由文本引用意味着「这项技能不在档案里」→ 其用户状态未知 →
                    # 必须显式写明，否则「按技能状态决定指导方式」在这条路径上失效。
                    # 全量核对实测：36 条引用中 30 条是自由文本且无任何状态说明。
                    if depth in ("standard", "deep") and not str(ref) in ctx.skill_ids \
                            and not SKILL_ID_RE.match(str(ref)):
                        report.check()
                        if not (item.get("gap") or item.get("archive_status")):
                            report.warn(
                                "T-SKILL-GAP", rwe,
                                f"技能引用 {ref!r} 不在档案中（自由文本），但未写明 gap 或 archive_status——"
                                "请显式标注该技能状态未评估，例如 "
                                '{"skill_ref": "需求澄清", "gap": "未评估，按 can_with_checklist 对待"}',
                            )

            if "status" in step:
                report.check()
                if step.get("status") not in ctx.enums.get("step_status", []):
                    report.error("T-STEP-STATUS", swe, f"status={step.get('status')!r} 不在 step_status 枚举内")

        if isinstance(plan, list) and not plan and task.get("status") in OPEN_TASK_STATUSES:
            report.check()
            report.warn("T-PLAN-EMPTY", where, f"任务仍在进行（status={task.get('status')}）但计划为空")

        # 完成步骤
        completed = task.get("completed_steps")
        report.check()
        if not isinstance(completed, list):
            report.error("T-ARRAY", where, "completed_steps 必须是数组")
            completed = []
        for cindex, record in enumerate(completed):
            cwe = f"{where}.completed_steps[{cindex}]"
            report.check()
            if not isinstance(record, dict):
                report.error("T-EVIDENCE-EMPTY", cwe, "完成记录必须是对象")
                continue
            step_id = record.get("step_id")
            report.check()
            if step_id not in step_ids:
                report.error("T-XREF-STEP", cwe, f"step_id {step_id!r} 不在同任务的 plan 中")
            report.check()
            if not store.is_iso8601(record.get("completed_at")):
                report.error("T-TIME", cwe, f"completed_at 不是 ISO8601：{record.get('completed_at')!r}")
            report.check()
            if not _nonempty(record.get("evidence")):
                report.error("T-EVIDENCE-EMPTY", cwe, "evidence 为空——无证据不得标记完成")

        # 证据清单
        evidence_list = task.get("evidence")
        report.check()
        if not isinstance(evidence_list, list):
            report.error("T-ARRAY", where, "evidence 必须是数组")
            evidence_list = []
        for eindex, evidence in enumerate(evidence_list):
            ewe = f"{where}.evidence[{eindex}]"
            report.check()
            if not isinstance(evidence, dict):
                report.error("T-EV-SHAPE", ewe, "证据必须是对象")
                continue
            if not _nonempty(evidence.get("evidence_id")):
                report.error("T-EV-ID", ewe, "evidence_id 必须非空")
                continue
            for fieldname in ("kind", "description", "source", "recorded_at"):
                report.check()
                if not _nonempty(evidence.get(fieldname)):
                    report.error("T-EV-SHAPE", ewe, f"缺少或为空：{fieldname}")

        # 决定 / 阻碍 / 变更
        for dindex, decision in enumerate(task.get("decisions") or []):
            report.check()
            if not isinstance(decision, dict) or not _nonempty(decision.get("what")) or not _nonempty(decision.get("why")):
                report.error("T-DECISION", f"{where}.decisions[{dindex}]", "决定必须含非空 what 与 why")
        for bindex, blocker in enumerate(task.get("blockers") or []):
            report.check()
            if not isinstance(blocker, dict) or not _nonempty(blocker.get("blocker_id")) or not _nonempty(blocker.get("description")):
                report.error("T-BLOCKER", f"{where}.blockers[{bindex}]", "阻碍必须含非空 blocker_id 与 description")
        for chindex, change in enumerate(task.get("changes") or []):
            report.check()
            bad = not isinstance(change, dict) or any(
                not _nonempty(change.get(f)) for f in ("changed_at", "what", "why", "impact")
            )
            if bad:
                report.error("T-CHANGE", f"{where}.changes[{chindex}]", "计划变更必须含 changed_at/what/why/impact")

        # 下一步
        nba = task.get("next_best_action")
        report.check()
        if not isinstance(nba, dict) or not _nonempty(nba.get("action")) or not _nonempty(nba.get("reason")):
            report.error("T-NBA", where, "next_best_action 必须是含非空 action 与 reason 的对象")

        # 关闭一致性
        report.check()
        if task.get("status") == "completed" and not _nonempty(task.get("closed_at")):
            report.error("T-CLOSED-AT", where, "status=completed 但缺少 closed_at")

        # 验收对象（schema 1.1 新登记）：三问 verdict + basis 非空（对应 task_update.py close 的强制项）
        acceptance = task.get("acceptance")
        if acceptance is not None:
            report.check()
            if not isinstance(acceptance, dict):
                report.error("T-ACCEPTANCE", f"{where}.acceptance", "acceptance 必须是对象")
            else:
                for question in ACCEPTANCE_QUESTIONS:
                    report.check()
                    answer = acceptance.get(question)
                    if (
                        not isinstance(answer, dict)
                        or answer.get("verdict") not in QUESTION_VERDICTS
                        or not _nonempty(answer.get("basis"))
                    ):
                        report.error(
                            "T-ACCEPTANCE", f"{where}.acceptance.{question}",
                            f"验收三问必须是 {{verdict: yes|partial|no, basis: 非空}}，收到 {answer!r}",
                        )
                for listfield in ("pending_external", "incomplete_steps_at_close"):
                    if listfield in acceptance:
                        report.check()
                        if not isinstance(acceptance[listfield], list):
                            report.error("T-ACCEPTANCE", f"{where}.acceptance.{listfield}", f"{listfield} 必须是数组")
                if acceptance.get("closed_at") is not None:
                    report.check()
                    if not store.is_iso8601(acceptance["closed_at"]):
                        report.error(
                            "T-ACCEPTANCE", f"{where}.acceptance.closed_at",
                            f"closed_at 不是 ISO8601：{acceptance['closed_at']!r}",
                        )
                if "verdict" in acceptance:
                    report.check()
                    allowed = enum_or_default(ctx, "task_acceptance_verdict", DEFAULT_ACCEPTANCE_VERDICTS)
                    if acceptance.get("verdict") not in allowed:
                        report.error(
                            "T-VERDICT", f"{where}.acceptance.verdict",
                            f"acceptance.verdict={acceptance.get('verdict')!r} 不在枚举 {list(allowed)} 内",
                        )

        # 任务级结论（task_update.py close 写入的 machine 结论）
        if "verdict" in task:
            report.check()
            allowed = enum_or_default(ctx, "task_verdict", DEFAULT_TASK_VERDICTS)
            if task.get("verdict") not in allowed:
                report.error(
                    "T-VERDICT-TEXT", f"{where}.verdict",
                    f"verdict={task.get('verdict')!r} 不在 close 流程结论枚举 {list(allowed)} 内"
                    "（若确实需要自由文本，请在 state/schema.json 的 enums 中登记 task_verdict）",
                )

        # 计划归档（schema 1.1 新登记）：重规划不得静默覆盖旧计划
        plan_history = task.get("plan_history")
        if plan_history is not None:
            report.check()
            if not isinstance(plan_history, list):
                report.error("T-PLAN-HISTORY", f"{where}.plan_history", "plan_history 必须是数组")
                plan_history = []
            for pindex, archived in enumerate(plan_history):
                pwe = f"{where}.plan_history[{pindex}]"
                report.check()
                if (
                    not isinstance(archived, dict)
                    or not store.is_iso8601(archived.get("archived_at"))
                    or not _nonempty(archived.get("reason"))
                    or not isinstance(archived.get("plan"), list)
                ):
                    report.error(
                        "T-PLAN-HISTORY", pwe,
                        "归档项必须含 {archived_at: ISO8601, reason: 非空, plan: 数组}",
                    )

        # 历史
        history = task.get("history")
        report.check()
        if not isinstance(history, list) or not history:
            report.error("T-HISTORY", where, "history 必须是非空数组（每次写入追加一条）")
            history = history if isinstance(history, list) else []
        for hindex, entry in enumerate(history):
            report.check()
            if not isinstance(entry, dict) or any(
                not _nonempty(entry.get(f)) for f in ("at", "action", "summary")
            ):
                report.error("T-HISTORY", f"{where}.history[{hindex}]", "历史条目必须含 at/action/summary")

    if legacy_refs:
        by_task: dict[str, list[str]] = {}
        for where_text, step_id, fieldname, value in legacy_refs:
            by_task.setdefault(where_text, []).append(f"{step_id or '?'}.{fieldname}={value}")
        for where_text, items in by_task.items():
            report.check()
            report.warn(
                "T-STEP-SKILL-LEGACY", where_text,
                f"仍有 {len(items)} 条 required_skills 使用 1.0 字段名（缺 skill_ref），待迁移为 skill_ref："
                + "；".join(items),
            )

    if extras:
        report.check()
        report.note(
            "T-EXTRA：tasks 上存在 schema 未列出的字段 "
            + "、".join(sorted(extras))
            + "（由 task_update.py 写入；不视为失败，已作为契约偏差记入 reports/STORAGE_VERIFICATION.md）"
        )
    return len(tasks)


# ---------------------------------------------------------------- 技能域

def check_skills(ctx: Context, report: Report) -> int:
    spec = ctx.schema.get("user_skills", {})
    required = list(spec.get("required_fields", []))
    data = _read_json(ctx.state_dir / "user_skills.json", report)

    if data is _MISSING:
        report.check()
        report.error("S-FILE", rel(ctx.state_dir / "user_skills.json"), "个人技能档案不存在")
        return 0
    if data is _BROKEN:
        return 0

    skills = _root_check(report, "S-ROOT", rel(ctx.state_dir / "user_skills.json"), data, "skills", ctx.enums)
    seen: dict[str, int] = {}
    upgrade_evidence_kinds = ("independent_operation", "observed_test")

    for index, skill in enumerate(skills):
        where = f"user_skills.json → skills[{index}]"
        if not isinstance(skill, dict):
            report.check()
            report.error("S-REQ", where, "技能条目必须是 JSON 对象")
            continue

        for fieldname in required:
            report.check()
            if fieldname not in skill:
                report.error("S-REQ", where, f"缺少必填字段：{fieldname}")
                continue
            if fieldname in ("evidence", "known_gaps", "related_tasks"):
                if not isinstance(skill[fieldname], list):
                    report.error("S-REQ", where, f"{fieldname} 必须是数组")
            elif fieldname in NULLABLE_REQUIRED_FIELDS["user_skills"]:
                continue  # schema 允许 null，格式由 S-LASTVERIFIED 校验
            elif not _nonempty(skill[fieldname]):
                report.error("S-REQ", where, f"必填字段为空：{fieldname}")

        skill_id = skill.get("skill_id")
        report.check()
        if not _nonempty(skill_id):
            report.error("S-REQ", where, "skill_id 必须是非空字符串")
        else:
            report.check()
            if skill_id in seen:
                report.error("S-ID-DUP", where, f"skill_id 重复：{skill_id}（已在 skills[{seen[skill_id]}] 出现）")
            else:
                seen[skill_id] = index

        for fieldname, enum_key in (("status", "skill_status"), ("privacy_scope", "privacy_scope")):
            report.check()
            allowed = ctx.enums.get(enum_key, [])
            if skill.get(fieldname) not in allowed:
                report.error("S-ENUM", where, f"{fieldname}={skill.get(fieldname)!r} 不在枚举 {allowed} 内")

        # 弱词黑名单：skill_name 必须可验证
        name = skill.get("skill_name")
        report.check()
        if isinstance(name, str) and any(term in name for term in WEAK_SKILL_NAME_TERMS):
            hits = [t for t in WEAK_SKILL_NAME_TERMS if t in name]
            report.error(
                "S-WEAK-NAME", where,
                f"skill_name 含不可验证的弱表述 {hits}：{name!r}——请改写成可验证的具体能力",
            )

        confidence = skill.get("confidence")
        report.check()
        if (
            not isinstance(confidence, dict)
            or confidence.get("level") not in ("high", "medium", "low")
            or not _nonempty(confidence.get("basis"))
        ):
            report.error("S-CONF", where, "confidence 必须是 {level: high|medium|low, basis: 非空字符串}")

        report.check()
        if not _iso_or_null(skill.get("last_verified_at")):
            report.error("S-LASTVERIFIED", where, f"last_verified_at 不是 ISO8601 或 null：{skill.get('last_verified_at')!r}")

        report.check()
        if not isinstance(skill.get("known_gaps"), list):
            report.error("S-GAPS", where, "known_gaps 必须是数组")

        evidence_list = skill.get("evidence") or []
        kinds: list[str] = []
        for eindex, evidence in enumerate(evidence_list):
            ewe = f"{where}.evidence[{eindex}]"
            report.check()
            if not isinstance(evidence, dict):
                report.error("S-EVIDENCE-SHAPE", ewe, "证据必须是对象")
                continue
            if not _nonempty(evidence.get("description")):
                report.error("S-EVIDENCE-SHAPE", ewe, "缺少或为空：description")
            if not store.is_iso8601(evidence.get("at")):
                report.error("S-EVIDENCE-SHAPE", ewe, f"at 不是 ISO8601：{evidence.get('at')!r}")
            kind = evidence.get("kind")
            report.check()
            if kind not in ctx.enums.get("skill_evidence_kind", []):
                report.error("S-EVIDENCE-KIND", ewe, f"kind={kind!r} 不在 skill_evidence_kind 枚举内")
            else:
                kinds.append(str(kind))
            task_ref = evidence.get("task_id")
            if task_ref is not None:
                report.check()
                if task_ref not in ctx.task_ids:
                    report.error("S-XREF-TASK", ewe, f"task_id {task_ref!r} 不存在于 tasks.json")
        # S-RELATED-TASKS：related_tasks 必须与 evidence 里的 task_id 集合一致。
        # 实测发生过：复盘往 evidence 追加了条目，但没更新 related_tasks，
        # 导致「这条技能靠哪些任务验证」失去可信来源。
        report.check()
        _ev_tasks = sorted({e.get("task_id") for e in (skill.get("evidence") or [])
                            if isinstance(e, dict) and e.get("task_id")})
        _rt = sorted(skill.get("related_tasks") or [])
        if _ev_tasks != _rt:
            report.error(
                "S-RELATED-TASKS", where,
                f"related_tasks={_rt or '[]'} 与 evidence 里的 task_id={_ev_tasks or '[]'} 不一致"
                "——两者必须相同，否则无法追溯这条技能是由哪些任务验证的",
            )

        for tindex, task_ref in enumerate(skill.get("related_tasks") or []):
            report.check()
            if task_ref not in ctx.task_ids:
                report.error("S-XREF-TASK", f"{where}.related_tasks[{tindex}]", f"{task_ref!r} 不存在于 tasks.json")

        status = skill.get("status")
        if status and status != "not_assessed":
            report.check()
            if not evidence_list:
                report.error("S-EVIDENCE-REQUIRED", where, f"status={status} 但没有证据（只有 not_assessed 允许空证据）")
        if status == "can_independently":
            report.check()
            if not any(kind in upgrade_evidence_kinds for kind in kinds):
                report.error(
                    "S-UPGRADE", where,
                    "status=can_independently 但没有 independent_operation / observed_test 证据，"
                    f"现有证据类型：{kinds or '（无）'}——不得虚假升级",
                )

    return len(skills)


# ---------------------------------------------------------------- 经验域

def check_experience(entry: dict, where: str, ctx: Context, report: Report, filename: str | None = None) -> None:
    """单条经验的规则校验（validate.py 与 exp.py add 共用，保证只有一份规则）。"""
    spec = ctx.schema.get("experiences", {})
    required = list(spec.get("required_fields", []))
    today = store.now_iso()[:10]

    if not isinstance(entry, dict):
        report.check()
        report.error("E-REQ", where, "经验条目必须是 JSON 对象")
        return

    for fieldname in required:
        report.check()
        if fieldname not in entry:
            report.error("E-REQ", where, f"缺少必填字段：{fieldname}")
            continue
        if fieldname in ("tags", "trigger_conditions", "evidence", "limitations", "counterexamples"):
            if not isinstance(entry[fieldname], list):
                report.error("E-REQ", where, f"{fieldname} 必须是数组")
        elif fieldname in ("observed_outcome", "confidence"):
            if not isinstance(entry[fieldname], dict):
                report.error("E-REQ", where, f"{fieldname} 必须是对象")
        elif fieldname in NULLABLE_REQUIRED_FIELDS["experiences"]:
            continue  # schema 允许 null，格式由 E-TIME 校验
        elif not _nonempty(entry[fieldname]):
            report.error("E-REQ", where, f"必填字段为空：{fieldname}")

    experience_id = entry.get("experience_id")
    report.check()
    if not isinstance(experience_id, str) or not EXPERIENCE_ID_RE.match(experience_id):
        report.error("E-ID-FMT", where, f"experience_id 不符合 ^EXP-\\d{{8}}-\\d{{3}}$：{experience_id!r}")

    report.check()
    if filename is not None and experience_id and filename != f"{experience_id}.json":
        report.error("E-FILENAME", where, f"文件名应为 {experience_id}.json，实际 {filename}")

    for fieldname, enum_key in (
        ("domain", "domain"),
        ("task_type", "task_type"),
        ("status", "experience_status"),
        ("privacy_scope", "privacy_scope"),
    ):
        report.check()
        allowed = ctx.enums.get(enum_key, [])
        if entry.get(fieldname) not in allowed:
            report.error("E-ENUM", where, f"{fieldname}={entry.get(fieldname)!r} 不在枚举 {allowed} 内")

    report.check()
    if not _array_of_strings(entry.get("trigger_conditions")):
        report.error("E-TRIGGER", where, "trigger_conditions 必须是非空数组且每项为非空文字——没有适用条件的经验不允许入库")

    report.check()
    if not isinstance(entry.get("tags"), list):
        report.error("E-TAGS", where, "tags 必须是数组")

    confidence = entry.get("confidence")
    report.check()
    if isinstance(confidence, dict):
        if confidence.get("level") not in ("high", "medium", "low") or not _nonempty(confidence.get("basis")):
            report.error("E-CONF", where, "confidence 对象必须是 {level: high|medium|low, basis: 非空字符串}")
    elif not _nonempty(confidence):
        report.error("E-CONF", where, "confidence 必须是 {level,basis} 或非空文字")

    outcome = entry.get("observed_outcome")
    executed: bool | None = None
    report.check()
    if isinstance(outcome, dict) and isinstance(outcome.get("executed"), bool):
        executed = outcome["executed"]
        if executed:
            details = [v for k, v in outcome.items() if k != "executed" and isinstance(v, str) and v.strip()]
            report.check()
            if not details:
                report.warn("E-OUTCOME", where, "executed=true 但 observed_outcome 没有记录实际结果内容")
    else:
        report.error("E-OUTCOME", where, "observed_outcome 必须是含布尔 executed 的对象")

    status = entry.get("status")
    evidence_list = entry.get("evidence") or []
    if status in ("single_observation", "repeatedly_supported"):
        report.check()
        if executed is not True:
            report.error(
                "E-STATUS-CTX", where,
                f"status={status} 要求 observed_outcome.executed=true（实际 {executed!r}）"
                "——未执行不得写成已验证经验，只能写 to_verify",
            )
        report.check()
        if not evidence_list:
            report.error("E-STATUS-CTX", where, f"status={status} 但 evidence 为空——没有证据不得入库为已验证")
    if executed is False and status not in (None, "to_verify"):
        report.check()
        report.error(
            "E-STATUS-CTX", where,
            f"executed=false 时 status 只能是 to_verify（实际 {status!r}）——不得把未执行的方法写成已观察/已验证",
        )

    if executed is False:
        haystack = " ".join(
            str(entry.get(key) or "")
            for key in ("conclusion", "recommended_action", "reasoning")
        )
        outcome_text = " ".join(str(v) for v in (outcome or {}).values()) if isinstance(outcome, dict) else ""
        report.check()
        hits = [term for term in RESULT_CLAIM_TERMS if term in haystack + " " + outcome_text]
        if hits:
            report.error(
                "E-CLAIM", where,
                f"executed=false 却写了结果性结论 {hits}——只能写待验证假设，不得虚构结果",
            )

    source_task_id = entry.get("source_task_id")
    report.check()
    if source_task_id not in ctx.task_ids:
        report.error("E-SOURCE", where, f"source_task_id {source_task_id!r} 不存在于 tasks.json（悬空引用）")

    for kind, ids in (
        ("E-XREF-SKILL", (entry.get("related_skill_ids") or [], ctx.skill_ids)),
        ("E-XREF-METHOD", (entry.get("related_method_ids") or [], ctx.method_ids)),
    ):
        values, known = ids
        report.check()
        if not isinstance(values, list):
            report.error(kind, where, f"{kind} 必须是数组")
            continue
        for value in values:
            report.check()
            if value not in known:
                report.error(kind, where, f"{value!r} 不存在于引用目标（悬空引用）")

    report.check()
    if not isinstance(entry.get("limitations"), list) or not isinstance(entry.get("counterexamples"), list):
        report.error("E-LIMITATIONS", where, "limitations 与 counterexamples 必须是数组")

    if status == "challenged_by_counterexample":
        report.check()
        if not entry.get("counterexamples"):
            report.error("E-COUNTEREXAMPLE", where, "status=challenged_by_counterexample 但 counterexamples 为空——必须记录具体反例")
    if status == "obsolete":
        report.check()
        if not entry.get("limitations"):
            report.warn("E-OBSOLETE-REASON", where, "status=obsolete 但 limitations 为空——建议写明失效原因")

    # 复核历史（schema 1.1 新登记）：复核必须留下可追溯记录
    review_history = entry.get("review_history")
    if review_history is not None:
        report.check()
        if not isinstance(review_history, list):
            report.error("E-REVIEW-HISTORY", f"{where}.review_history", "review_history 必须是数组")
            review_history = []
        for rindex, record in enumerate(review_history):
            rwe = f"{where}.review_history[{rindex}]"
            report.check()
            if (
                not isinstance(record, dict)
                or not store.is_iso8601(record.get("at"))
                or not _nonempty(record.get("note"))
                or record.get("to_status") not in ctx.enums.get("experience_status", [])
            ):
                report.error(
                    "E-REVIEW-HISTORY", rwe,
                    "复核记录必须含 {at: ISO8601, to_status: 枚举, note: 非空}",
                )
            if record.get("from_status") is not None:
                report.check()
                if record.get("from_status") not in ctx.enums.get("experience_status", []):
                    report.error("E-REVIEW-HISTORY", rwe, f"from_status={record.get('from_status')!r} 不在 experience_status 枚举内")

    # 反例处理依据（schema 1.1 新登记）：升级前处理反例必须留痕
    resolutions = entry.get("counterexample_resolutions")
    if resolutions is not None:
        report.check()
        if not isinstance(resolutions, list):
            report.error("E-COUNTEREXAMPLE-RES", f"{where}.counterexample_resolutions", "counterexample_resolutions 必须是数组")
            resolutions = []
        for xindex, record in enumerate(resolutions):
            xwe = f"{where}.counterexample_resolutions[{xindex}]"
            report.check()
            if (
                not isinstance(record, dict)
                or not store.is_iso8601(record.get("at"))
                or not _nonempty(record.get("resolution"))
            ):
                report.error(
                    "E-COUNTEREXAMPLE-RES", xwe,
                    "反例处理记录必须含 {at: ISO8601, resolution: 非空}",
                )
            if record.get("from_status") is not None:
                report.check()
                if record.get("from_status") not in ctx.enums.get("experience_status", []):
                    report.error("E-COUNTEREXAMPLE-RES", xwe, f"from_status={record.get('from_status')!r} 不在 experience_status 枚举内")

    report.check()
    if not store.is_iso8601(entry.get("created_at")):
        report.error("E-TIME", where, f"created_at 不是 ISO8601：{entry.get('created_at')!r}")
    report.check()
    if not _iso_or_null(entry.get("last_reviewed_at")):
        report.error("E-TIME", where, f"last_reviewed_at 不是 ISO8601 或 null：{entry.get('last_reviewed_at')!r}")
    if entry.get("review_after") is not None:
        report.check()
        if not store.is_iso8601(entry["review_after"]):
            report.error("E-TIME", where, f"review_after 不是 ISO8601：{entry['review_after']!r}")
        elif str(entry["review_after"])[:10] < today:
            report.check()
            report.warn(
                "E-STALE", where,
                f"review_after={entry['review_after']} 已过期（今天 {today}）——使用前应重新复核，检索时会显式排除",
            )


def check_experiences(ctx: Context, report: Report) -> int:
    experience_dir = ctx.state_dir / "experience"
    if not experience_dir.exists():
        report.note(
            f"经验库目录不存在（0 条）：{rel(experience_dir)}——"
            "store.load_experiences 对不存在的目录返回空列表，且 spec/03 §8「无新经验也是合法结果」，"
            "故按「0 条」处理而不判为缺失；这与 methods/index.json（单文件、缺失即缺域）不同"
        )
        return 0

    detector = load_privacy_detector(report)
    privacy_scanned = 0
    privacy_hits = 0
    paths = sorted(experience_dir.glob("*.json"))
    seen: dict[str, str] = {}
    for path in paths:
        data = _read_json(path, report)
        if data is _MISSING or data is _BROKEN:
            continue
        where = rel(path)
        check_experience(data, where, ctx, report, filename=path.name)
        if detector is not None:
            scanned, hit_count = check_experience_privacy(path, data, report, detector)
            privacy_scanned += scanned
            privacy_hits += hit_count
        experience_id = data.get("experience_id") if isinstance(data, dict) else None
        if experience_id:
            report.check()
            if experience_id in seen:
                report.error("E-ID-DUP", where, f"experience_id 重复：{experience_id}（已在 {seen[experience_id]} 出现）")
            else:
                seen[experience_id] = where
    if detector is not None:
        report.note(
            f"数据层隐私检测（只警告，不阻断）：扫描 {privacy_scanned} 条 privacy_scope=general 条目，"
            f"命中 {privacy_hits} 处；命中不等于机密，未命中也不等于可以安全泛化——该检测只覆盖"
            "「公司内部/未公开/保密」等标记、客户名称占位符、指标词+具体数值三类明显情形"
        )
    return len(paths)


# ---------------------------------------------------------------- 方法域

def check_methods(ctx: Context, report: Report) -> int:
    spec = ctx.schema.get("methods", {})
    required = list(spec.get("required_fields", []))
    path = methods_path(ctx.state_dir, ctx.schema)
    data = _read_json(path, report)

    if data is _MISSING:
        # 必需数据域缺失 → 明确报错并非零退出；禁止把「未执行」当作通过（schema.methods.file 是单文件，缺失即缺域）
        report.check()
        report.error(
            "M-FILE", rel(path),
            f"方法库文件不存在：{path}（schema.methods.file 要求该文件存在）。"
            "若要跳过本域，请显式只选择其他域（例如 --tasks --skills），此时结论不会显示「通过」。",
        )
        return 0
    if data is _BROKEN:
        return 0

    methods = _root_check(report, "M-ROOT", rel(path), data, "methods", ctx.enums)
    seen: dict[str, int] = {}

    for index, method in enumerate(methods):
        where = f"methods/index.json → methods[{index}]"
        if not isinstance(method, dict):
            report.check()
            report.error("M-REQ", where, "方法条目必须是 JSON 对象")
            continue

        for fieldname in required:
            report.check()
            if fieldname not in method:
                report.error("M-REQ", where, f"缺少必填字段：{fieldname}")
            elif not _nonempty(method[fieldname]):
                report.error("M-REQ", where, f"必填字段为空：{fieldname}")

        method_id = method.get("method_id")
        if _nonempty(method_id):
            report.check()
            if method_id in seen:
                report.error("M-ID-DUP", where, f"method_id 重复：{method_id}")
            else:
                seen[method_id] = index

        report.check()
        allowed = ctx.enums.get("method_verification", [])
        if method.get("verification_status") not in allowed:
            report.error("M-ENUM", where, f"verification_status={method.get('verification_status')!r} 不在枚举 {allowed} 内")

        for fieldname in ("applicable_task_types", "preconditions", "not_applicable_when", "steps", "checkpoints", "inputs", "outputs"):
            if fieldname in method:
                report.check()
                if not isinstance(method[fieldname], list):
                    report.error("M-ARRAY", where, f"{fieldname} 必须是数组")

        source = method.get("source")
        report.check()
        if not isinstance(source, dict):
            report.error("M-SOURCE", where, "source 必须是对象 {kind, citation, retrieved_at}")
        else:
            report.check()
            if source.get("kind") not in ("public_framework", "official_doc", "own_experience", "other"):
                report.error("M-SOURCE", where, f"source.kind={source.get('kind')!r} 不在枚举内")
            report.check()
            if not _nonempty(source.get("citation")):
                report.error("M-SOURCE", where, "source.citation 不能为空（公开框架必须给可核实来源）")
            report.check()
            if not store.is_iso8601(source.get("retrieved_at")):
                report.error("M-SOURCE", where, f"source.retrieved_at 不是 ISO8601：{source.get('retrieved_at')!r}")

        if method.get("verification_status") == "unverified":
            report.check()
            limitation_text = " ".join(
                str(x) for x in (method.get("limitations") or [])
            ) + " " + " ".join(str(x) for x in (method.get("not_applicable_when") or []))
            if not any(hint in limitation_text for hint in UNVERIFIED_HINTS) and not method.get("limitations"):
                report.error(
                    "M-UNVERIFIED", where,
                    "verification_status=unverified 但没有任何「未验证范围」说明"
                    "（需要 limitations，或在 not_applicable_when 中写明未验证）",
                )

    root = project_root_for(ctx.state_dir)
    check_selection_rules(root, ctx.method_ids, report)
    check_index_md_drift(root, ctx.method_ids, report, ctx.renderer)
    return len(methods)


# ---------------------------------------------------------------- 隐私检测（t12，数据层）

def load_privacy_detector(report: Report):
    """复用 exp.py 的 privacy_hits（**不复制**检测逻辑，避免两份实现漂移）。

    exp.py 顶层 `import validate`，因此这里必须惰性导入：否则 validate→exp→validate 的循环在
    「先导入 validate」的入口（如直接运行本脚本）下会拿到半初始化的模块。
    加载失败时**不静默**：记为「未执行」，从而不让 `--all` 宣称通过。
    """
    try:
        import exp as exp_module  # noqa: PLC0415 —— 惰性导入是有意为之（打破循环依赖）
    except Exception as exc:  # pragma: no cover - 仅在 exp.py 缺失/损坏时触发
        report.check()
        report.skip_check(f"数据层隐私检测（无法加载检测器 exp.privacy_hits：{exc}）")
        return None
    detector = getattr(exp_module, "privacy_hits", None)
    if not callable(detector):
        report.check()
        report.skip_check("数据层隐私检测（exp.py 中没有 privacy_hits 函数，检测器不可用）")
        return None
    return detector


def check_experience_privacy(path: Path, entry: dict, report: Report, detector) -> tuple[int, int]:
    """对 privacy_scope=general 的条目做机密特征检测：**命中只报警告，绝不阻断**。

    返回 (已扫描的 general 条目数, 命中处数)。命中 ≠ 违规：这是给人看的处置信号。
    """
    if not isinstance(entry, dict) or entry.get("privacy_scope") != "general":
        return (0, 0)
    report.check()  # 每条 general 条目都记一次检查，避免「扫描数」藏在说明里而检查数为 0
    experience_id = entry.get("experience_id") or path.stem
    hits = detector(entry) or []
    for rule, where in hits:
        report.check()
        report.warn(
            "E-PRIVACY-GENERAL", f"{rel(path)} → {experience_id}",
            f"命中 {rule}：{where}（命中不等于机密，也不阻断保存；请人工确认后处理或写明理由接受）",
        )
    return (1, len(hits))


# ---------------------------------------------------------------- 方法域派生文件（t11）

INDEX_TIME_PATTERN = re.compile(r"生成时间")
SOURCE_SHA_PATTERN = re.compile(r"生成来源 SHA256[^0-9a-f]*([0-9a-f]{64})")
BASIS_METHOD_REF = re.compile(r"^methods/index\.json\s*→\s*([A-Za-z0-9_\-]+)\.")
METHOD_ID_LINE = re.compile(r"`method_id`[^`]*`([A-Za-z0-9_\-]+)`")


def check_selection_rules(root: Path, method_ids: set, report: Report) -> int:
    """校验 methods/selection_rules.json 的**全部**方法引用（F1：禁止前缀过滤）。"""
    path = root / "methods" / "selection_rules.json"
    if not path.exists():
        if root == store.PROJECT_ROOT:
            report.check()
            report.error(
                "M-SELECTION-FILE", rel(path),
                f"方法选择规则文件不存在：{path}——缺它就没有任何引用可校验（历史上正是缺这类检查才会出现「空真」）",
            )
        else:
            report.skip_check(f"selection_rules 引用校验（样本树未提供 {rel(path)}）")
        return 0

    data = _read_json(path, report)
    if data is _BROKEN:
        return 0
    report.check()
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        report.error("M-SELECTION-ROOT", rel(path), "根结构必须是含 rules 数组的对象")
        return 0

    refs: list[tuple[str, str]] = []          # (位置, 值)
    structural = 0
    for index, rule in enumerate(data["rules"]):
        where = f"selection_rules.json → rules[{index}]"
        rule_id = rule.get("rule_id") if isinstance(rule, dict) else None
        if not isinstance(rule, dict):
            report.check()
            report.error("M-SELECTION-ROOT", where, "rule 必须是对象")
            structural += 1
            continue
        for key in ("recommend", "avoid"):
            if key not in rule:
                continue
            values = rule.get(key)
            if not isinstance(values, list):
                report.check()
                report.error("M-SELECTION-ROOT", f"{where}.{key}", f"{key} 必须是数组")
                structural += 1
                continue
            for position, value in enumerate(values):
                if not isinstance(value, str):
                    report.check()
                    report.error(
                        "M-SELECTION-ROOT", f"{where}.{key}[{position}]",
                        f"引用必须是字符串（当前 {type(value).__name__}）——非字符串会被成员校验静默跳过",
                    )
                    structural += 1
                    continue
                refs.append((f"{rule_id or index}.{key}[{position}]", value))

    for index, combination in enumerate(data.get("combination_rules") or []):
        if not isinstance(combination, dict):
            continue
        for position, value in enumerate(combination.get("sequence") or []):
            if isinstance(value, str):
                refs.append((f"combination_rules[{index}].sequence[{position}]", value))

    # F1 的关键护栏：引用数为 0 时，成员校验必然「通过」但什么都没查
    report.check()
    if not refs:
        report.error(
            "M-SELECTION-EMPTY", rel(path),
            "recommend/avoid/sequence 的引用总数为 0——成员校验将退化为空真（恒真），按失败处理",
        )
        return 0

    dangling = []
    for where, value in refs:
        report.check()
        # 全量成员检查：精确相等，不做任何前缀过滤、不做大小写折叠
        if value not in method_ids:
            dangling.append((where, value))
            report.error(
                "M-SELECTION-REF", f"{rel(path)} → {where}",
                f"引用 {value!r} 不在 methods/index.json 的 method_id 集合中（悬空引用）",
            )

    basis_checked = 0
    for index, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict):
            continue
        for position, ref in enumerate(rule.get("basis_refs") or []):
            if not isinstance(ref, str):
                continue
            match = BASIS_METHOD_REF.match(ref)
            if not match:
                continue
            basis_checked += 1
            method_id = match.group(1)
            report.check()
            if method_id not in method_ids:
                report.error(
                    "M-SELECTION-BASIS-REF", f"{rel(path)} → rules[{index}].basis_refs[{position}]",
                    f"依据里引用的 method_id {method_id!r} 不存在（悬空引用）",
                )

    report.note(
        f"selection_rules：已对 {len(refs)} 条引用做**全量字符串成员检查**（无前缀过滤，规则 {len(data['rules'])} 条）；"
        f"另有 {basis_checked} 条 basis_refs 方法引用经解析后校验"
        + (f"；悬空 {len(dangling)} 条" if dangling else "")
    )
    report.check(structural)
    return len(refs)


def _run_renderer(renderer: Path, root: Path, report: Report) -> str | None:
    """在临时副本里调用生成器重渲染；返回新生成的 index.md **文本**（失败返回 None）。

    本函数**不实现**任何渲染逻辑：只负责复制输入、调用生成器、读回它的产物，
    因此生成器格式变化时校验器无需跟着改。
    """
    import shutil
    import subprocess
    import tempfile

    methods_dir = root / "methods"
    temp_root = Path(tempfile.mkdtemp(prefix="tn-render-"))
    try:
        temp_methods = temp_root / "methods"
        temp_methods.mkdir(parents=True)
        shutil.copy2(methods_dir / "index.json", temp_methods / "index.json")
        if (methods_dir / "index.md").exists():
            shutil.copy2(methods_dir / "index.md", temp_methods / "index.md")
        local_renderer = temp_methods / renderer.name
        shutil.copy2(renderer, local_renderer)
        try:
            result = subprocess.run(
                [sys.executable, str(Path("methods") / renderer.name)],
                cwd=str(temp_root), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except subprocess.TimeoutExpired:
            report.check()
            report.error("M-INDEX-RENDER", rel(renderer), "生成器执行超时（120 秒），无法完成漂移比对")
            return None
        if result.returncode != 0:
            report.check()
            tail = " | ".join((result.stderr or result.stdout or "").strip().splitlines()[-3:])
            report.error(
                "M-INDEX-RENDER", rel(renderer),
                f"生成器退出码 {result.returncode}，重渲染失败：{tail or '（无输出）'}",
            )
            return None
        produced = temp_methods / "index.md"
        if not produced.exists():
            report.check()
            report.error(
                "M-INDEX-RENDER", rel(renderer),
                "生成器运行成功但没有产出 methods/index.md，无法比对（生成器与预期路径不一致）",
            )
            return None
        return produced.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def check_index_md_drift(root: Path, method_ids: set, report: Report, renderer: Path | None) -> int:
    """methods/index.md 漂移检查：来源哈希 + id 覆盖 + （有生成器时）重渲染逐行比对。"""
    methods_dir = root / "methods"
    index_md = methods_dir / "index.md"
    index_json = methods_dir / "index.json"
    if not index_md.exists():
        if root == store.PROJECT_ROOT:
            report.check()
            report.error("M-INDEX-FILE", rel(index_md), f"派生索引不存在：{index_md}")
        else:
            report.skip_check(f"index.md 漂移检查（样本树未提供 {rel(index_md)}）")
        return 0

    text = index_md.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ① 来源哈希：index.md 记录的快照哈希 vs 当前 index.json
    if index_json.exists():
        actual_sha = store.sha256_file(index_json)
        recorded = SOURCE_SHA_PATTERN.search(text)
        report.check()
        if not recorded:
            report.error("M-INDEX-HASH", rel(index_md), "文件头没有「生成来源 SHA256」，无法判断派生索引是否对应当前权威数据")
        elif recorded.group(1) != actual_sha:
            line_no = next((i + 1 for i, line in enumerate(lines) if "生成来源 SHA256" in line), 0)
            report.error(
                "M-INDEX-HASH", f"{rel(index_md)}:{line_no}",
                f"记录的来源哈希 {recorded.group(1)[:12]}… 与当前 methods/index.json 的 {actual_sha[:12]}… 不一致"
                "——派生索引已落后于权威数据，需重渲染",
            )

        # ② id 覆盖：JSON 里的每个 method_id 都必须出现在 index.md
        for method_id in sorted(method_ids):
            report.check()
            if method_id not in text:
                report.error("M-INDEX-COVERAGE", rel(index_md), f"method_id {method_id!r} 在派生索引里找不到（条目缺失）")
        # ③ 反向：index.md 里出现的 method_id 是否都在 JSON 中
        found = set(METHOD_ID_LINE.findall(text))
        for method_id in sorted(found - method_ids):
            report.check()
            report.warn("M-INDEX-EXTRA", rel(index_md), f"派生索引里的 method_id {method_id!r} 不在 methods/index.json 中（多余条目）")

    # ④ 重渲染比对（只调用生成器，不实现渲染逻辑）
    resolved = renderer or (methods_dir / "methods-renderer.py")
    if not Path(resolved).exists():
        report.check()
        report.warn(
            "M-INDEX-RENDER", str(resolved),
            f"找不到生成器 {resolved}，无法执行「重渲染逐行比对」；"
            "已退化为来源哈希 + id 覆盖两项弱检查（它们发现不了「只改 index.md 文本」的手工编辑）",
        )
        report.skip_check(f"index.md 重渲染比对（生成器缺失：{resolved}）")
        return 0

    rendered_text = _run_renderer(Path(resolved), root, report)
    if rendered_text is None:
        return 0

    produced_lines = rendered_text.splitlines()
    if len(produced_lines) != len(lines):
        report.check()
        report.error(
            "M-INDEX-DRIFT", rel(index_md),
            f"重渲染行数 {len(produced_lines)} 与现有文件 {len(lines)} 不一致——派生索引已漂移",
        )
    diffs = []
    for number in range(max(len(lines), len(produced_lines))):
        current = lines[number] if number < len(lines) else "<缺行>"
        expected = produced_lines[number] if number < len(produced_lines) else "<缺行>"
        if current == expected:
            continue
        if INDEX_TIME_PATTERN.search(current) or INDEX_TIME_PATTERN.search(expected):
            continue  # 忽略「生成时间（UTC）」行
        diffs.append((number + 1, expected, current))
    report.check()
    if diffs:
        detail = "；".join(
            f"第 {number} 行 期望 {expected[:60]!r} 实际 {current[:60]!r}" for number, expected, current in diffs[:5]
        )
        report.error(
            "M-INDEX-DRIFT", f"{rel(index_md)}（共 {len(diffs)} 处差异，显示前 {min(5, len(diffs))} 处）",
            detail,
        )
    else:
        report.note(f"index.md 漂移检查：调用 {rel(Path(resolved))} 重渲染后逐行一致（已忽略「生成时间（UTC）」行）")
    return 0


# ---------------------------------------------------------------- 备份校验

def check_backup(backup: Path | None, schema: dict, report: Report) -> bool:
    try:
        result = store.verify_backup(Path(backup) if backup else None)
    except store.StoreError as exc:
        report.check()
        report.error("B-MANIFEST", rel(backup) if backup else "state/backups", str(exc))
        return False

    print(f"备份目录    : {result['backup']}")
    print(f"已校验文件  : {result['checked_files']} 个")
    for problem in result["problems"]:
        report.check()
        if "哈希不符" in problem:
            rule = "B-HASH"
        elif "记录数不符" in problem:
            rule = "B-RECORDS"
        elif "缺失" in problem:
            rule = "B-MISSING"
        else:
            rule = "B-MANIFEST"
        report.error(rule, rel(Path(result["backup"])), problem)

    manifest_path = Path(result["backup"]) / "manifest.json"
    manifest = store.read_json(manifest_path, default=None) or {}
    report.check()
    if manifest.get("schema_version") not in (None, schema.get("schema_version")):
        report.warn(
            "B-SCHEMA", rel(manifest_path),
            f"备份 schema_version={manifest.get('schema_version')!r} 与当前 {schema.get('schema_version')!r} 不一致",
        )
    if result["ok"]:
        print(f"结论        : 通过（{result['checked_files']} 个文件的 sha256 与记录数均一致）")
    else:
        print(f"结论        : 失败（{len(result['problems'])} 个问题）")
    return result["ok"]


# ---------------------------------------------------------------- 主流程

def backup_targets(all_backups: bool, backup: Path | None) -> list[Path | None]:
    if all_backups:
        if not store.BACKUP_DIR.exists():
            raise store.StoreError("没有任何备份可供校验。")
        targets: list[Path | None] = sorted(p for p in store.BACKUP_DIR.iterdir() if p.is_dir())
        if not targets:
            raise store.StoreError("没有任何备份可供校验。")
        return targets
    return [Path(backup) if backup else None]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="任务导航 数据校验器（依据 state/schema.json）")
    parser.add_argument("--all", action="store_true", help="校验全部域（默认）")
    parser.add_argument("--lessons", action="store_true", help="只校验流程类教训 state/lessons/")
    parser.add_argument("--tasks", action="store_true", help="校验任务状态域")
    parser.add_argument("--skills", action="store_true", help="校验个人技能档案域")
    parser.add_argument("--experience", action="store_true", help="校验领域经验库域")
    parser.add_argument("--methods", action="store_true", help="校验 AI 方法库域")
    parser.add_argument("--state-dir", type=Path, help="要校验的 state 目录（默认 state/；反例样本用）")
    parser.add_argument("--backup-verify", action="store_true", help="校验备份的 sha256 与记录数")
    parser.add_argument("--backup", type=Path, help="指定的备份目录（默认最新一个）")
    parser.add_argument("--all-backups", action="store_true", help="逐个校验 state/backups/ 下的全部备份")
    parser.add_argument("--list-rules", action="store_true", help="打印规则清单后退出")
    parser.add_argument("--renderer", type=Path,
                        help="methods/index.md 生成器路径（默认 <项目根>/methods/methods-renderer.py，用于重渲染漂移比对）")
    return parser.parse_args(argv[1:])


DOMAIN_LABELS = {
    "tasks": "任务 tasks.json",
    "skills": "技能 user_skills.json",
    "experience": "经验 experience/*.json",
    "methods": "方法 methods/index.json",
    "lessons": "流程教训 lessons/*.json",
}



def check_lessons(ctx: Context, report: Report) -> int:
    """校验流程类教训：lesson_type 必须在六类内（SKILL.md §J）。"""
    spec = ctx.schema.get("lessons") or {}
    allowed = spec.get("lesson_type_enum") or (ctx.schema.get("enums") or {}).get("lesson_type") or []
    directory = ctx.state_dir / "lessons"
    if not directory.is_dir():
        return 0
    count = 0
    for path in sorted(directory.glob("*.json")):
        data = _read_json(path, report)
        if data is _MISSING or data is _BROKEN:
            continue
        count += 1
        where = rel(path)
        report.check()
        lt = data.get("lesson_type")
        if not lt:
            report.error("L-TYPE", where, "缺少 lesson_type——教训必须归入六类之一（SKILL.md §J）")
        elif allowed and lt not in allowed:
            report.error("L-TYPE", where, f"lesson_type={lt!r} 不在枚举 {allowed} 内")
        report.check()
        if not _nonempty(data.get("conclusion")):
            report.error("L-SHAPE", where, "缺少 conclusion（这条教训的结论是什么）")
        report.check()
        if not data.get("trigger_conditions"):
            report.error("L-SHAPE", where, "缺少 trigger_conditions（什么情况下适用）")
        report.check()
        if not data.get("evidence"):
            report.error("L-SHAPE", where, "缺少 evidence（依据是什么）")
    return count

def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.list_rules:
        for rule in rule_ids():
            print(f"{rule:<20}{RULES[rule]}")
        print(f"\n共 {len(RULES)} 条规则。")
        return 0

    state_dir = (args.state_dir or store.STATE_DIR).resolve()
    report = Report()

    print("=== 任务导航 数据校验 ===")
    print(f"数据目录    : {state_dir}")
    schema = load_schema(state_dir, report)
    ctx = load_context(state_dir, schema, report, renderer=args.renderer)

    ALL_DOMAINS = ["tasks", "skills", "experience", "lessons", "methods"]
    explicit_flags = any((args.tasks, args.skills, args.experience, args.lessons, args.methods))
    selected = [d for d, flag in (
        ("tasks", args.tasks), ("skills", args.skills),
        ("experience", args.experience), ("lessons", args.lessons),
        ("methods", args.methods),
    ) if flag]
    if args.all or (not selected and not args.backup_verify):
        selected = list(ALL_DOMAINS)
    if not selected and args.backup_verify and not explicit_flags:
        selected = []  # --backup-verify 单独使用：只校验备份，不做域校验

    skipped = [d for d in ALL_DOMAINS if d not in selected]
    backup_only = args.backup_verify and not selected

    print(f"选择域      : {', '.join(selected) if selected else '（无，仅备份校验）'}")
    if skipped and not backup_only:
        print(
            f"未选择域    : {', '.join(skipped)}（本次显式未选择 → 记为「未执行」，不计入通过；"
            "如需完整结论请用 --all）"
        )
    for note in report.notes:
        print(f"  · {note}")
    report.notes.clear()

    stats: list[dict] = []

    def run(name: str, func, *fargs) -> None:
        before_err, before_warn, before_checks = len(report.errors), len(report.warnings), report.checks
        records = func(*fargs)
        stats.append({
            "name": name,
            "records": records,
            "checks": report.checks - before_checks,
            "errors": len(report.errors) - before_err,
            "warnings": len(report.warnings) - before_warn,
        })

    for domain in skipped:
        if not backup_only:
            stats.append({"name": f"{DOMAIN_LABELS[domain]}", "records": None, "checks": 0, "errors": 0, "warnings": 0})

    if "tasks" in selected:
        run("任务 tasks.json", check_tasks, ctx, report)
    if "skills" in selected:
        run("技能 user_skills.json", check_skills, ctx, report)
    if "experience" in selected:
        run("经验 experience/*.json", check_experiences, ctx, report)
    if "lessons" in selected:
        run("流程教训 lessons/*.json", check_lessons, ctx, report)

    # 派生文件一致性：经验索引是否已过期（只警告，不阻断）
    if "experience" in selected or "lessons" in selected:
        import subprocess as _sp
        idx = ctx.state_dir / "experience_index.md"
        script = Path(__file__).resolve().parent / "build_index.py"
        if idx.is_file() and script.is_file():
            report.check()
            r = _sp.run(
                [sys.executable, str(script), "--check"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                report.warn("E-INDEX-STALE", "state/experience_index.md",
                            "索引与经验/教训数据不一致——跑 python3 scripts/build_index.py 重建")
    if "methods" in selected:
        run("方法 methods/index.json", check_methods, ctx, report)

    print()
    print("── 校验明细 ───────────────────────────────────────────────")
    for item in stats:
        if item["records"] is None:
            records, verdict = "未执行（本次未选择该域）", "未执行"
        else:
            records = f"{item['records']} 条"
            verdict = "通过" if item["errors"] == 0 else "失败"
        print(
            f"{item['name']:<26} 记录 {records:<20} 检查 {item['checks']:>4} 项  "
            f"错误 {item['errors']}  警告 {item['warnings']}  → {verdict}"
        )

    backup_ok: bool | None = None
    if args.backup_verify:
        print()
        print("── 备份校验 ───────────────────────────────────────────────")
        before_err, before_warn, before_checks = len(report.errors), len(report.warnings), report.checks
        targets = backup_targets(args.all_backups, args.backup)
        backups_ok = []
        for index, target in enumerate(targets, start=1):
            if len(targets) > 1:
                print(f"── 备份 {index}/{len(targets)} ──")
            backups_ok.append(check_backup(target, schema, report))
        backup_ok = all(backups_ok)
        stats.append({
            "name": f"备份 manifest（sha256/记录数，{len(targets)} 个）",
            "records": 0,
            "checks": report.checks - before_checks,
            "errors": len(report.errors) - before_err,
            "warnings": len(report.warnings) - before_warn,
        })

    print()
    print("── 错误与警告 ─────────────────────────────────────────────")
    if not report.errors and not report.warnings:
        print("（无）")
    for item in report.errors:
        print(f"[错误] [{item['rule']}] {item['where']} → {item['message']}")
    for item in report.warnings:
        print(f"[警告] [{item['rule']}] {item['where']} → {item['message']}")
    # 校验过程中产生的说明（含「某项检查实际检查了多少条引用」这类反空真证据）
    for note in report.notes:
        print(f"[说明] {note}")

    print()
    print("── 汇总 ───────────────────────────────────────────────────")
    print(f"规则检查总数 : {report.checks} 项")
    print(f"错误         : {len(report.errors)} 项")
    print(f"警告         : {len(report.warnings)} 项")
    not_run = [item["name"] for item in stats if item["records"] is None]
    if not_run:
        print(f"未执行       : {', '.join(not_run)}（本次显式未选择该域，未做任何判定，也不计入通过）")
    for item in report.not_run:
        print(f"未执行       : {item}（未做判定，也不计入通过）")
    if report.errors:
        conclusion = "失败"
    elif report.not_run:
        conclusion = "部分校验（存在未执行项，不宣称整体通过）"
    elif not_run:
        conclusion = "部分校验（存在未执行域，不宣称整体通过）"
    elif backup_only:
        conclusion = "通过（仅备份校验，未做域校验）"
    else:
        conclusion = "通过"
    print(f"结论         : {conclusion}")
    if not args.backup_verify:
        print("提示         : 备份完整性未在本命令中校验，请单独运行 --backup-verify")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(2)