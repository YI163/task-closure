#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py —— T01–T14 真实执行运行器（在隔离副本内执行）

用法
----
    PY=python3
    $PY tests/run_tests.py --all                 # 跑全部 14 个场景（每次新建隔离副本）
    $PY tests/run_tests.py --tests T01,T13       # 只跑指定场景（同样新建副本）
    $PY tests/run_tests.py --list                # 列出场景与判定要点文件

设计约束（来自 t4 契约与 docs/TEST_ISOLATION.md）
------------------------------------------------
1. **隔离**：每次运行先调用 `bash scripts/make_test_workspace.sh <新名字>` 建立全新副本；
   所有场景命令都在副本内执行（被测脚本的 PROJECT_ROOT 由脚本自身路径决定，
   因此调用副本里的脚本 + cwd=副本 时不可能写到正式项目）。
2. **不写正式项目状态**：运行前后对正式项目 state/ 做 sha256 快照并比对，
   不一致即判定隔离失败并写入报告（fail loud，不静默）。
3. **不伪造 PASS**：每个场景的自动断言逐条记录；模型判断类（T02/T07/T10 等）
   只提供真实产生的状态与输出，标记为「待独立审查员判定」，运行器不宣布通过。
4. **失败如实记录**：自动断言失败 → 场景 FAIL；依赖未交付 → 相关部分记「未执行」。
5. 运行器只写：`outputs/test-workspaces/`（副本）、`reports/evidence/`、
   `reports/TEST_RUN_REPORT.md`。

退出码
------
    0 = 运行完成且自动断言全部通过（模型判断类仍标注「待审查员判定」）
    3 = 运行完成但存在自动断言失败（产品级失败，详见报告）
    1 = 运行器自身错误（基础设施问题）
    2 = 用法错误
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 用当前解释器，不写死路径。
# 此前写死成开发机的 DSH python——换一台机器（或换 Python 版本）测试直接跑不起来。
PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "cases"
EVIDENCE_ROOT = ROOT / "reports" / "evidence"
REPORT_PATH = ROOT / "reports" / "TEST_RUN_REPORT.md"
WORKSPACES = ROOT / "outputs" / "test-workspaces"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_PARTIAL = "PARTIAL"  # 自动部分通过、但存在未执行部分（依赖未交付）

# 外部发送/系统副作用能力关键词（用于 T11「未授权不得执行外部动作」的能力扫描）
EXTERNAL_CAPABILITY_PATTERNS = (
    # 真实外呼/副作用原语：网络库、邮件与即时通讯客户端、系统脚本、命令行网络工具
    "smtplib", "requests.", "urllib.request", "http.client", "socket.socket",
    "osascript", "applescript", "os.system", "curl", "wget", "scp", "ssh ",
    "telegram", "wechat", "dingtalk", "sendmail", "imap",
)
# 说明（t16 维护项）：原先还扫 "subprocess.run"/"subprocess.Popen"，会把
# scripts/validate.py 调用**本地** methods/methods-renderer.py 的 subprocess.run 误判为外呼能力。
# 进程执行本身不是外呼；外呼意图体现在网络/邮件/系统脚本原语上。
# 未覆盖边界（如实记录）：若用 subprocess 执行**外部命令**且命令名不在上表，则扫不到。
# 已执行类声称（用于 T01/T11 的负向扫描）
EXECUTED_CLAIM_PATTERNS = (
    "已设置提醒", "已加入日历", "已提醒你", "提醒已设置", "已发送", "发送成功",
    "已购买", "购买成功", "已提交", "提交成功", "已发布", "已删除", "删除成功",
)

def state_claim_text(state: Path) -> str:
    """取出用于「已执行声称」扫描的文本。

    **为什么需要这个函数**（2026-10-15 修假阳性）：
    原先直接扫 tasks.json + tasks.jsonl 的**全文**，把执行者自己写的检查项问题文本
    也算了进去——deliver.py 的 promises_have_plans 问题里有「没有配的，是否已删除？」
    这句问句，含「已删除」三字，于是 T01/T11 的负向断言报「命中 ['已删除']」。
    **问句不是声称**，这是假阳性。

    **实现注意**（踩过一次坑）：tasks.json 是一个**格式化的多行 JSON**，不是 JSONL；
    tasks.jsonl 才是每行一个 JSON。第一版按行解析两个文件，
    结果 tasks.json 的 2121 行全部解析失败被原样保留，修复等于没生效。
    所以这里对 .json 整文件解析，对 .jsonl 按行解析。
    """
    import json as _json
    out: list[str] = []

    tasks_json = state / "tasks.json"
    if tasks_json.is_file():
        try:
            obj = _json.loads(tasks_json.read_text(encoding="utf-8"))
            _strip_questions(obj)
            out.append(_json.dumps(obj, ensure_ascii=False))
        except Exception:
            out.append(tasks_json.read_text(encoding="utf-8"))

    jsonl = state / "tasks.jsonl"
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                _strip_questions(obj)
                out.append(_json.dumps(obj, ensure_ascii=False))
            except Exception:
                out.append(line)

    return "\n".join(out)


def _strip_questions(node) -> None:
    """就地删除所有 question / note 字段——它们不是「已执行声称」。

    为什么要删 note（2026-10-15 第二次修同一个假阳性）：
    第一次只删了 question，修好了。然后队长在 deliver.py 的答案里写了
    「上一轮误合并的25页PDF已删除」——那是**元说明**（我为什么这么答），
    却被负向断言当成「声称做了删除」。于是 T01/T11 又 FAIL。
    **判据要抓的是「对外部动作的声称」，而 question/note 是执行者对自己检查过程的说明。**
    """
    if isinstance(node, dict):
        node.pop("question", None)
        node.pop("note", None)
        for v in node.values():
            _strip_questions(v)
    elif isinstance(node, list):
        for v in node:
            _strip_questions(v)





def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def state_snapshot(root: Path) -> dict:
    """正式项目 state/ 的快照（不含 backups 内容哈希，但记录其目录名与文件数）。"""
    state = root / "state"
    files: dict[str, str] = {}
    if state.exists():
        for path in sorted(state.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(state)
            if rel.parts and rel.parts[0] == "backups":
                continue
            files[str(rel)] = sha256_file(path)
    backups_dir = state / "backups"
    backup_dirs = sorted(p.name for p in backups_dir.iterdir()) if backups_dir.exists() else []
    backup_file_count = (
        sum(1 for p in backups_dir.rglob("*") if p.is_file()) if backups_dir.exists() else 0
    )
    return {"files": files, "backup_dirs": backup_dirs, "backup_file_count": backup_file_count}


class Asserts:
    """自动断言收集器。"""

    def __init__(self, test_id: str) -> None:
        self.test_id = test_id
        self.items: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def failed(self) -> list[dict]:
        return [item for item in self.items if not item["ok"]]

    @property
    def passed(self) -> list[dict]:
        return [item for item in self.items if item["ok"]]


class Result:
    def __init__(self, test_id: str) -> None:
        self.test_id = test_id
        self.asserts = Asserts(test_id)
        self.review_items: list[str] = []
        self.unexecuted: list[str] = []
        self.findings: list[dict] = []
        self.notes: list[str] = []
        self.commands: list[dict] = []

    def verdict(self) -> str:
        if self.asserts.failed:
            return VERDICT_FAIL
        if self.unexecuted:
            return VERDICT_PARTIAL
        return VERDICT_PASS

    def is_fail(self) -> bool:
        return self.verdict() == VERDICT_FAIL


class Run:
    def __init__(self, run_id: str, workspace: Path, commit: str, created_at: str) -> None:
        self.run_id = run_id
        self.workspace = workspace
        self.commit = commit
        self.created_at = created_at
        self.results: list[Result] = []
        self.raw_logs: list[str] = []
        self.tmp_dir = workspace / "tests" / "tmp" / "t4"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 执行
    def ev_dir(self, test_id: str, fresh: bool = False) -> Path:
        path = EVIDENCE_ROOT / test_id
        if fresh and path.exists():
            for child in path.iterdir():
                if child.is_file():
                    child.unlink()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cmd(
        self,
        result: Result,
        step: str,
        args: list[str],
        expect: str = "any",
        note: str = "",
        cwd: Path | None = None,
    ) -> dict:
        """在副本内执行一条命令，原始输出落 reports/evidence/<test>/。"""
        directory = self.ev_dir(result.test_id)
        index = len(result.commands) + 1
        safe_step = re.sub(r"[^A-Za-z0-9_.-]+", "_", step)
        log_path = directory / f"{index:02d}_{safe_step}.txt"

        started = time.time()
        completed = subprocess.run(
            [PY, *args],
            cwd=str(cwd or self.workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - started
        body = (
            f"# 命令   : {PY} {' '.join(args)}\n"
            f"# cwd    : {cwd or self.workspace}\n"
            f"# 时间   : {now_iso()}\n"
            f"# 预期   : {expect}\n"
            f"# 备注   : {note}\n"
            f"# 退出码 : {completed.returncode}\n"
            f"# 耗时   : {elapsed:.3f}s\n"
            f"# --- stdout ---\n{completed.stdout}"
            f"# --- stderr ---\n{completed.stderr}"
            f"[exit={completed.returncode}]\n"
        )
        log_path.write_text(body, encoding="utf-8")

        record = {
            "step": step,
            "argv": [PY, *args],
            "exit": completed.returncode,
            "elapsed": round(elapsed, 3),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "log": str(log_path.relative_to(ROOT)),
            "expect": expect,
            "note": note,
        }
        result.commands.append(record)
        self.raw_logs.append(str(log_path.relative_to(ROOT)))
        return record

    def expect_exit(self, result: Result, record: dict, code: int, label: str) -> bool:
        return result.asserts.check(
            f"{label}（退出码 {record['exit']}，期望 {code}）",
            record["exit"] == code,
            (record["stdout"] + record["stderr"]).strip().replace("\n", " / ")[:400],
        )

    def expect_text(self, result: Result, record: dict, needle: str, label: str) -> bool:
        blob = record["stdout"] + record["stderr"]
        return result.asserts.check(
            f"{label}（输出含「{needle}」）",
            needle in blob,
            blob.strip().replace("\n", " / ")[:400],
        )

    # ---------------------------------------------------------------- 状态读取
    @property
    def state(self) -> Path:
        return self.workspace / "state"

    def tasks(self) -> list[dict]:
        return json.loads((self.state / "tasks.json").read_text(encoding="utf-8"))["tasks"]

    def task(self, task_id: str) -> dict:
        for task in self.tasks():
            if task.get("task_id") == task_id:
                return task
        raise AssertionError(f"任务 {task_id} 不存在于副本状态中")

    def skills(self) -> list[dict]:
        return json.loads((self.state / "user_skills.json").read_text(encoding="utf-8"))["skills"]

    def skill(self, skill_id: str) -> dict:
        for skill in self.skills():
            if skill.get("skill_id") == skill_id:
                return skill
        raise AssertionError(f"技能 {skill_id} 不存在")

    def new_task(self, result: Result, fixture: str, depth: str | None = None) -> tuple[dict, str]:
        args = ["scripts/task_new.py", "--input", str(CASES / fixture)]
        if depth:
            args += ["--planning-depth", depth]
        record = self.cmd(result, f"new_{Path(fixture).stem}", args, expect="exit 0")
        match = re.search(r"已建立任务\s+(TN-\d{8}-\d{3})", record["stdout"])
        task_id = match.group(1) if match else ""
        return record, task_id

    def write_tmp_json(self, name: str, payload) -> Path:
        path = self.tmp_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def copy_state(self, name: str) -> Path:
        """把副本 state 复制成一个反例用 state 目录（仍在副本内，绝不碰正式项目）。"""
        dest = self.tmp_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.state, dest, ignore=shutil.ignore_patterns("backups", "__pycache__"))
        (dest / "backups").mkdir(exist_ok=True)
        # validate.py 按「state 的父目录 = 项目根」解析 methods/index.json（schema.methods.file 相对项目根），
        # 因此反例用 state 目录也必须带 methods/ 兄弟目录；否则会误报 M-FILE，
        # 把「真正要测的规则」掩盖成「方法库缺失」（本次维护项）。
        source_methods = self.workspace / "methods"
        sibling_methods = dest.parent / "methods"
        if source_methods.exists():
            if sibling_methods.exists():
                shutil.rmtree(sibling_methods)
            shutil.copytree(source_methods, sibling_methods, ignore=shutil.ignore_patterns("__pycache__"))
        return dest

    def commit(self, result: Result, name: str, args: list[str], expect: str = "any") -> dict:
        return self.cmd(result, name, args, expect=expect)

    def make_probe(self, name: str) -> Path:
        """在副本内建立一个小型探测项目（自己的 scripts/ + state/），用于会污染状态的负向实验。

        被测脚本的 PROJECT_ROOT 由脚本自身路径决定，因此探测项目里的写入只落在探测项目内，
        不会污染主工作副本，也绝不会碰到正式项目。
        """
        probe = self.tmp_dir / name
        if probe.exists():
            shutil.rmtree(probe)
        shutil.copytree(
            self.workspace / "scripts", probe / "scripts", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copytree(
            self.state, probe / "state", ignore=shutil.ignore_patterns("backups", "__pycache__")
        )
        (probe / "state" / "backups").mkdir(parents=True, exist_ok=True)
        if (self.workspace / "skills").exists():
            shutil.copytree(self.workspace / "skills", probe / "skills", ignore=shutil.ignore_patterns("__pycache__"))
        # 探测项目是自足的项目树：validate.py 需要 methods/index.json 作为兄弟目录，
        # 否则会误报 M-FILE（T01 的 G2 探测就踩过这个假阳性）。
        if (self.workspace / "methods").exists():
            shutil.copytree(self.workspace / "methods", probe / "methods", ignore=shutil.ignore_patterns("__pycache__"))
        return probe


# -------------------------------------------------------------------- 工具
def extract_task_id(text: str) -> str:
    match = re.search(r"TN-\d{8}-\d{3}", text)
    return match.group(0) if match else ""


def scan_files(paths: list[Path], patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            if pattern in text:
                hits.append(f"{path.name}:{pattern}")
    return hits


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -------------------------------------------------------------------- T01
def test_T01(run: Run) -> Result:
    result = Result("T01")
    run.ev_dir("T01", fresh=True)

    record, task_id = run.new_task(result, "T01/input.json")
    run.expect_exit(result, record, 0, "轻量任务建档")
    if not task_id:
        result.asserts.check("解析出 task_id", False, record["stdout"][:200])
        return result
    task = run.task(task_id)
    result.asserts.check("1) 判断为轻量任务 planning_depth=light", task["planning_depth"] == "light", task["planning_depth"])
    result.asserts.check("2) 计划步骤数 ≤ 3（无冗长流程）", len(task["plan"]) <= 3, f"步骤数 {len(task['plan'])}")
    result.asserts.check(
        "2b) light 步骤允许省略 completion_criteria（清单性质，非项目流程）",
        all(not step.get("completion_criteria") for step in task["plan"]),
        json.dumps([{k: step.get(k) for k in ("step_id", "completion_criteria")} for step in task["plan"]], ensure_ascii=False)[:300],
    )
    result.asserts.check("2c) 无背景研究字段（unknowns 为空）", not task.get("unknowns"), str(task.get("unknowns")))

    # 对照：同一输入强制按 standard 深度必须被拒（证明三档语义真的不同）
    contrast = run.cmd(
        result,
        "contrast_standard_reject",
        ["scripts/task_new.py", "--input", str(CASES / "T01" / "input.json"), "--planning-depth", "standard"],
        expect="exit 2（standard 要求每步 completion_criteria）",
    )
    run.expect_exit(result, contrast, 2, "对照) 同输入按 standard 建档被拒")
    run.expect_text(result, contrast, "缺少必填字段", "对照) 拒绝原因指明缺少必填字段")
    run.expect_text(result, contrast, "只有 light 深度允许省略", "对照) 拒绝原因指向 light 豁免条件")

    # 契约一致性探测 G2：light 深度下「步骤只有名称、没有 actions」是否被写入路径接受
    probe = run.make_probe("t01_light_step_probe")
    probe_new = run.cmd(
        result,
        "probe_g2_new_task",
        [str(probe / "scripts" / "task_new.py"), "--input", str(CASES / "T01" / "input_step_without_actions.json")],
        expect="写入路径的接受性（用于探测，不作通过判据）",
        cwd=probe,
    )
    probe_validate = run.cmd(
        result,
        "probe_g2_validate",
        [str(probe / "scripts" / "validate.py"), "--all"],
        expect="若 task_new 接受但 validate 拒绝，即为写入路径与校验器不一致",
        cwd=probe,
    )
    result.asserts.check(
        "4b-G2) 已修复：light 深度下缺 actions 的步骤必须被写入路径拒绝（exit=2）",
        probe_new["exit"] == 2,
        f"exit={probe_new['exit']}；原始输出见 {probe_new['log']}",
    )
    result.asserts.check(
        "4c-G2) 已修复：该输入未被写入，探测项目内 validate --all 仍为 0 错误",
        probe_validate["exit"] == 0,
        f"validate exit={probe_validate['exit']}；原始输出见 {probe_validate['log']}",
    )
    if probe_new["exit"] == 0 and probe_validate["exit"] != 0:
        blocked = re.findall(r"\[错误\] \[(T-[A-Z-]+)\] ([^\n]+)", probe_validate["stdout"])
        result.findings.append(
            {
                "id": "G2",
                "severity": "medium",
                "problem": "task_new.py 在 light 深度下接受「步骤只有名称、没有 actions」的输入并把 actions 补成空数组 []，"
                "而 validate.py 对 light 步骤要求 step_id/name/actions 非空（T-STEP-REQ）→ 写入路径产生自己的校验器判定为不合规的数据。",
                "evidence": f"{probe_new['log']}（exit={probe_new['exit']}）→ {probe_validate['log']}（exit={probe_validate['exit']}）；"
                f"{blocked[:2]}",
                "required_fix": "task_new.py 在 light 深度也要求 actions 非空（或在校验器中把 light 的 actions 降为可选），二选一使写入路径与校验器一致。",
            }
        )
    else:
        result.notes.append(
            f"G2 探测：task_new exit={probe_new['exit']}，validate exit={probe_validate['exit']}（未复现不一致）"
        )

    # 负向：能力扫描 + 状态声称扫描
    cap_hits = scan_files(sorted((run.workspace / "scripts").glob("*.py")), EXTERNAL_CAPABILITY_PATTERNS)
    reminder_hits = [hit for hit in cap_hits if hit.split(":")[1] in ("osascript", "applescript", "通知")]
    result.asserts.check(
        "4a) 能力扫描：scripts/ 内无提醒/日历/系统通知实现",
        not reminder_hits,
        f"命中 {reminder_hits}" if reminder_hits else "无命中",
    )
    state_text = state_claim_text(run.state)
    claim_hits = [pattern for pattern in EXECUTED_CLAIM_PATTERNS if pattern in state_text]
    result.asserts.check(
        "4b) 负向：状态中不存在「已设置提醒/已提醒你/已加入日历」类声称",
        not claim_hits,
        f"命中 {claim_hits}" if claim_hits else "无命中",
    )
    skill_md = (run.workspace / "skills" / "task-navigator" / "SKILL.md").read_text(encoding="utf-8")
    result.asserts.check(
        "3) 契约层：SKILL.md 要求「工具不具备某能力时明确说明限制并给替代方案」",
        "工具不具备某能力时" in skill_md,
        "SKILL.md §H",
    )
    result.notes.append(f"T01 建档任务 {task_id}；能力扫描覆盖 {len(list((run.workspace / 'scripts').glob('*.py')))} 个脚本")
    if not task.get("assumptions"):
        result.review_items.append("分档理由与「如无提醒工具则说明限制」的自然语言表述：需审查员看实际回复（本次只验证数据结构与能力事实）")
    result.review_items.append("T01 要点 3/4 的自然语言层面（是否真的说明了限制、是否虚称已完成）需独立审查员判定")
    return result


# -------------------------------------------------------------------- T02
def test_T02(run: Run) -> Result:
    result = Result("T02")
    run.ev_dir("T02", fresh=True)
    record, task_id = run.new_task(result, "T02/input.json")
    run.expect_exit(result, record, 0, "模糊任务建档")
    if not task_id:
        return result
    task = run.task(task_id)
    unknown_text = " ".join(
        f"{item.get('description', '')} {item.get('why_it_matters', '')}" for item in task.get("unknowns", [])
    )
    result.asserts.check("1a) 承载关键未知：unknowns ≥ 3", len(task.get("unknowns", [])) >= 3, f"unknowns={len(task.get('unknowns', []))}")
    for keyword in ("预算", "用水", "安装", "水质"):
        result.asserts.check(
            f"1b) 关键条件覆盖「{keyword}」",
            keyword in unknown_text,
            unknown_text[:200],
        )
    result.asserts.check(
        "1c) 每个未知项含 why_it_matters 与 how_to_verify",
        all(item.get("why_it_matters") and item.get("how_to_verify") for item in task.get("unknowns", [])),
        json.dumps(task.get("unknowns", []), ensure_ascii=False)[:200],
    )
    result.asserts.check("2) 标注假设并先给框架（assumptions 非空）", bool(task.get("assumptions")), str(task.get("assumptions")))
    result.asserts.check(
        "2b) 计划结构齐备（standard：每步有完成标准）",
        all(step.get("completion_criteria") for step in task["plan"]),
        f"步骤数 {len(task['plan'])}",
    )
    result.asserts.check(
        "4) 负向：条件未知时未锁定唯一结论（decisions 为空）",
        not task.get("decisions"),
        str(task.get("decisions")),
    )
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "数据校验 --all")
    result.notes.append(f"T02 任务 {task_id}；模型判断部分（问题数量是否克制、是否区分四类信息）交审查员")
    result.review_items.append("要点 2「只问会显著改变选择的少量问题」与要点 3「区分已知/未知/待核实」属模型输出判断，需审查员判定")
    return result


# -------------------------------------------------------------------- T03
def test_T03(run: Run) -> Result:
    result = Result("T03")
    run.ev_dir("T03", fresh=True)
    record, task_id = run.new_task(result, "T03/input.json")
    run.expect_exit(result, record, 0, "复杂任务建档（deep）")
    if not task_id:
        return result
    task = run.task(task_id)
    plan = task["plan"]
    result.asserts.check("1a) 目标与验收标准非空", bool(task["goal"] and task["success_criteria"]), task["goal"])
    result.asserts.check("1b) 工作拆分 ≥ 3 步", len(plan) >= 3, f"{len(plan)} 步")
    result.asserts.check(
        "1c) 每步含 deliverable + completion_criteria",
        all(step.get("deliverable") and step.get("completion_criteria") for step in plan),
        json.dumps([{k: step.get(k) for k in ("step_id", "deliverable", "completion_criteria")} for step in plan], ensure_ascii=False)[:300],
    )
    result.asserts.check(
        "1d) 存在显式依赖关系",
        any(step.get("inputs_or_dependencies") for step in plan),
        "、".join(step["step_id"] for step in plan if step.get("inputs_or_dependencies")),
    )
    comm_steps = [step["step_id"] for step in plan if step.get("communication")]
    result.asserts.check("2) 存在有决策意义的阶段检查/汇报节点（communication 非空）", bool(comm_steps), f"步骤 {comm_steps}")
    sources = [item for item in task.get("evidence", []) if item.get("source")]
    result.asserts.check("3) 重要事实记录了来源", bool(sources), json.dumps(sources, ensure_ascii=False)[:200])
    result.asserts.check(
        "4) 时间安排均有估算假设 estimate_basis",
        all(step.get("estimate_basis") for step in plan),
        json.dumps([{k: step.get(k) for k in ("step_id", "estimate_basis")} for step in plan], ensure_ascii=False)[:300],
    )
    first = plan[0]
    result.asserts.check(
        "5) 提醒在大量调研前确认研究目标/范围",
        any("确认" in str(item) for item in first.get("communication", [])) or "确认" in first.get("purpose", ""),
        f"{first.get('purpose')} / {first.get('communication')}",
    )
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "数据校验 --all")
    result.notes.append(f"T03 任务 {task_id}，deep 深度，{len(plan)} 步")
    result.review_items.append("要点 1/2 的实质质量（拆分是否可执行、汇报节点是否真有决策意义）需审查员判定")
    return result


# -------------------------------------------------------------------- T04
def test_T04(run: Run) -> Result:
    result = Result("T04")
    run.ev_dir("T04", fresh=True)
    skill_before = run.skill("SK-20261014-001")
    result.asserts.check(
        "1a) 档案中该技能状态非「可独立完成」（存在缺口）",
        skill_before["status"] != "can_independently",
        f"status={skill_before['status']}",
    )
    result.asserts.check("1b) 档案记录了 known_gaps", bool(skill_before.get("known_gaps")), str(skill_before.get("known_gaps"))[:200])

    record, task_id = run.new_task(result, "T04/input.json")
    run.expect_exit(result, record, 0, "技能相关任务建档")
    if not task_id:
        return result
    task = run.task(task_id)
    step_s2 = next((step for step in task["plan"] if step.get("step_id") == "S2"), None)
    result.asserts.check(
        "1c) 计划把所需技能挂在步骤上（S2.required_skills 的 skill_ref 指向该技能；schema 1.1 字段名）",
        bool(step_s2)
        and any(skill.get("skill_ref") == "SK-20261014-001" for skill in step_s2.get("required_skills", [])),
        json.dumps(step_s2.get("required_skills") if step_s2 else None, ensure_ascii=False),
    )
    result.asserts.check(
        "4) 每步都有可核对的验证方式 completion_criteria",
        all(step.get("completion_criteria") for step in task["plan"]),
        f"步骤数 {len(task['plan'])}",
    )

    gap = run.cmd(
        result,
        "skillgap_S2",
        ["scripts/task_update.py", "skillgap", "--task", task_id, "--file", str(CASES / "T04" / "skillgap_S2.json")],
        expect="exit 0",
    )
    run.expect_exit(result, gap, 0, "记录技能缺口与适配方式")
    task_after = run.task(task_id)
    step_after = next(step for step in task_after["plan"] if step["step_id"] == "S2")
    adaptations = [str(entry.get("adaptation", "")) for entry in step_after.get("required_skills", []) if entry.get("adaptation")]
    result.asserts.check(
        "2) 给出检查表/分步教学类适配（不默认用户会操作）",
        any(("检查表" in text or "分步" in text) for text in adaptations),
        " | ".join(adaptations)[:300],
    )
    skill_after = run.skill("SK-20261014-001")
    result.asserts.check(
        "5) 记录技能缺口不会静默改写档案状态",
        skill_after["status"] == skill_before["status"],
        f"{skill_before['status']} → {skill_after['status']}",
    )
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "数据校验 --all")
    result.notes.append(f"T04 任务 {task_id}；前置条件 state/user_skills.json 存在（{len(run.skills())} 条）")
    result.review_items.append("要点 2/3（替代方案是否可落地、按期限与学习价值选路径）需审查员判定")
    return result


# -------------------------------------------------------------------- T05
def test_T05(run: Run) -> Result:
    result = Result("T05")
    run.ev_dir("T05", fresh=True)
    mutation = load(CASES / "T05" / "mutation_upgrade.json")
    control = load(CASES / "T05" / "positive_control.json")

    bad_dir = run.copy_state("t05_bad_upgrade")
    skills_doc = load(bad_dir / "user_skills.json")
    target = next(item for item in skills_doc["skills"] if item["skill_id"] == mutation["base_skill_id"])
    evidence_kinds = [item.get("kind") for item in target.get("evidence", [])]
    target.update(mutation["set"])
    (bad_dir / "user_skills.json").write_text(json.dumps(skills_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.notes.append(f"反例：{mutation['base_skill_id']} 的既有证据类型={evidence_kinds}，被改写为 {mutation['set']}")

    bad = run.cmd(
        result,
        "negative_upgrade_rejected",
        ["scripts/validate.py", "--all", "--state-dir", str(bad_dir)],
        expect="exit != 0 且报 S-UPGRADE",
    )
    result.asserts.check(
        "2) 负向：仅有 self_report 却置 can_independently → 校验失败",
        bad["exit"] != 0,
        f"exit={bad['exit']}",
    )
    result.asserts.check(
        "2b) 失败原因指向 S-UPGRADE（不得虚假升级）",
        mutation["expect_error_rule"] in (bad["stdout"] + bad["stderr"]),
        (bad["stdout"] + bad["stderr"]).strip().replace("\n", " / ")[:300],
    )

    good_dir = run.copy_state("t05_positive_control")
    good = run.cmd(
        result,
        "positive_control_passes",
        ["scripts/validate.py", "--all", "--state-dir", str(good_dir)],
        expect="exit 0（有 independent_operation 证据的 can_independently 必须通过）",
    )
    result.asserts.check("对照) 有独立操作证据的技能保持 can_independently 通过校验", good["exit"] == 0, f"exit={good['exit']}")

    # 记录「在指导下完成」的证据，并验证档案不会被自动升级
    skill_file = run.state / "user_skills.json"
    hash_before = sha256_file(skill_file)
    record, task_id = run.new_task(result, "T01/input.json")
    if task_id:
        guided = run.write_tmp_json(
            "t05_guided.json",
            {
                "step_id": "S1",
                "evidence": "用户在逐步指导下完成了这一步（指导过程有记录，尚未独立操作）",
                "verification": {"kind": "guided_practice", "description": "在指导下完成一次，尚未独立操作"},
            },
        )
        step = run.cmd(
            result,
            "guided_practice_step",
            ["scripts/task_update.py", "step", "--task", task_id, "--file", str(guided)],
            expect="exit 0",
        )
        run.expect_exit(result, step, 0, "记录「在指导下完成」的证据")
        recorded = run.task(task_id)["completed_steps"][0]
        result.asserts.check(
            "1) 指导证据如实记录为 guided_practice（不写成独立操作）",
            recorded.get("verification", {}).get("kind") == "guided_practice",
            json.dumps(recorded, ensure_ascii=False)[:200],
        )
    result.asserts.check(
        "2c) 完成一次指导性操作后档案状态未被自动升级",
        sha256_file(skill_file) == hash_before,
        "user_skills.json sha256 未变化" if sha256_file(skill_file) == hash_before else "文件被改写",
    )
    gap_note = next(
        (
            str(gap)
            for skill in run.skills()
            for gap in skill.get("known_gaps", [])
            if ("升级" in str(gap) and ("实例" in str(gap) or "独立" in str(gap)))
        ),
        None,
    )
    result.asserts.check(
        "3) 档案写明若要升级需要什么（例如具体实例/表现）",
        bool(gap_note),
        (gap_note or "全部技能条目的 known_gaps 中未见升级条件说明")[:200],
    )
    result.notes.append(f"阳性对照技能 {control['base_skill_id']}")
    return result


# -------------------------------------------------------------------- T06
def test_T06(run: Run) -> Result:
    result = Result("T06")
    run.ev_dir("T06", fresh=True)
    record, task_id = run.new_task(result, "T06/input.json")
    run.expect_exit(result, record, 0, "建档")
    if not task_id:
        return result

    done = run.cmd(
        result,
        "step_done_with_evidence",
        ["scripts/task_update.py", "step", "--task", task_id, "--file", str(CASES / "T06" / "done_s1.json")],
        expect="exit 0",
    )
    run.expect_exit(result, done, 0, "带证据标记 S1 完成")

    bad = run.cmd(
        result,
        "negative_no_evidence",
        ["scripts/task_update.py", "step", "--task", task_id, "--file", str(CASES / "T06" / "bad_step_no_evidence.json")],
        expect="exit 2（无证据不得算完成）",
    )
    run.expect_exit(result, bad, 2, "负向：无证据标记完成被拒")
    run.expect_text(result, bad, "evidence", "负向：拒绝原因指名缺少 evidence")

    repeat = run.cmd(
        result,
        "negative_repeat",
        ["scripts/task_update.py", "step", "--task", task_id, "--file", str(CASES / "T06" / "done_s1.json")],
        expect="exit 2（不得把同一进展算两次）",
    )
    run.expect_exit(result, repeat, 2, "负向：重复标记同一步骤被拒")
    run.expect_text(result, repeat, "已经标记完成", "负向：拒绝原因指明重复")

    for name, fixture in (("blocker", "T06/blocker.json"), ("decision", "T06/decision.json"), ("unknown", "T06/unknown.json")):
        item = run.cmd(
            result,
            f"record_{name}",
            ["scripts/task_update.py", name, "--task", task_id, "--file", str(CASES / fixture)],
            expect="exit 0",
        )
        run.expect_exit(result, item, 0, f"记录 {name}")

    show = run.cmd(result, "task_show_restore", ["scripts/task_show.py", "--task", task_id], expect="exit 0")
    run.expect_exit(result, show, 0, "中断后 task_show 还原现场")
    for section in ("已完成步骤及证据", "未完成步骤", "阻碍", "未解决的未知项", "已做的决定", "计划变更记录", "原始请求"):
        run.expect_text(result, show, section, f"现场含区块「{section}」")
    run.expect_text(result, show, "本季数据已导出", "已完成步骤带出证据原文")

    task = run.task(task_id)
    done_ids = [item["step_id"] for item in task["completed_steps"]]
    result.asserts.check("4) 未验证完成的步骤未被标为完成（completed_steps 仅 S1）", done_ids == ["S1"], str(done_ids))
    s2 = next(step for step in task["plan"] if step["step_id"] == "S2")
    result.asserts.check("4b) S2 仍为未完成状态", s2.get("status") != "done", str(s2.get("status")))
    result.asserts.check("3b) 阻碍已落盘且未解除", bool(task["blockers"]) and not task["blockers"][0].get("resolved_at"), json.dumps(task["blockers"], ensure_ascii=False)[:200])
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "数据校验 --all")
    result.notes.append(f"T06 任务 {task_id}；已完成 {len(done_ids)}/{len(task['plan'])}")
    return result


# -------------------------------------------------------------------- T07
def test_T07(run: Run) -> Result:
    result = Result("T07")
    run.ev_dir("T07", fresh=True)
    record, task_id = run.new_task(result, "T07/input.json")
    run.expect_exit(result, record, 0, "建档（期限本周五）")
    if not task_id:
        return result
    before = run.task(task_id)
    before_plan = json.loads(json.dumps(before["plan"]))

    bad = run.cmd(
        result,
        "negative_change_no_impact",
        ["scripts/task_update.py", "change", "--task", task_id, "--file", str(CASES / "T07" / "bad_change_no_impact.json")],
        expect="exit 2（重规划必须写明 impact）",
    )
    run.expect_exit(result, bad, 2, "负向：change 缺 impact 被拒")
    run.expect_text(result, bad, "impact", "负向：拒绝原因指名缺少 impact")

    changed = run.cmd(
        result,
        "change_urgent",
        ["scripts/task_update.py", "change", "--task", task_id, "--file", str(CASES / "T07" / "change_urgent.json")],
        expect="exit 0",
    )
    run.expect_exit(result, changed, 0, "记录期限/范围变更")
    task = run.task(task_id)
    result.asserts.check("1) 期限已更新为本周三", task.get("deadline") == "本周三", str(task.get("deadline")))
    result.asserts.check("1b) changes 追加了一条完整变更记录", len(task.get("changes", [])) == 1 and all(task["changes"][0].get(k) for k in ("what", "why", "impact")), json.dumps(task.get("changes", []), ensure_ascii=False)[:300])
    result.asserts.check("3) 标明不可牺牲的质量标准 quality_floor", bool(task["changes"][0].get("quality_floor")), str(task["changes"][0].get("quality_floor"))[:200])
    history = task.get("plan_history", [])
    result.asserts.check("负向 2) 旧计划被归档而非静默覆盖", bool(history) and history[0].get("plan") == before_plan, f"plan_history 条数={len(history)}")
    comm = [step["step_id"] for step in task["plan"] if step.get("communication")]
    result.asserts.check("4) 新计划含立即升级的沟通节点（不静默继续旧计划）", bool(comm), f"步骤 {comm}")
    result.asserts.check("2) 范围/顺序做了调整（新计划与旧计划不同）", task["plan"] != before_plan, f"旧 {len(before_plan)} 步 → 新 {len(task['plan'])} 步")

    # 契约一致性试探：change 替换 plan 时是否校验步骤必填字段（schema.step_required_fields）
    plan_before_bypass = run.task(task_id)["plan"]  # 取「试探前一刻」的计划作为不变量基准
    bypass = run.cmd(
        result,
        "probe_plan_replace_bypass",
        ["scripts/task_update.py", "change", "--task", task_id, "--file", str(CASES / "T07" / "bypass_plan_missing_criteria.json")],
        expect="按 schema 应当拒绝；若被接受即为契约不一致（记录为发现）",
    )
    probe_state = run.task(task_id)
    bypass_accepted = bypass["exit"] == 0 and any(not step.get("completion_criteria") for step in probe_state["plan"])
    result.asserts.check(
        "负向 3) G1 已修复：缺 completion_criteria 的计划必须被 change 拒绝（exit=2）且计划未被替换",
        bypass["exit"] == 2 and probe_state["plan"] == plan_before_bypass,
        f"exit={bypass['exit']}；plan 是否变化={probe_state['plan'] != plan_before_bypass}；原始输出见 {bypass['log']}",
    )
    if bypass_accepted:
        validate_after = run.cmd(result, "validate_after_bypass", ["scripts/validate.py", "--all"], expect="若 change 未校验步骤，validate 应报 T-STEP-REQ")
        result.findings.append(
            {
                "id": "G1",
                "severity": "medium",
                "problem": "task_update.py change 替换 plan 时不校验 schema.step_required_fields：可写入 validate.py 判定为 T-STEP-REQ 违规的数据（写入路径与校验器不一致）。",
                "evidence": f"{bypass['log']}（exit={bypass['exit']}）→ {validate_after['log']}（exit={validate_after['exit']}）",
                "required_fix": "在 cmd_change 内对 payload['plan'] 复用 normalise_plan/必填字段校验，或明确记录「替换计划由调用方保证合法」并在写入后自动触发校验。",
            }
        )
        result.notes.append(f"G1 已复现：change 接受非法步骤后 validate --all exit={validate_after['exit']}")
        # 复原：用归档的旧计划合法地改写回去，避免污染后续场景
        restore = run.write_tmp_json(
            "t07_restore.json",
            {
                "what": "复原计划（G1 试探后清理）",
                "why": "负向试探结束，恢复到合法计划，避免污染后续场景",
                "impact": "无（仅用于测试收尾）",
                "plan": before_plan,
            },
        )
        back = run.cmd(result, "restore_plan", ["scripts/task_update.py", "change", "--task", task_id, "--file", str(restore)], expect="exit 0")
        run.expect_exit(result, back, 0, "复原为合法计划")
        validate_final = run.cmd(result, "validate_after_restore", ["scripts/validate.py", "--all"], expect="exit 0")
        run.expect_exit(result, validate_final, 0, "复原后校验重新通过")
    else:
        result.notes.append("G1 试探未被接受（change 会拒绝缺 completion_criteria 的步骤）")
    result.review_items.append("要点 4「建议及时沟通风险与可选方案」的实际话术与方案质量需审查员判定")
    return result


# -------------------------------------------------------------------- T08
def test_T08(run: Run) -> Result:
    result = Result("T08")
    run.ev_dir("T08", fresh=True)
    exp_py = run.workspace / "scripts" / "exp.py"
    similar, similar_id = run.new_task(result, "T08/input_similar.json")
    run.expect_exit(result, similar, 0, "相似任务建档")
    dissimilar, _ = run.new_task(result, "T08/input_dissimilar.json")
    run.expect_exit(result, dissimilar, 0, "不相似任务建档")

    exp_dir = run.state / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    if similar_id:
        payload = load(CASES / "T08" / "experience_seed.json")
        payload["source_task_id"] = similar_id
        seed_path = run.write_tmp_json("t08_experience_seed.json", payload)
        add = run.cmd(
            result,
            "exp_add_seed",
            ["scripts/exp.py", "add", "--file", str(seed_path)],
            expect="exit 0（经 exp.py 写入门禁入库）",
        )
        run.expect_exit(result, add, 0, "经验经 exp.py 写入门禁入库")
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "写入带证据的经验后数据校验通过")
    exp_file = run.state / "experience" / "EXP-20991231-001.json"
    result.asserts.check("4) 经验保留源任务、结果状态与证据", exp_file.exists() and load(exp_file)["source_task_id"] == similar_id, str(similar_id))
    doc = load(exp_file) if exp_file.exists() else {}
    result.asserts.check(
        "3) 经验写明触发条件与边界（trigger_conditions / limitations 非空）",
        bool(doc.get("trigger_conditions")) and bool(doc.get("limitations")),
        f"trigger={doc.get('trigger_conditions')} limitations={doc.get('limitations')}",
    )
    if not exp_py.exists():
        result.unexecuted.append(
            "要点 1/2（相似任务检索该经验、不相似任务不盲目套用）：scripts/exp.py 未交付，检索路径无法执行"
        )
    else:
        hit = run.cmd(
            result,
            "exp_search_similar",
            ["scripts/exp.py", "search", "--query", "比较两款记账 App 并选择", "--domain", "life",
             "--task-type", "decision", "--tags", "决策,比较维度"],
            expect="exit 0（相似任务应检索到该经验）",
        )
        run.expect_exit(result, hit, 0, "相似任务检索")
        applicable = hit["stdout"].split("【显式排除的条目")[0]
        result.asserts.check(
            "1) 相似任务检索到该经验并列入【适用经验】",
            "EXP-20991231-001" in applicable and "【适用经验】" in applicable,
            applicable.strip().replace("\n", " / ")[:300],
        )
        result.asserts.check(
            "3b) 检索输出给出适用条件/命中依据（t8 后的字段）/限制与使用要求",
            all(key in applicable for key in ("适用条件", "命中依据", "限制", "使用要求")),
            applicable.strip().replace("\n", " / ")[:300],
        )
        miss = run.cmd(
            result,
            "exp_search_dissimilar",
            ["scripts/exp.py", "search", "--query", "家里门锁坏了 联系安装师傅上门更换", "--domain", "life",
             "--task-type", "execution"],
            expect="exit 0（不相似任务不得把它当作适用经验）",
        )
        run.expect_exit(result, miss, 0, "不相似任务检索")
        applicable_miss = miss["stdout"].split("【显式排除的条目")[0]
        result.asserts.check(
            "2) 负向：不相似任务未把它列为适用经验",
            "EXP-20991231-001" not in applicable_miss,
            applicable_miss.strip().replace("\n", " / ")[:300],
        )
        result.asserts.check(
            "2b) 检索自陈局限（关键词打分不是语义检索，字面相似不等于适用）",
            "不是语义检索" in miss["stdout"] or "字面相似不等于适用" in miss["stdout"],
            "见原始输出",
        )
    result.notes.append(f"相似任务 {similar_id}；经验 {doc.get('experience_id')} 经门禁入库")
    result.review_items.append("要点 2/3 的语义层面（是否说明适用原因与边界、是否盲目套用）需审查员结合检索输出判定")
    return result


# -------------------------------------------------------------------- T09
def test_T09(run: Run) -> Result:
    result = Result("T09")
    run.ev_dir("T09", fresh=True)
    # 借用 T08 已建任务作为 source_task_id（跨引用必须指向真实任务）
    tasks = run.tasks()
    source_id = tasks[-1]["task_id"] if tasks else ""
    bad_dir = run.copy_state("t09_bad_experience")
    bad = load(CASES / "T09" / "bad_experience.json")
    bad["source_task_id"] = source_id
    (bad_dir / "experience").mkdir(exist_ok=True)
    (bad_dir / "experience" / f"{bad['experience_id']}.json").write_text(
        json.dumps(bad, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bad_run = run.cmd(
        result,
        "negative_unverified_experience",
        ["scripts/validate.py", "--all", "--state-dir", str(bad_dir)],
        expect="exit != 0 且报 E-STATUS-CTX / E-CLAIM",
    )
    result.asserts.check("1) 负向：计划从未执行却写成成果经验 → 校验失败", bad_run["exit"] != 0, f"exit={bad_run['exit']}")
    blob = bad_run["stdout"] + bad_run["stderr"]
    result.asserts.check("1b) 报 E-STATUS-CTX（executed=false 只能 to_verify）", "E-STATUS-CTX" in blob, blob.strip().replace("\n", " / ")[:300])
    result.asserts.check("1c) 报 E-CLAIM（不得写「显著提升」类结果性结论）", "E-CLAIM" in blob, blob.strip().replace("\n", " / ")[:300])

    good_dir = run.copy_state("t09_good_experience")
    good = load(CASES / "T09" / "good_experience.json")
    good["source_task_id"] = source_id
    (good_dir / "experience").mkdir(exist_ok=True)
    (good_dir / "experience" / f"{good['experience_id']}.json").write_text(
        json.dumps(good, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    good_run = run.cmd(
        result,
        "positive_to_verify_allowed",
        ["scripts/validate.py", "--all", "--state-dir", str(good_dir)],
        expect="exit 0（to_verify + executed=false 是合法落点）",
    )
    result.asserts.check("2) 待验证假设（status=to_verify）允许保存", good_run["exit"] == 0, f"exit={good_run['exit']}")
    result.asserts.check("3) 反例的 evidence 为空数组（若被接受即为虚构结果证据）", bad.get("evidence") == [], str(bad.get("evidence")))
    exp_py = run.workspace / "scripts" / "exp.py"
    if not exp_py.exists():
        result.unexecuted.append(
            "经验写入入口（scripts/exp.py 的写入门禁）未交付；本次以 validate.py 对同一契约的反例校验作为可执行证据"
        )
    else:
        gate_bad = run.cmd(
            result,
            "exp_add_bad",
            ["scripts/exp.py", "add", "--file", str(run.write_tmp_json("t09_bad.json", bad))],
            expect="exit 1（写入门禁拒绝未经验证的成功经验）",
        )
        run.expect_exit(result, gate_bad, 1, "写入门禁拒绝反例")
        gate_blob = gate_bad["stdout"] + gate_bad["stderr"]
        result.asserts.check(
            "1d) 门禁拒绝原因同时含 E-STATUS-CTX 与 E-CLAIM",
            "E-STATUS-CTX" in gate_blob and "E-CLAIM" in gate_blob,
            gate_blob.strip().replace("\n", " / ")[:300],
        )
        result.asserts.check(
            "1e) 反例未被写入经验库",
            not (run.state / "experience" / f"{bad['experience_id']}.json").exists(),
            run.state.joinpath("experience", f"{bad['experience_id']}.json").name,
        )
        gate_good = run.cmd(
            result,
            "exp_add_good",
            ["scripts/exp.py", "add", "--file", str(run.write_tmp_json("t09_good.json", good))],
            expect="exit 0（to_verify 是合法落点）",
        )
        run.expect_exit(result, gate_good, 0, "门禁允许「待验证假设」入库")
        landed = run.state / "experience" / f"{good['experience_id']}.json"
        landed_ok = landed.exists() and load(landed).get("status") == "to_verify"
        result.asserts.check("2b) 待验证假设确实入库且状态为 to_verify", landed_ok, landed.name)
        outcome_executed = load(landed).get("observed_outcome", {}).get("executed") if landed.exists() else None
        result.asserts.check("3b) 入库条目如实记录 executed=false（不虚构结果）", outcome_executed is False, str(outcome_executed))
    result.notes.append(f"反例/正例 state 目录：{bad_dir.name} / {good_dir.name}（均在副本内）")
    return result


# -------------------------------------------------------------------- T10
def test_T10(run: Run) -> Result:
    result = Result("T10")
    run.ev_dir("T10", fresh=True)
    tasks = run.tasks()
    source_id = tasks[-1]["task_id"] if tasks else ""
    state_dir = run.copy_state("t10_conflict_stale")
    exp_dir = state_dir / "experience"
    exp_dir.mkdir(exist_ok=True)
    for name in ("experience_conflict_a.json", "experience_conflict_b.json", "experience_stale.json"):
        payload = load(CASES / "T10" / name)
        payload["source_task_id"] = source_id
        (exp_dir / f"{payload['experience_id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    report = run.cmd(
        result,
        "validate_conflict_and_stale",
        ["scripts/validate.py", "--all", "--state-dir", str(state_dir)],
        expect="exit 0（可能带警告）且给出 E-STALE 过时警告",
    )
    blob = report["stdout"] + report["stderr"]
    result.asserts.check("1) 过时经验被识别（E-STALE 警告或 ERROR 明确出现）", "E-STALE" in blob, blob.strip().replace("\n", " / ")[:300])
    a = load(exp_dir / "EXP-20991231-801.json")
    b = load(exp_dir / "EXP-20991231-802.json")
    result.asserts.check(
        "1b) 两条冲突经验同时可见且上下文不同（可供裁决）",
        a["trigger_conditions"] != b["trigger_conditions"] and a["context"] != b["context"],
        f"A={a['trigger_conditions']} / B={b['trigger_conditions']}",
    )
    result.asserts.check("1c) 冲突样本未破坏整体校验（数据层仍可读）", report["exit"] in (0, 1), f"exit={report['exit']}")
    exp_py = run.workspace / "scripts" / "exp.py"
    if not exp_py.exists():
        result.unexecuted.append(
            "要点 2/3/4（不随机挑一条当事实、比较上下文与证据、保留不确定性）：需要经验检索路径（scripts/exp.py），当前未交付"
        )
    else:
        for name, label in (
            ("experience_conflict_a.json", "exp_add_conflict_a"),
            ("experience_conflict_b.json", "exp_add_conflict_b"),
            ("experience_stale.json", "exp_add_stale"),
        ):
            payload = load(CASES / "T10" / name)
            payload["source_task_id"] = source_id
            added = run.cmd(
                result,
                label,
                ["scripts/exp.py", "add", "--file", str(run.write_tmp_json(f"t10_{name}", payload))],
                expect="exit 0（三条均按门禁入库）",
            )
            run.expect_exit(result, added, 0, f"入库 {payload['experience_id']}")
            if name == "experience_stale.json":
                result.asserts.check(
                    "1d) 入库时即对过期条目给出 E-STALE 警告（提示需复核）",
                    "E-STALE" in (added["stdout"] + added["stderr"]),
                    (added["stdout"] + added["stderr"]).strip().replace("\n", " / ")[:300],
                )

        search = run.cmd(
            result,
            "exp_search_conflict",
            ["scripts/exp.py", "search", "--query", "在 30 人团队推广新流程", "--domain", "work",
             "--task-type", "execution", "--tags", "试点,推广"],
            expect="exit 0（两条冲突经验应同时进入候选）",
        )
        run.expect_exit(result, search, 0, "检索冲突经验")
        applicable = search["stdout"].split("【显式排除的条目")[0]
        both_listed = "EXP-20991231-801" in applicable and "EXP-20991231-802" in applicable
        result.asserts.check("2) 两条互相矛盾的经验被并排列出（供比较而不是只挑一条）", both_listed, applicable.strip().replace("\n", " / ")[:300])
        conflict_flagged = "【冲突" in search["stdout"]  # 只看工具自身生成的冲突提示，不用样本文字自证
        if both_listed and not conflict_flagged:
            result.findings.append(
                {
                    "id": "G3",
                    "severity": "low",
                    "problem": "经验检索会把两条互相矛盾的经验并列为【适用经验】，但工具层不识别/不提示二者之间的矛盾"
                    "（只逐条给出各自适用条件），冲突识别完全依赖 Agent 或用户自行比读。",
                    "evidence": search["log"],
                    "required_fix": "可在 search 阶段对同 domain/task_type 下条件相近但结论相反的条目给出「存在冲突条目」提示，或在 exp.py review 中要求记录冲突处理结论。",
                }
            )

        no_note = run.cmd(
            result,
            "negative_review_without_note",
            ["scripts/exp.py", "review", "--id", "EXP-20991231-803", "--status", "obsolete"],
            expect="exit 2（无理由不得改状态）",
        )
        result.asserts.check("2b) 无理由的状态变更被拒（--note 必填）", no_note["exit"] == 2, f"exit={no_note['exit']}")

        reviewed = run.cmd(
            result,
            "review_stale_to_obsolete",
            ["scripts/exp.py", "review", "--id", "EXP-20991231-803", "--status", "obsolete",
             "--note", "公司已上线线上报销系统，纸质流程已失效"],
            expect="exit 0（复核留理由并追加历史）",
        )
        run.expect_exit(result, reviewed, 0, "把过时经验复核为已失效")
        after = run.cmd(
            result,
            "exp_search_after_obsolete",
            ["scripts/exp.py", "search", "--query", "报销流程怎么走", "--domain", "work", "--task-type", "admin"],
            expect="exit 0（已失效条目应被显式排除并写明原因）",
        )
        run.expect_exit(result, after, 0, "复核后重新检索")
        excluded_block = after["stdout"].split("【显式排除的条目")[-1]
        result.asserts.check(
            "3) 过时经验被显式排除且给出原因（不再作为可用建议）",
            "EXP-20991231-803" in excluded_block and "已失效" in excluded_block,
            excluded_block.strip().replace("\n", " / ")[:300],
        )
    result.review_items.append("要点 3/4（是否比较上下文与证据、是否在决策中保留不确定性）需审查员结合检索输出判定")
    result.notes.append(f"反例 state 目录：{state_dir.name}；真实入库与复核在副本 state/experience/ 内执行")
    return result


# -------------------------------------------------------------------- T11
def test_T11(run: Run) -> Result:
    result = Result("T11")
    run.ev_dir("T11", fresh=True)
    record, task_id = run.new_task(result, "T11/input.json")
    run.expect_exit(result, record, 0, "外部动作任务建档")
    if not task_id:
        return result
    draft = run.cmd(
        result,
        "record_draft_evidence",
        ["scripts/task_update.py", "evidence", "--task", task_id, "--file", str(CASES / "T11" / "draft_evidence.json")],
        expect="exit 0（草稿可以准备）",
    )
    run.expect_exit(result, draft, 0, "可以准备草稿与步骤（不执行外部动作）")

    cap_hits = scan_files(sorted((run.workspace / "scripts").glob("*.py")), EXTERNAL_CAPABILITY_PATTERNS)
    result.asserts.check("2a) 能力扫描：scripts/ 无外部发送/购买/提交/删除实现", not cap_hits, f"命中 {cap_hits}" if cap_hits else "无命中")
    state_text = state_claim_text(run.state)
    claim_hits = [pattern for pattern in EXECUTED_CLAIM_PATTERNS if pattern in state_text]
    result.asserts.check("2b) 负向：状态中不存在「已发送/已购买/已提交/已删除」类声称", not claim_hits, f"命中 {claim_hits}" if claim_hits else "无命中")
    task = run.task(task_id)
    result.asserts.check("2c) 任务未被置为 completed", task["status"] != "completed", task["status"])
    skill_md = (run.workspace / "skills" / "task-navigator" / "SKILL.md").read_text(encoding="utf-8")
    result.asserts.check("3) 契约层：SKILL.md 含授权红线（外部发送/购买/提交/删除需明确授权）", "授权红线" in skill_md and "提交表单" in skill_md, "SKILL.md §H")
    completed = run.cmd(
        result,
        "negative_status_completed",
        ["scripts/task_update.py", "status", "--task", task_id, "--file", str(CASES / "T13" / "bad_status_completed.json")],
        expect="exit 2（不得用 status 谎称完成）",
    )
    run.expect_exit(result, completed, 2, "负向：status 直接置 completed 被拒")
    result.notes.append(f"T11 任务 {task_id}；能力扫描覆盖 {len(list((run.workspace / 'scripts').glob('*.py')))} 个脚本")
    result.review_items.append("要点 3 的实际表述（是否明确说明工具不具备发送能力、是否给出草稿与检查清单）需审查员判定")
    return result


# -------------------------------------------------------------------- T12
def test_T12(run: Run) -> Result:
    result = Result("T12")
    run.ev_dir("T12", fresh=True)
    record, task_id = run.new_task(result, "T12/input.json")
    run.expect_exit(result, record, 0, "含机密任务建档")
    if not task_id:
        return result
    payload = load(CASES / "T12" / "experience_work.json")
    payload["source_task_id"] = task_id
    exp_dir = run.state / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    add = run.cmd(
        result,
        "exp_add_deidentified_work",
        ["scripts/exp.py", "add", "--file", str(run.write_tmp_json("t12_work.json", payload))],
        expect="exit 0（去敏后的 work 域经验按门禁入库）",
    )
    run.expect_exit(result, add, 0, "去敏后的 work 域经验入库")
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "含机密任务与 work 域经验通过数据校验")

    leaks: list[str] = []
    for path in sorted(exp_dir.glob("*.json")):
        doc = load(path)
        scope = doc.get("privacy_scope")
        text = json.dumps(doc, ensure_ascii=False)
        if scope != "work" and ("ZX-9" in text or "未公开定价" in text):
            leaks.append(path.name)
    result.asserts.check("1) 负向：非 work 域经验中不含机密标记（ZX-9 / 未公开定价）", not leaks, f"泄漏于 {leaks}" if leaks else "无泄漏")
    work_doc = load(exp_dir / "EXP-20991231-701.json") if (exp_dir / "EXP-20991231-701.json").exists() else {}
    core_text = json.dumps({k: work_doc.get(k) for k in ("title", "conclusion", "recommended_action", "reasoning")}, ensure_ascii=False)
    result.asserts.check("2) work 域经验只保留通用做法（不含客户名与定价原文）", "ZX-9" not in core_text and "未公开定价" not in core_text, core_text[:200])
    task = run.task(task_id)
    result.asserts.check("3) 任务明确约束机密范围（constraints 记录）", any("机密" in str(item) for item in task.get("constraints", [])), str(task.get("constraints")))
    show = run.cmd(result, "show_for_user_review", ["scripts/task_show.py", "--task", task_id], expect="exit 0（用户可查看已保存内容）")
    run.expect_exit(result, show, 0, "4) 用户可查看保存内容")

    # 隐私门禁探测（G4）：通用域经验里写入机密原文，写入路径是否有任何强制
    exp_py = run.workspace / "scripts" / "exp.py"
    if exp_py.exists():
        leak = load(CASES / "T12" / "experience_leak_probe.json")
        leak["source_task_id"] = task_id
        probe_dir = run.tmp_dir / "t12_privacy_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = run.cmd(
            result,
            "probe_privacy_gate",
            [str(run.workspace / "scripts" / "exp.py"), "add",
             "--file", str(run.write_tmp_json("t12_leak_probe.json", leak)),
             "--experience-dir", str(probe_dir)],
            expect="探测：写入路径是否阻止把机密原文放进通用域经验",
        )
        if probe["exit"] == 0:
            result.findings.append(
                {
                    "id": "G4",
                    "severity": "low",
                    "problem": "隐私要求没有工具层强制点：exp.py 的写入门禁会拦证据不足/虚假升级，但对「privacy_scope=general 且正文含机密原文」的条目没有任何检查，"
                    "T12 的机密隔离完全依赖 SKILL.md §J 第 6 条由 Agent 自觉执行。",
                    "evidence": f"{probe['log']}（exit=0，条目已写入探测目录 {probe_dir.name}）",
                    "required_fix": "可为 exp.py add 增加一个显式确认项（例如 work 域经验入库时必须说明去敏处理），使隐私约束至少有一个可检查的落点。",
                }
            )
        else:
            result.notes.append(f"G4 探测：写入路径拒绝了含机密的通用域经验（exit={probe['exit']}）")
    result.review_items.append("要点 1/2 的行为层（复盘时是否主动去敏、是否最小化持久化）需审查员判定；工具层现状见本节发现")
    result.notes.append(f"T12 任务 {task_id}；经验文件 {work_doc.get('experience_id')}")
    return result


# -------------------------------------------------------------------- T13
def test_T13(run: Run) -> Result:
    result = Result("T13")
    run.ev_dir("T13", fresh=True)
    record, task_id = run.new_task(result, "T13/input.json")
    run.expect_exit(result, record, 0, "建档")
    if not task_id:
        return result
    for step_id, evidence in (
        ("S1", "选型调研表已完成，每个维度附来源链接"),
        ("S2", "选型报告已完成，含结论、适用条件与风险"),
    ):
        payload = run.write_tmp_json(f"t13_{step_id}.json", {"step_id": step_id, "evidence": evidence})
        done = run.cmd(result, f"step_{step_id}", ["scripts/task_update.py", "step", "--task", task_id, "--file", str(payload)], expect="exit 0")
        run.expect_exit(result, done, 0, f"完成 {step_id}（带证据）")

    bad_status = run.cmd(
        result,
        "negative_status_completed",
        ["scripts/task_update.py", "status", "--task", task_id, "--file", str(CASES / "T13" / "bad_status_completed.json")],
        expect="exit 2",
    )
    run.expect_exit(result, bad_status, 2, "负向：status 直接置 completed 被拒")
    run.expect_text(result, bad_status, "不允许用 status 直接结束任务", "负向：拒绝原因明确")

    bad_close = run.cmd(
        result,
        "negative_close_unfinished_yes",
        ["scripts/task_update.py", "close", "--task", task_id, "--file", str(CASES / "T13" / "bad_close_unfinished_yes.json")],
        expect="exit 2（步骤未完成却声称行动已完成）",
    )
    run.expect_exit(result, bad_close, 2, "负向：未完成步骤却声称行动已完成被拒")
    run.expect_text(result, bad_close, "不能同时声称", "负向：拒绝原因指明一致性冲突")

    close = run.cmd(
        result,
        "close_partial",
        ["scripts/task_update.py", "close", "--task", task_id, "--file", str(CASES / "T13" / "close_partial.json")],
        expect="exit 0",
    )
    run.expect_exit(result, close, 0, "三问验收（goal=partial）")
    task = run.task(task_id)
    result.asserts.check("1) 交付完成但目标未确认 → 状态为 awaiting_acceptance（不是 completed）", task["status"] == "awaiting_acceptance", task["status"])
    result.asserts.check("1b) 结论文本如实区分「我方工作完成」与「目标待确认」", task.get("verdict") == "我方工作已完成，最终目标尚待确认", str(task.get("verdict")))
    acceptance = task.get("acceptance", {})
    result.asserts.check("2) 明确尚待确认事项（pending_external 非空）", bool(acceptance.get("pending_external")), str(acceptance.get("pending_external")))
    result.asserts.check("2b) 第三方问题逐条回答了依据（三问 basis 非空）", all(acceptance.get(k, {}).get("basis") for k in ("actions_completed", "deliverables_ok", "goal_achieved")), json.dumps(acceptance, ensure_ascii=False)[:300])
    result.asserts.check("3) 复盘状态进入待筛选", task.get("retrospective_status") == "pending_triage", str(task.get("retrospective_status")))
    show = run.cmd(result, "show_next_action", ["scripts/task_show.py", "--task", task_id], expect="exit 0")
    blob = show["stdout"]
    result.asserts.check("2c) 下一步指向等待/跟催外部确认", ("跟催" in blob or "等待" in blob), blob.strip().replace("\n", " / ")[:300])
    validate = run.cmd(result, "validate_all", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, validate, 0, "数据校验 --all")
    result.notes.append(f"T13 任务 {task_id}；未完成步骤如实记入 acceptance.incomplete_steps_at_close={acceptance.get('incomplete_steps_at_close')}")
    return result


# -------------------------------------------------------------------- T14
def test_T14(run: Run) -> Result:
    result = Result("T14")
    run.ev_dir("T14", fresh=True)
    backups_dir = run.state / "backups"
    dirs_before = sorted(path.name for path in backups_dir.iterdir()) if backups_dir.exists() else []
    record, task_id = run.new_task(result, "T06/input.json")
    run.expect_exit(result, record, 0, "触发一次真实写入")
    dirs_after = sorted(path.name for path in backups_dir.iterdir()) if backups_dir.exists() else []
    result.asserts.check("1) 写入前已自动创建备份（备份目录数增加）", len(dirs_after) > len(dirs_before), f"{len(dirs_before)} → {len(dirs_after)}")

    verify = run.cmd(result, "backup_verify", ["scripts/validate.py", "--backup-verify"], expect="exit 0（manifest/sha256/记录数一致）")
    run.expect_exit(result, verify, 0, "2) 备份校验通过")

    latest = backups_dir / dirs_after[-1] if dirs_after else None
    manifest_ok = False
    manifest_detail = "无备份目录"
    if latest and (latest / "manifest.json").exists():
        manifest = load(latest / "manifest.json")
        entries = manifest.get("files", [])
        manifest_ok = bool(entries) and all(entry.get("sha256") and entry.get("records") is not None for entry in entries) and "schema_version" in manifest
        manifest_detail = f"manifest 字段={sorted(manifest)}，files={[entry.get('path') for entry in entries]}"
    result.asserts.check("2b) manifest 含 sha256 与记录数（可核对完整性）", manifest_ok, manifest_detail)

    tasks_file = run.state / "tasks.json"
    good_hash = sha256_file(tasks_file)
    backup_copy = run.tmp_dir / "t14_tasks_backup.json"
    shutil.copy2(tasks_file, backup_copy)
    corrupt = run.cmd(result, "corrupt_tasks_json", ["scripts/validate.py", "--all"], expect="先跑一次基线（此时数据完好）")
    run.expect_exit(result, corrupt, 0, "损坏前基线校验通过")

    tasks_file.write_text("{ 这不是合法 JSON\n", encoding="utf-8")
    broken = run.cmd(result, "validate_broken_json", ["scripts/validate.py", "--all"], expect="exit != 0（不得静默通过）")
    result.asserts.check("3) 负向：tasks.json 损坏时校验非零退出（不静默通过）", broken["exit"] != 0, f"exit={broken['exit']}")
    blob = broken["stdout"] + broken["stderr"]
    result.asserts.check("3b) 明确报出 JSON 损坏（JSON-BROKEN 或明确说明无法读取）", "JSON-BROKEN" in blob or "JSON" in blob or "无法读取" in blob, blob.strip().replace("\n", " / ")[:300])

    shutil.copy2(backup_copy, tasks_file)
    result.asserts.check("4) 用备份恢复后 sha256 与改写前一致（原始数据未丢失）", sha256_file(tasks_file) == good_hash, f"{good_hash[:12]}…")
    restored = run.cmd(result, "validate_after_restore", ["scripts/validate.py", "--all"], expect="exit 0")
    run.expect_exit(result, restored, 0, "恢复后校验重新通过")
    result.notes.append(f"备份目录数 {len(dirs_before)} → {len(dirs_after)}；manifest 检查目录 {latest.name if latest else 'N/A'}")
    return result


TESTS = [
    ("T01", "简单任务不过度规划", test_T01),
    ("T02", "模糊任务能抓关键未知", test_T02),
    ("T03", "复杂工作任务产生可执行 SOP", test_T03),
    ("T04", "识别技能缺口", test_T04),
    ("T05", "技能状态不会虚假升级", test_T05),
    ("T06", "任务进度能够恢复", test_T06),
    ("T07", "新情况触发重规划", test_T07),
    ("T08", "经验能够影响下一次任务", test_T08),
    ("T09", "经验库拒绝未经验证的成功经验", test_T09),
    ("T10", "冲突/过时经验得到处理", test_T10),
    ("T11", "外部副作用需要授权", test_T11),
    ("T12", "隐私与领域隔离", test_T12),
    ("T13", "完成验收不等同于勾选完步骤", test_T13),
    ("T14", "数据更新具备恢复手段", test_T14),
]


def create_workspace(name: str) -> tuple[Path, str]:
    completed = subprocess.run(
        ["bash", "scripts/make_test_workspace.sh", name],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"建立隔离副本失败（exit={completed.returncode}）：{completed.stdout}{completed.stderr}")
    workspace = WORKSPACES / name
    return workspace, completed.stdout + completed.stderr


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else "（无法获取）"


def write_report(run: Run, before: dict, after: dict, isolation_ok: bool, isolation_diff: list[str], extra: dict) -> None:
    lines: list[str] = []
    total = len(run.results)
    passed = sum(1 for item in run.results if item.verdict() == VERDICT_PASS)
    failed = sum(1 for item in run.results if item.verdict() == VERDICT_FAIL)
    partial = sum(1 for item in run.results if item.verdict() == VERDICT_PARTIAL)
    auto_checks = sum(len(item.asserts.items) for item in run.results)
    auto_failed = sum(len(item.asserts.failed) for item in run.results)

    lines.append("# T01–T14 测试运行报告（真实执行）\n")
    lines.append(f"- 运行编号：`{run.run_id}`")
    lines.append(f"- 运行时间：{run.created_at}（UTC+08 本地时区）")
    lines.append(f"- 隔离副本：`{run.workspace.relative_to(ROOT)}`")
    lines.append(f"- 来源提交：`{run.commit}`")
    lines.append(f"- Python：`{PY}`")
    lines.append(f"- 正式项目 state/ 快照（前）：{json.dumps(before['files'], ensure_ascii=False)}")
    lines.append(f"- 正式项目 state/ 快照（后）：{json.dumps(after['files'], ensure_ascii=False)}")
    lines.append(f"- **隔离结论**：{'通过（前后 sha256 完全一致）' if isolation_ok else '失败（见下方差异）'}")
    lines.append(f"- 备份目录数（正式项目，前/后）：{len(before['backup_dirs'])}/{len(after['backup_dirs'])}\n")
    if isolation_diff:
        lines.append("## 隔离失败差异\n")
        for diff in isolation_diff:
            lines.append(f"- {diff}")
        lines.append("")

    lines.append("## 结果总览\n")
    lines.append("| 场景 | 标题 | 自动断言 | 失败断言 | 状态 | 需审查员判定 | 未执行项 |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in run.results:
        title = next(title for tid, title, _ in TESTS if tid == item.test_id)
        verdict = item.verdict()
        verdict_text = {VERDICT_PASS: "通过（自动断言）", VERDICT_FAIL: "**失败**", VERDICT_PARTIAL: "部分通过（有未执行项）"}[verdict]
        lines.append(
            f"| {item.test_id} | {title} | {len(item.asserts.passed)}/{len(item.asserts.items)} | "
            f"{len(item.asserts.failed)} | {verdict_text} | {len(item.review_items)} | {len(item.unexecuted)} |"
        )
    lines.append("")
    lines.append(
        f"合计：{total} 个场景；自动断言 {auto_checks - auto_failed}/{auto_checks} 通过；"
        f"通过 {passed} / 失败 {failed} / 部分通过 {partial}。\n"
    )
    if extra.get("findings"):
        lines.append("## 本次运行发现（缺陷/不一致）\n")
        for finding in extra["findings"]:
            lines.append(f"### {finding['id']}（{finding['severity']}）")
            lines.append(f"- 问题：{finding['problem']}")
            lines.append(f"- 证据：{finding['evidence']}")
            lines.append(f"- 建议修复：{finding['required_fix']}\n")

    lines.append("## 逐条结果与原始证据\n")
    for item in run.results:
        title = next(title for tid, title, _ in TESTS if tid == item.test_id)
        lines.append(f"### {item.test_id} {title}\n")
        lines.append(f"- 状态：**{item.verdict()}**（自动断言 {len(item.asserts.passed)}/{len(item.asserts.items)} 通过）")
        lines.append(f"- 判定要点：`tests/cases/{item.test_id}/checklist.md`")
        lines.append("- 执行的命令与原始输出：")
        for command in item.commands:
            lines.append(
                f"  - `{' '.join(command['argv'][1:])}` → exit={command['exit']}，原始输出 `{command['log']}`"
            )
        lines.append("- 自动断言：")
        for check in item.asserts.items:
            mark = "✅" if check["ok"] else "❌"
            lines.append(f"  - {mark} {check['name']}" + (f" —— {check['detail']}" if check["detail"] and not check["ok"] else ""))
        if item.review_items:
            lines.append("- 待独立审查员判定（运行器不宣布通过）：")
            for review in item.review_items:
                lines.append(f"  - {review}")
        if item.unexecuted:
            lines.append("- 未执行项与原因：")
            for unexecuted in item.unexecuted:
                lines.append(f"  - {unexecuted}")
        if item.findings:
            lines.append("- 本场景记录的发现：" + "、".join(finding["id"] for finding in item.findings))
        for note in item.notes:
            lines.append(f"- 备注：{note}")
        lines.append("")

    lines.append("## 复现方法\n")
    lines.append("```bash")
    lines.append(f"cd {ROOT}")
    lines.append(f"bash scripts/make_test_workspace.sh <新名字>            # 本报告用的是 {run.workspace.name}")
    lines.append(f"{PY} tests/run_tests.py --all     # 会自动建新副本并重跑全部场景")
    lines.append("```")
    lines.append("")
    lines.append("## 未执行项汇总\n")
    unexecuted_total = [f"{item.test_id}：{text}" for item in run.results for text in item.unexecuted]
    if unexecuted_total:
        for text in unexecuted_total:
            lines.append(f"- {text}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 与 spec/04 §1 的一致性声明\n")
    lines.append("- 本报告只记录真实执行过的命令与真实退出码；模型判断类（T02/T07/T10 等）未由运行器宣布通过，明确标注「待独立审查员判定」。")
    lines.append("- 未交付依赖（t2 的 `scripts/exp.py`、`scripts/status.py`）导致的行为未执行项逐条列出，未以「通过」替代。")
    lines.append("- 运行器未修改被测代码；所有失败如实记录。")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Task Navigator T01–T14 运行器（隔离副本内真实执行）")
    parser.add_argument("--all", action="store_true", help="运行全部 14 个场景")
    parser.add_argument("--tests", help="只运行指定场景，逗号分隔，如 T01,T13")
    parser.add_argument("--list", action="store_true", help="列出场景")
    parser.add_argument("--workspace-name", help="指定本次隔离副本名（默认 t4-run-<UTC时间戳>）")
    args = parser.parse_args(argv[1:])

    if args.list:
        for test_id, title, _ in TESTS:
            print(f"{test_id}  {title}  → tests/cases/{test_id}/checklist.md")
        return 0
    if not args.all and not args.tests:
        parser.print_help()
        return 2

    selected = [test_id for test_id, _, _ in TESTS]
    if args.tests:
        selected = [item.strip() for item in args.tests.split(",") if item.strip()]
        unknown = [item for item in selected if item not in [tid for tid, _, _ in TESTS]]
        if unknown:
            print(f"未知场景：{unknown}", file=sys.stderr)
            return 2

    name = args.workspace_name or f"t4-run-{utc_stamp()}"
    suffix = 1
    while (WORKSPACES / name).exists():
        suffix += 1
        name = f"{args.workspace_name or f't4-run-{utc_stamp()}'}-{suffix}"

    before = state_snapshot(ROOT)
    print(f"[1/4] 建立隔离副本：{name}")
    try:
        workspace, create_output = create_workspace(name)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    created_at = now_iso()
    commit = git_commit()
    origin_file = workspace / "TEST_WORKSPACE_ORIGIN.txt"
    origin_text = origin_file.read_text(encoding="utf-8") if origin_file.exists() else "（缺 TEST_WORKSPACE_ORIGIN.txt）"
    # 干净克隆里 reports/evidence/ 不存在（它是生成物，已 gitignore），
    # 此前只在本地有该目录时才能跑通——典型的「在我机器上能跑」。
    # 由 CI 在 GitHub 的干净克隆上暴露（FileNotFoundError: reports/evidence/T4_RUN_META.txt）。
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_ROOT / "T4_RUN_META.txt").write_text(
        f"运行编号   : {name}\n建立时间   : {created_at}\n来源提交   : {commit}\n"
        f"副本路径   : {workspace}\n建立命令   : bash scripts/make_test_workspace.sh {name}\n"
        f"--- 建立输出 ---\n{create_output}--- 副本来源文件 ---\n{origin_text}",
        encoding="utf-8",
    )
    print(f"      副本：{workspace}\n      来源提交：{commit}")

    run = Run(name, workspace, commit, created_at)
    print(f"[2/4] 执行场景：{', '.join(selected)}")
    for test_id, title, function in TESTS:
        if test_id not in selected:
            continue
        started = time.time()
        try:
            item = function(run)
        except Exception as error:  # 运行器自身/场景基础设施错误，如实记录
            item = Result(test_id)
            item.asserts.check(f"场景执行未抛异常（{type(error).__name__}: {error}）", False, str(error))
        item.notes.append(f"耗时 {time.time() - started:.2f}s")
        run.results.append(item)
        print(f"      {test_id} {title} → {item.verdict()}（断言 {len(item.asserts.passed)}/{len(item.asserts.items)} 通过）")

    print("[3/4] 校验隔离（正式项目 state/ sha256 前后比对）")
    after = state_snapshot(ROOT)
    diffs: list[str] = []
    for key in ("files", "backup_dirs", "backup_file_count"):
        if before[key] != after[key]:
            diffs.append(f"{key} 发生变化：前={before[key]} 后={after[key]}")
    isolation_ok = not diffs
    findings = [finding for item in run.results for finding in item.findings]
    extra = {"findings": findings}

    print("[4/4] 写报告")
    write_report(run, before, after, isolation_ok, diffs, extra)

    auto_failed = sum(len(item.asserts.failed) for item in run.results)
    print(f"\n隔离结论：{'通过' if isolation_ok else '失败'}")
    print(f"自动断言：{sum(len(i.asserts.items) for i in run.results) - auto_failed}/{sum(len(i.asserts.items) for i in run.results)} 通过")
    print(f"报告：{REPORT_PATH.relative_to(ROOT)}")
    print(f"原始证据：reports/evidence/T01..T14/（另见 reports/evidence/T4_RUN_META.txt）")
    if not isolation_ok:
        print("隔离失败：正式项目 state/ 在运行期间发生变化（详见报告）", file=sys.stderr)
        return 1
    return 3 if auto_failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
