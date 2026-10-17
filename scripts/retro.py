#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retro.py —— 复盘流程。把 spec/00 阶段1 第9、10 条从「文档里写了」变成「必须走一遍」。

对应要求：
  · spec/00 阶段1-9  结果验收与复盘
  · spec/00 阶段1-10 在复盘后，经过筛选地更新领域经验库**和个人技能档案**
  · spec/03 §8       复盘与经验提炼规则（只回答实用问题）
  · spec/03 §4       技能状态更新规则（有证据才升级）

为什么需要它：审计发现 retrospective_status 分布为 not_reviewed:4 / pending_triage:3，
**达到 reviewed 的 0 个**；技能档案 8 条证据的 task_id 全部为 None——**复盘从未闭环**。
根因：规格写了要复盘，但没有任何工具或检查点触发它。

用法：
    python3 scripts/retro.py status                    # 看哪些任务待复盘
    python3 scripts/retro.py ask    --task <id>        # 打印五个必答问题
    python3 scripts/retro.py close  --task <id> --file <answers.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

# spec/03 §8 的五个实用问题——只问这些，不搞形式
QUESTIONS = [
    ("goal_vs_result", "原目标与完成标准是什么？实际结果如何？"),
    ("what_helped", "哪些计划步骤实际有帮助？哪些是浪费？"),
    ("surprises", "发生了什么意外？根因是什么（事实与推测分开写）？"),
    ("skills", "哪些技能确实得到验证（有独立操作证据）？哪些仍有缺口？"),
    ("experience", "是否有值得未来复用的经验？适用条件和反例是什么？"),
    # 第六问由用户追问促成：SKILL.md §J 要求按六类整理教训，
    # 但复盘只问「这个任务怎么样」，从不问「用户这次的纠正属于哪类」——
    # 结果是用户教的东西只进 decisions.md 流水账，进不了可检索的教训库。
    ("user_corrections", "本次用户提出了哪些纠正？每条各属于哪一类"
                         "（有效做法/无效做法/失败原因/方法适用条件/技能差距/流程改进）？"),
]

# 技能状态的可选值（与 schema.enums.skill_status 一致）
SKILL_STATUSES = [
    "not_assessed", "can_independently", "can_with_checklist",
    "needs_step_by_step", "not_yet", "needs_review",
]

# 只有这两类证据支持「可独立完成」（spec/03 §4 门禁）
INDEPENDENT_EVIDENCE = {"independent_operation", "observed_test"}

# SKILL.md §J 的六类
LESSON_TYPES = ["有效做法", "无效做法", "失败原因", "方法适用条件", "技能差距", "流程改进"]


def die(msg: str) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(2)


def cmd_status() -> int:
    tasks = store.load_tasks()["tasks"]
    todo = [t for t in tasks if t.get("retrospective_status") in ("not_reviewed", "pending_triage")
            and t["status"] in ("completed", "awaiting_acceptance", "cancelled")]
    pending = [t for t in tasks if t.get("retrospective_status") == "pending_triage"]
    reviewed = [t for t in tasks if t.get("retrospective_status") == "reviewed"]

    print("═══ 复盘状态 ═══")
    print(f"  已完成待复盘：{len(todo)} 个")
    for t in todo:
        mark = "待筛选" if t.get("retrospective_status") == "pending_triage" else "未复盘"
        print(f"     · {t['task_id']}  [{mark}]  {t['title'][:38]}")
    print(f"  已复盘：{len(reviewed)} 个")
    for t in reviewed:
        print(f"     · {t['task_id']}  {t['title'][:38]}")
    if pending:
        print()
        print(f"  ⚠️ 有 {len(pending)} 个任务处于「待筛选」——按 spec/03 §8，复盘要落到实处才算闭环")
    return 0


def cmd_ask(task_id: str) -> int:
    tasks = store.load_tasks()["tasks"]
    task = store.find_task(tasks, task_id)
    print(f"═══ 复盘：{task_id}《{task['title']}》═══")
    print(f"  验收结论：{task.get('verdict', '（尚未验收）')}")
    print()
    print("五个问题（spec/03 §8，只问实用的）：")
    for i, (key, q) in enumerate(QUESTIONS, start=1):
        print(f"  {i}. [{key}] {q}")
    print()
    print("§J 六类（用户纠正必须归类，不能只写进 decisions.md 流水账）：")
    for t in ("有效做法", "无效做法", "失败原因", "方法适用条件", "技能差距", "流程改进"):
        print(f"     · {t}")
    print()
    print("三类决定（留空表示「无」，不要编）：")
    print("  · experiences[]：要新增的经验（无新经验是合法结果）")
    print("  · skills[]：要更新的技能（有独立操作证据才能升级到 can_independently）")
    print("  · methods_used[]：本次用了哪条方法（spec/03 §7-6 要求可追溯）")
    print()
    print("答案写成 JSON 后用 close 提交。模板：")
    print(json.dumps({
        "answers": {k: "……" for k, _ in QUESTIONS},
        "experiences": [],
        "skills": [],
        "methods_used": [],
        "no_new_experience_reason": "（若不新增经验，写明理由）",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_capture(task_id: str, lesson_type: str, title: str, conclusion: str,
                evidence: str) -> int:
    """任务**进行中**捕获一条教训，不必等任务完成。

    为什么需要它（2026-10-15 核查用户的工作流时发现）：
    用户设计的流程是「项目完成之后 / **修改意见提出之后**，修改相关经验」——
    而 retro.py 只在 status ∈ (completed/awaiting_acceptance/cancelled) 时能跑。
    **实测：本会话 23 条教训几乎全部来自用户中途纠正，不是任务完成后的复盘。**
    也就是说，最重要的学习来源走的是流程里没有的那条路。
    本命令补上这条路径。
    """
    if lesson_type not in LESSON_TYPES:
        die(f"lesson_type={lesson_type!r} 不在六类内：{LESSON_TYPES}")
    for k, v in (("title", title), ("conclusion", conclusion), ("evidence", evidence)):
        if not str(v).strip():
            die(f"capture 需要 {k} 非空——教训必须写清「是什么/结论/依据」")

    lessons_dir = getattr(store, "LESSONS_DIR", store.STATE_DIR / "lessons")
    lessons_dir.mkdir(parents=True, exist_ok=True)
    # 编号规则：**按天计数**，与 lessons 落盘路径（retro close）保持一致。
    # 修 bug（2026-10-16）：此前用「全部教训数 + 1」作序号，于是今天第一条教训
    # 落成 L-20261016-025（续接昨天的 024）——而项目其余路径都是按天从 001 起算。
    # 后果是 ID 语义混乱：L-20261015-024 之后直接跳到 L-20261016-025，
    # 看不出「这是今天的第几条」。同型问题此前出现过：判据/编号各写一套。
    today = store.now_iso()[:10].replace("-", "")
    prefix = f"L-{today}-"
    used = []
    for f in lessons_dir.glob(f"{prefix}*.json"):
        try:
            used.append(int(f.stem.rsplit("-", 1)[1]))
        except ValueError:
            continue
    lid = f"{prefix}{max(used) + 1 if used else 1:03d}"

    store.write_json(lessons_dir / f"{lid}.json", {
        "experience_id": lid,
        "lesson_type": lesson_type,
        "title": title,
        "conclusion": conclusion,
        "recommended_action": conclusion,
        "trigger_conditions": ["见 evidence 描述的场景"],
        "limitations": [],
        "counterexamples": [],
        "evidence": [evidence],
        "scope": "cross_task",
        "domain": "process",
        "source": f"任务 {task_id} 进行中捕获（用户纠正或自查发现）",
        "status": "single_observation",
        "confidence": {"level": "medium", "basis": "来自一次真实交互"},
        "privacy_scope": "general",
        "created_at": store.now_iso(),
        "last_reviewed_at": None,
    })
    print(f"  ✅ 已捕获教训 {lid}（{lesson_type}）")
    print(f"     {title}")
    print(f"     来源任务：{task_id}")
    # 重建索引，让经验库可读索引同步
    try:
        import subprocess as _sp
        _sp.run([sys.executable, str(Path(__file__).resolve().parent / "build_index.py")],
                capture_output=True, timeout=30)
    except Exception:
        pass
    return 0


def cmd_close(task_id: str, answers_path: Path) -> int:
    if not answers_path.exists():
        die(f"答案文件不存在：{answers_path}")
    try:
        payload = json.loads(answers_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(
            f"答案文件不是合法 JSON：{answers_path}（第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}）。"
            "常见原因：多余的逗号、中文引号、注释。请修正后重跑。"
        )

    answers = payload.get("answers") or {}
    missing = [k for k, _ in QUESTIONS if not str(answers.get(k, "")).strip()]
    if missing:
        die(f"有 {len(missing)} 个问题没回答：{', '.join(missing)}。"
            "复盘必须逐条回答——答不出就写「无」，但不能空着。")

    data = store.load_tasks()
    task = store.find_task(data["tasks"], task_id)

    skills_data = store.load_skills()
    messages: list[str] = []

    # ── 技能更新（spec/03 §4 门禁：只有独立操作证据才能升级） ──
    for upd in payload.get("skills") or []:
        sid = upd.get("skill_id")
        new_status = upd.get("status")
        if new_status not in SKILL_STATUSES:
            die(f"技能状态非法：{new_status}（可选：{SKILL_STATUSES}）")
        entry = next((s for s in skills_data["skills"] if s["skill_id"] == sid), None)

        if entry is None:
            # spec/03 §4：允许在复盘后新增技能条目
            entry = {
                "skill_id": store.next_skill_id(skills_data["skills"]),
                "skill_name": upd.get("skill_name") or die("新增技能必须给 skill_name"),
                "scope": upd.get("scope", "（复盘新增，范围待补充）"),
                "status": new_status,
                "evidence": [],
                "confidence": {"level": upd.get("confidence_level", "low"),
                               "basis": upd.get("confidence_basis", "来自任务复盘的观察")},
                "last_verified_at": store.now_iso() if new_status == "can_independently" else None,
                "known_gaps": upd.get("known_gaps", []),
                "preferred_learning_mode": upd.get("preferred_learning_mode", "未评估"),
                "related_tasks": [task_id],
                "privacy_scope": upd.get("privacy_scope", "personal"),
                "notes": f"由任务 {task_id} 的复盘新增",
            }
            skills_data["skills"].append(entry)
            messages.append(f"新增技能档案条目 {entry['skill_id']}《{entry['skill_name']}》状态 {new_status}")
        else:
            if new_status == "can_independently":
                has_independent = any(e.get("kind") in INDEPENDENT_EVIDENCE
                                      for e in entry.get("evidence", []))
                if not has_independent and not upd.get("evidence_kind") in INDEPENDENT_EVIDENCE:
                    die(f"拒绝把 {sid} 升级为「可独立完成」：档案里没有独立操作证据，"
                        "本次也没提供。spec/03 §4 规定「在指导下完成一次」不构成升级依据。")
            entry["status"] = new_status
            if task_id not in entry.setdefault("related_tasks", []):
                entry["related_tasks"].append(task_id)
            messages.append(f"更新技能 {sid} 状态为 {new_status}")

        # 记录证据（含来源任务——这正是审计指出的缺口：task_id 全为 None）
        entry.setdefault("evidence", []).append({
            "kind": upd.get("evidence_kind", "guided_practice"),
            "description": upd.get("evidence", f"来自任务 {task_id} 的复盘观察"),
            "task_id": task_id,
            "at": store.now_iso(),
        })

    # ── 经验条目（复用 exp.py 的门禁） ──
    for exp in payload.get("experiences") or []:
        exp.setdefault("source_task_id", task_id)
        # ── 修复（2026-10-16）：此前直接 store.write_json + 'TEMP' 兜底 ──
        # 症状：复盘写入的经验落成 state/experience/TEMP.json、experience_id=None，
        #       校验器随即报 21 个错误、整体结论「失败」。
        # 根因：绕过了 store.save_experience()——那才是会校验 ID 的入口
        #       （缺 experience_id 直接 raise StoreError），
        #       而 'TEMP' 兜底把「我忘了给 ID」变成了静默写坏一个文件。
        # 与已修的其它同类问题一致：**绕过校验器的静默路径 = 假护栏**。
        if not exp.get("experience_id"):
            exp["experience_id"] = store.next_experience_id(store.load_experiences())
        # ── 规则门禁（2026-10-16 补）：走 exp.py 的写入门禁，复用 validate.py 的单条经验规则 ──
        # 为什么必须在这里拦（实测事故）：
        #   store.save_experience() 只检查 experience_id 是否存在，**不查 schema**。
        #   于是我手写的一条经验缺 9 个必填字段、domain 也不在枚举内，照样写进了正式库，
        #   校验器随即报 15 个错误、整体结论「失败」。
        #   exp.py 头部早已写明要求：「写入门禁复用校验器规则……exp.py 与 validate.py
        #   不会出现两套判断标准」——但 retro.py 这条路径绕过了它。
        #   **绕过校验器的写入路径 = 假护栏**（与已修的 TEMP 文件名、静默 except 同类）。
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import exp as exp_tool  # noqa: PLC0415
        report, ctx = exp_tool.build_report_and_context(store.STATE_DIR)
        exp_tool.validator.check_experience(
            exp, "待写入条目", ctx, report, filename=f"{exp['experience_id']}.json")
        if report.errors:
            # report.errors 是 list[dict]（键为 rule / where / message），不是对象——
            # 我第一版写成 e.code / e.message，直接 AttributeError 崩在门禁自己身上。
            detail = "；".join(
                f"[{e['rule']}] {e['message']}" for e in report.errors[:6])
            die(f"经验 {exp['experience_id']} 未通过校验规则"
                f"（共 {len(report.errors)} 条错误）：{detail}"
                "——拒绝写入。请补齐字段后重试（结构参照 state/experience/ 下已有条目）。")
        store.save_experience(exp, reason=f"retro close {task_id}")
        messages.append(f"写入经验 {exp['experience_id']}")

    # ── 流程类教训落盘（SKILL.md §J 六类；用户纠正必须归类，不能只躺在 decisions.md）──
    lessons_dir = getattr(store, "LESSONS_DIR", store.STATE_DIR / "lessons")
    lessons_dir.mkdir(parents=True, exist_ok=True)
    added_lessons = []
    for les in payload.get("lessons") or []:
        ltype = les.get("lesson_type")
        if ltype not in LESSON_TYPES:
            die(f"教训 {les.get('title', '?')} 的 lesson_type={ltype!r} 不在六类内：{LESSON_TYPES}")
        existing = sorted(lessons_dir.glob("L-*.json"))
        next_no = len(existing) + 1
        lid = les.get("lesson_id") or f"L-{store.now_iso()[:10].replace('-', '')}-{next_no:03d}"
        doc = {
            "experience_id": lid,
            "lesson_type": ltype,
            "title": les.get("title", ""),
            "conclusion": les.get("conclusion", ""),
            "recommended_action": les.get("conclusion", ""),
            "trigger_conditions": les.get("trigger_conditions") or [],
            "limitations": les.get("limitations") or [],
            "counterexamples": [],
            "evidence": les.get("evidence") or [],
            "scope": "cross_task",
            "domain": "process",
            "source": f"任务 {task_id} 复盘：用户纠正",
            "status": "single_observation",
            "confidence": {"level": les.get("confidence_level", "medium"),
                           "basis": les.get("confidence_basis", "来自一次真实交互中的明确纠正")},
            "privacy_scope": "general",
            "created_at": store.now_iso(),
            "last_reviewed_at": None,
        }
        store.write_json(lessons_dir / f"{lid}.json", doc)
        added_lessons.append(lid)
        messages.append(f"新增教训 {lid}（{ltype}）《{doc['title'][:30]}》")

    # ── 方法使用记录（spec/03 §7-6：用了哪条经验/方法必须可追溯） ──
    used = payload.get("methods_used") or []
    if used:
        task["methods_used"] = used
        messages.append(f"记录使用的方法 {len(used)} 条")

    # ── 收尾：复盘状态闭环 ──
    task["retrospective"] = {
        "reviewed_at": store.now_iso(),
        "answers": answers,
        "no_new_experience_reason": payload.get("no_new_experience_reason"),
        "experiences_added": len(payload.get("experiences") or []),
        "skills_updated": len(payload.get("skills") or []),
        "methods_used": used,
        "lessons_added": added_lessons,
    }
    task["retrospective_status"] = "reviewed"
    store.append_history(task, "retro", "完成复盘并闭环")

    # 经验/教训变了就重建可读索引，避免它过期
    # （SKILL.md 承诺了 state/experience_index.md，此前无写入方）
    try:
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "build_index.py")],
                       capture_output=True, timeout=30)
        messages.append("已重建 state/experience_index.md")
    except Exception as exc:
        messages.append(f"注意：索引重建失败（{type(exc).__name__}）——可手工跑 scripts/build_index.py")

    backup = store.save_tasks(data, f"完成 {task_id} 复盘")
    if payload.get("skills"):
        store.save_skills(skills_data, f"{task_id} 复盘后更新技能档案")

    print(f"═══ 复盘完成：{task_id} ═══")
    for m in messages:
        print(f"  ✓ {m}")
    if not messages:
        print("  · 本次无经验新增、无技能更新（这是合法结果，spec/03 §8）")
        if not payload.get("no_new_experience_reason"):
            print("  ⚠️ 建议在 no_new_experience_reason 里写明为什么没有可复用经验")
    print(f"  复盘状态：pending_triage → reviewed（闭环）")
    print(f"  写前备份：{backup.relative_to(store.PROJECT_ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="复盘流程（spec/00 阶段1-9/10）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="列出待复盘任务")
    a = sub.add_parser("ask", help="打印五个必答问题")
    a.add_argument("--task", required=True)
    cap = sub.add_parser("capture", help="任务进行中捕获一条教训（不必等任务完成）")
    cap.add_argument("--task", required=True)
    cap.add_argument("--type", required=True, help=f"六类之一：{'/'.join(LESSON_TYPES)}")
    cap.add_argument("--title", required=True)
    cap.add_argument("--conclusion", required=True)
    cap.add_argument("--evidence", required=True)
    c = sub.add_parser("close", help="提交复盘答案并闭环")
    c.add_argument("--task", required=True)
    c.add_argument("--file", required=True, type=Path)
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "ask":
        return cmd_ask(args.task)
    if args.cmd == "capture":
        return cmd_capture(args.task, args.type, args.title, args.conclusion, args.evidence)
    return cmd_close(args.task, args.file)


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
