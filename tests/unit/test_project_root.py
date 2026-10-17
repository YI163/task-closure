#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：项目根目录可配置、可跨机器定位，且不会静默使用第二套 state/。

## 防止什么问题

审查报告 P1-2：SKILL.md 里曾把项目根目录与 Python 解释器写死成作者本机路径
（`$HOME/Documents/...`、`$HOME/.dsh/dsh-runtimes/...`）。别人 clone 到别的目录后，
AI 可能对着不存在的路径操作，或者对**错误的仓库**读写。

## 验收方式（就是报告要求的场景）

把仓库复制到一个「路径含中文 + 空格」的位置，在那里跑
`env / init / new / show / validate` 核心流程：

- 必须认到副本自己的根目录与 `state/`；
- 不能写到原仓库；
- `TASK_CLOSURE_HOME` 与实际目录不一致时，nav.py 必须非零退出而不是继续。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable

IGNORE = shutil.ignore_patterns(
    ".git", "outputs", "reports", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"
)


def check(condition: bool, label: str, failures: list[str], detail: str = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


def run(args, cwd, env_extra=None):
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
        timeout=180,
    )


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "（缺）"


def prepare_copy(base: pathlib.Path) -> pathlib.Path:
    """复制仓库到「含中文 + 空格」的目录，并清掉用户数据（只留契约与示例档案）。"""
    dest = base / "含 空格 的目录" / "task-closure 副本"
    shutil.copytree(ROOT, dest, ignore=IGNORE)

    state = dest / "state"
    keep = {"schema.json", "user_skills.json"}
    for child in state.iterdir():
        if child.name in keep:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    # 必须返回**解析后**的路径：GitHub Windows runner 的 TEMP 常是 8.3 短路径
    # （C:\Users\RUNNER~1\...），而 nav.py 打印的是 GetFinalPathNameByHandle 的长路径。
    # 不解析就会出现「输出里明明有路径、断言却匹配不上」的假失败（CI 已实测）。
    return dest.resolve()


def main() -> int:
    failures: list[str] = []
    original_state = ROOT / "state" / "tasks.json"
    original_hash = sha256(original_state)

    with tempfile.TemporaryDirectory() as td:
        dest = prepare_copy(pathlib.Path(td))

        # 1) env：认到副本自己的根目录
        proc = run(["nav.py", "env"], dest)
        out = proc.stdout + proc.stderr
        check(proc.returncode == 0 and str(dest) in out and str(dest / "state") in out,
              "env 认到副本根目录与数据目录（路径含中文+空格）", failures,
              out.strip().replace("\n", " / ")[:160])
        check("经验目录" in out and "教训目录" in out,
              "env 单独报告经验/教训目录（跨机共用经验库时用于确认落点）", failures)

        # 2) init → new → show → validate 全流程可用
        proc = run(["nav.py", "init"], dest)
        check(proc.returncode == 0, "init 在中文+空格路径下成功", failures,
              (proc.stdout + proc.stderr).strip()[:120])

        proc = run(["nav.py", "new", "--input", "tests/cases/T01/input.json"], dest)
        check(proc.returncode == 0, "new 在中文+空格路径下成功", failures,
              (proc.stdout + proc.stderr).strip()[:120])

        proc = run(["nav.py", "show"], dest)
        check(proc.returncode == 0 and "TN-" in proc.stdout,
              "show 读到的是副本里的任务", failures,
              (proc.stdout + proc.stderr).strip()[:120])

        proc = run(["nav.py", "validate"], dest)
        validate_tail = (proc.stdout + proc.stderr).strip().splitlines()[-1] if (proc.stdout + proc.stderr).strip() else ""
        check(proc.returncode == 0 and "通过" in proc.stdout,
              "validate 在副本上通过", failures, validate_tail[:80])

        # 3) 数据确实落在副本，不是原仓库
        tasks_file = dest / "state" / "tasks.json"
        try:
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"]
        except Exception as exc:  # noqa: BLE001 - 测试里只关心是否可用
            tasks = []
            check(False, "副本 state/tasks.json 可读", failures, f"{type(exc).__name__}: {exc}")
        check(len(tasks) == 1, "任务写入副本的 state/（不是原仓库）", failures, f"{len(tasks)} 条")
        check(sha256(original_state) == original_hash,
              "原仓库 state/tasks.json 未被改动", failures)

        # 4) 环境变量不一致：nav.py 必须拒绝
        proc = run(["nav.py", "env"], dest, {"TASK_CLOSURE_HOME": str(ROOT)})
        check(proc.returncode == 5 and "不一致" in (proc.stdout + proc.stderr),
              "TASK_CLOSURE_HOME 不一致时 nav.py 拒绝执行（exit=5）", failures,
              f"exit={proc.returncode}")

        # 5) 环境变量一致：正常
        proc = run(["nav.py", "env"], dest, {"TASK_CLOSURE_HOME": str(dest)})
        check(proc.returncode == 0 and "一致" in proc.stdout,
              "TASK_CLOSURE_HOME 指向当前仓库时放行", failures,
              f"exit={proc.returncode}")

        # 6) 直接调脚本：不能静默，必须打警告
        proc = run(["scripts/task_show.py"], dest, {"TASK_CLOSURE_HOME": str(ROOT)})
        check("警告" in proc.stderr and str(dest) in proc.stderr,
              "直接调脚本时对路径不一致给出可见警告", failures,
              proc.stderr.strip().splitlines()[0][:120] if proc.stderr.strip() else "（无 stderr）")

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
