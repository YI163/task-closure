#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建立隔离的测试副本（跨平台版）。

## 为什么有这一版

原来的 `scripts/make_test_workspace.sh` 依赖 `bash` + `rsync`：
macOS/Linux 是常态，**Windows 上两样都没有**——`bash` 不在 PATH、`rsync` 更是
不存在。于是 `tests/run_tests.py` 在 Windows 上第一行就失败：

    FileNotFoundError: [WinError 2] 系统找不到指定的文件。

（Git for Windows 自带 bash，但默认不进 PATH；不能要求用户去配。）

本文件用标准库重写同一套逻辑，三平台行为一致：

- 只读取正式项目，唯一写入目标是 `outputs/test-workspaces/<副本名>/`；
- 目标已存在时**拒绝覆盖**（退出码 2），保证每次验证都是干净副本；
- 排除项与 rsync 版本一致：`state/backups/`、`.git/`、`outputs/`、
  `__pycache__/`、`*.pyc`；
- 交接给旧用法：`make_test_workspace.sh` 现在是本文件的薄包装。

用法：
    python scripts/make_test_workspace.py <副本名>

退出码：0 成功；1 参数错误；2 目标已存在（不覆盖已有副本）；3 缺少必要文件
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_ROOT = PROJECT_ROOT / "outputs" / "test-workspaces"

# 与旧 rsync 版本保持一致：这些目录/文件不进副本
EXCLUDE_RELATIVE = {
    "state/backups",
    "tests/tmp",
    ".git",
    "outputs",
    "__pycache__",
}

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
REQUIRED_FILES = (
    "state/schema.json",
    "scripts/store.py",
    "skills/task-navigator/SKILL.md",
)


def _ignore(source_dir: str, names: list[str]) -> set[str]:
    """告诉 copytree 哪些名字跳过（相对路径比较，避免误伤同名子目录）。"""
    base = Path(source_dir)
    ignored: set[str] = set()
    for name in names:
        full = base / name
        try:
            relative = full.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            relative = ""
        if (
            relative in EXCLUDE_RELATIVE
            or name == "__pycache__"
            or name.endswith(".pyc")
        ):
            ignored.add(name)
    return ignored


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return "（非 git 仓库或无提交）"
    if completed.returncode != 0:
        return "（非 git 仓库或无提交）"
    return completed.stdout.strip() or "（非 git 仓库或无提交）"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].strip():
        print("用法：python scripts/make_test_workspace.py <副本名>", file=sys.stderr)
        return 1

    name = argv[1].strip()
    if not NAME_PATTERN.match(name):
        print(f"副本名只能包含字母、数字、点、下划线、连字符：{name}", file=sys.stderr)
        return 1

    dest = DEST_ROOT / name
    if dest.exists():
        print(f"副本已存在，不覆盖（每次验证应建新副本）：{dest}", file=sys.stderr)
        return 2

    for required in REQUIRED_FILES:
        if not (PROJECT_ROOT / required).exists():
            print(f"正式项目缺少必要文件：{required}", file=sys.stderr)
            return 3

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(PROJECT_ROOT, dest, ignore=_ignore)
    except BaseException:
        # 半成品副本比没有更糟：下次运行会因「副本已存在」被拒。
        shutil.rmtree(dest, ignore_errors=True)
        raise

    (dest / "state" / "backups").mkdir(parents=True, exist_ok=True)

    commit = _git_commit()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    origin = (
        "隔离测试副本\n"
        f"副本名        : {name}\n"
        f"建立时间      : {stamp}\n"
        f"来源项目      : {PROJECT_ROOT}\n"
        f"来源提交      : {commit}\n"
        "用途          : T01–T14 真实执行；本副本内的所有改动都不影响正式项目\n"
    )
    (dest / "TEST_WORKSPACE_ORIGIN.txt").write_text(origin, encoding="utf-8", newline="\n")

    print(f"隔离副本已建立：{dest}")
    print(f"来源提交：{commit}")
    print()
    print("下一步：")
    print(f"  cd {dest}")
    print("  然后按 tests/cases/ 里的场景执行；原始输出请写回正式项目的 reports/evidence/")
    return 0


if __name__ == "__main__":
    import console  # noqa: E402  （同目录模块：统一控制台编码）

    console.setup()
    sys.exit(main(sys.argv))
