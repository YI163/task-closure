#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行为测试：证明 SKILL.md 里那些「机械约束」真的会在运行时拒绝违规输入。

## 为什么需要这个文件

审查报告 P1-4：`audit.py` 原来的判据是「源码里出现某个字符串」，然后把规则
标成「机械」。字符串出现在注释、错误提示、甚至没被调用的函数里，也能通过——
这会给出过强的可靠性结论。

本文件为每条可机械检查的规则准备一个**可复跑的行为探针**：在一个临时副本里
真实执行脚本，断言违规输入被拒绝、合法输入被放行。audit.py 只把这些探针
跑通的结果记为「行为测试证实」。

用法：
    python tests/unit/test_skill_guards.py                 # 跑全部探针（人读）
    python tests/unit/test_skill_guards.py --json out.json # 供 audit.py 读取结果

退出码：0 = 全部探针通过；1 = 有探针失败。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable

IGNORE = shutil.ignore_patterns(
    ".git", "outputs", "reports", "__pycache__", "*.pyc", ".pytest_cache"
)

TASK_ID_RE = re.compile(r"已建立任务\s+(TN-\d{8}-\d{3})")


def run(args, cwd, env_extra=None, timeout=180):
    env = os.environ.copy()
    env.pop("TASK_CLOSURE_HOME", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [PY, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def prepare_copy(base: pathlib.Path) -> pathlib.Path:
    dest = base / "guard-copy"
    shutil.copytree(ROOT, dest, ignore=IGNORE)
    state = dest / "state"
    keep = {"schema.json", "user_skills.json"}
    for child in state.iterdir():
        if child.name in keep:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    return dest


def new_task(repo: pathlib.Path, fixture: str) -> str:
    proc = run(["nav.py", "new", "--input", f"tests/cases/{fixture}"], repo)
    match = TASK_ID_RE.search(proc.stdout)
    if not match:
        raise RuntimeError(f"建档失败（{fixture}）：{proc.stdout}{proc.stderr}")
    return match.group(1)


def deliverables_dir(repo: pathlib.Path, task_id: str) -> pathlib.Path:
    path = repo / "outputs" / "deliverables" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_deliverables(repo: pathlib.Path, task_id: str) -> pathlib.Path:
    path = repo / "outputs" / "deliverables" / task_id
    if path.is_dir():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def deliver_check(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    desktop.mkdir(parents=True, exist_ok=True)
    return run(
        ["scripts/deliver.py", "check", "--task", task_id],
        repo,
        {"NAV_DELIVERY_DIR": str(desktop)},
    )


def blob(proc) -> str:
    return proc.stdout + proc.stderr


# ---------------------------------------------------------------- 探针


def probe_task_show(repo: pathlib.Path, task_id: str):
    proc = run(["scripts/task_show.py", "--task", task_id], repo)
    ok = proc.returncode == 0 and "先读状态再开口" in blob(proc) and task_id in blob(proc)
    return ok, "task_show 输出包含开工必读与任务 ID" if ok else blob(proc)[:200]


def probe_action_list(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    d = clear_deliverables(repo, task_id)
    (d / "说明.md").write_text("这是交付物正文。\n", encoding="utf-8")
    missing = deliver_check(repo, task_id, desktop)
    need_missing = "缺少「行动清单」文件" in blob(missing) and missing.returncode != 0

    (d / "0-从这里开始（行动清单）.md").write_text(
        "□ 第一步：做什么\n□ 第二步：做完回来说一声\n", encoding="utf-8"
    )
    present = deliver_check(repo, task_id, desktop)
    need_present = "缺少「行动清单」文件" not in blob(present)
    ok = need_missing and need_present
    return ok, "缺失时拒绝、补齐后不再报缺失" if ok else blob(missing)[-300:]


def probe_flowchart(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    d = clear_deliverables(repo, task_id)
    (d / "流程.md").write_text(
        "┌──────┬──────┐\n│ 步骤 │ 说明 │\n└──────┴──────┘\n", encoding="utf-8"
    )
    proc = deliver_check(repo, task_id, desktop)
    text = blob(proc)
    need_missing = "缺少流程图（渲染版）" in text
    need_ascii = "手写的 ASCII 框图" in text

    (d / "流程总览.pdf").write_bytes(b"%PDF-1.4 sample")
    after = deliver_check(repo, task_id, desktop)
    need_render_ok = "缺少流程图（渲染版）" not in blob(after)
    ok = need_missing and need_ascii and need_render_ok
    return ok, "缺渲染图被拒、ASCII 被拒、补渲染图后放行" if ok else blob(after)[-300:]


def probe_naming(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    clear_deliverables(repo, task_id)
    group = desktop / task_id
    group.mkdir(parents=True, exist_ok=True)
    (group / f"{task_id}-这个文件名带任务ID前缀.html").write_text("<html></html>", encoding="utf-8")
    proc = deliver_check(repo, task_id, desktop)
    ok = "桌面文件名不合规" in blob(proc) and proc.returncode != 0
    return ok, "任务 ID 前缀命名被拒" if ok else blob(proc)[-300:]


def probe_commitments(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    d = clear_deliverables(repo, task_id)
    (d / "建议.md").write_text("建议联系供应商确认报价。\n", encoding="utf-8")
    proc = deliver_check(repo, task_id, desktop)
    ok = "发现 1 处「承诺了动作」的句子" in blob(proc)
    return ok, "承诺句被扫描并计数" if ok else blob(proc)[-300:]


def probe_merge_marker(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    d = clear_deliverables(repo, task_id)
    (d / "合并本.md").write_text("<!-- GENERATED-MERGE-BUNDLE: 样本 -->\n正文\n", encoding="utf-8")
    proc = deliver_check(repo, task_id, desktop)
    ok = "带有「合并本」标记" in blob(proc) and proc.returncode != 0
    return ok, "合并本标记被拒" if ok else blob(proc)[-300:]


def probe_judgment(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    clear_deliverables(repo, task_id)
    first = deliver_check(repo, task_id, desktop)
    need_unanswered = "条判断检查未回答" in blob(first) and "[constraints_checked]" in blob(first)

    sys.path.insert(0, str(repo / "scripts"))
    try:
        import deliver as deliver_module  # noqa: PLC0415

        keys = [key for key, _ in deliver_module.JUDGMENT_CHECKS]
    finally:
        sys.path.pop(0)
    answers = {key: {"answer": "yes", "note": "样本回答"} for key in keys}
    answers_path = repo / "tests" / "tmp" / "seal_answers.json"
    answers_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    sealed = run(["scripts/deliver.py", "seal", "--task", task_id, "--file", str(answers_path)], repo)

    second = deliver_check(repo, task_id, desktop)
    need_sealed = (
        sealed.returncode == 0
        and f"已记录 {len(keys)} 条判断检查" in blob(sealed)
        and "判断检查全部已回答" in blob(second)
    )
    ok = need_unanswered and need_sealed
    return ok, "未回答时阻断、回答落盘后放行" if ok else blob(second)[-300:]


def _desktop_conflict_lines(text: str) -> int:
    """数「桌面冲突」问题行。

    不能直接数「种格式」——判断检查的问题文案里也含这几个字
    （「同一内容少几种格式」），会把计数虚高。
    """
    return sum(
        1 for line in text.splitlines()
        if line.strip().startswith("· 桌面") and "种格式" in line
    )


def probe_deliver_dedup(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    """P2-5：桌面「同一内容多格式」问题只能报一次（deliver.py 曾有两段重复扫描）。"""
    clear_deliverables(repo, task_id)
    group = desktop / task_id
    group.mkdir(parents=True, exist_ok=True)
    (group / "重叠内容.html").write_text("<html></html>", encoding="utf-8")
    clean = deliver_check(repo, task_id, desktop)
    clean_hits = _desktop_conflict_lines(blob(clean))

    (group / "重叠内容.pdf").write_bytes(b"%PDF-1.4 sample")
    conflicted = deliver_check(repo, task_id, desktop)
    conflict_hits = _desktop_conflict_lines(blob(conflicted))
    ok = clean_hits == 0 and conflict_hits == 1
    return ok, f"无冲突 {clean_hits} 次、有冲突 {conflict_hits} 次（应为 0 / 1）"


def probe_close_gate(repo: pathlib.Path, task_id: str, desktop: pathlib.Path):
    d = clear_deliverables(repo, task_id)
    (d / "说明.md").write_text("交付物\n", encoding="utf-8")
    payload = {
        "actions_completed": {"verdict": "partial", "basis": "样本：部分完成"},
        "deliverables_ok": {"verdict": "yes", "basis": "样本：已产出"},
        "goal_achieved": {"verdict": "partial", "basis": "样本：待确认"},
    }
    path = repo / "tests" / "tmp" / "close_payload.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = run(["scripts/task_update.py", "close", "--task", task_id, "--file", str(path)], repo)
    ok = proc.returncode == 2 and "没有交付检查记录" in blob(proc)
    return ok, "有交付物却无交付检查时拒绝收尾" if ok else blob(proc)[-300:]


PROBE_ORDER = [
    "task-show-preconditions",
    "deliver-action-list",
    "deliver-flowchart",
    "deliver-naming",
    "deliver-commitments",
    "deliver-merge-marker",
    "deliver-dedup",
    "deliver-judgment",
    "close-gate",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="SKILL 机械约束的行为探针")
    parser.add_argument("--json", type=pathlib.Path, help="把结果写到 JSON（供 audit.py 读取）")
    args = parser.parse_args(argv[1:])

    results: dict[str, dict[str, object]] = {}
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        try:
            repo = prepare_copy(base)
            init = run(["nav.py", "init"], repo)
            if init.returncode != 0:
                raise RuntimeError(f"init 失败：{blob(init)}")
            light = new_task(repo, "T01/input.json")
            standard = new_task(repo, "T02/input.json")
            # close 探针需要「有交付物但没有 delivery_check」的任务；
            # deliver-judgment 探针会给任务写 delivery_check，所以必须用独立任务。
            gate_task = new_task(repo, "T01/input.json")
            desktop = base / "desktop"

            checks = {
                "task-show-preconditions": lambda: probe_task_show(repo, light),
                "deliver-action-list": lambda: probe_action_list(repo, light, desktop),
                "deliver-flowchart": lambda: probe_flowchart(repo, standard, desktop),
                "deliver-naming": lambda: probe_naming(repo, light, desktop),
                "deliver-commitments": lambda: probe_commitments(repo, light, desktop),
                "deliver-merge-marker": lambda: probe_merge_marker(repo, light, desktop),
                "deliver-dedup": lambda: probe_deliver_dedup(repo, light, desktop),
                "deliver-judgment": lambda: probe_judgment(repo, light, desktop),
                "close-gate": lambda: probe_close_gate(repo, gate_task, desktop),
            }
            for key in PROBE_ORDER:
                try:
                    ok, detail = checks[key]()
                except Exception as exc:  # noqa: BLE001 - 探针失败本身就是结果
                    ok, detail = False, f"{type(exc).__name__}: {exc}"
                results[key] = {"ok": bool(ok), "detail": str(detail)[:300]}
        except Exception as exc:  # noqa: BLE001
            for key in PROBE_ORDER:
                results.setdefault(key, {"ok": False, "detail": f"无法建立探针环境：{exc}"})

    for key in PROBE_ORDER:
        item = results[key]
        print(f"  {'✅' if item['ok'] else '❌'} {key}：{item['detail']}")
    failed = [key for key in PROBE_ORDER if not results[key]["ok"]]
    print()
    print("结论：" + ("通过" if not failed else f"失败：{failed}"))

    if args.json:
        args.json.write_text(
            json.dumps({"probes": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    sys.path.insert(0, str(ROOT / "scripts"))
    import console  # noqa: E402

    console.setup()
    sys.exit(main(sys.argv))
