#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：真实任务/经验内容是否会被 git 带上去——按仓库类型分别断言。

## 两种模式

**公开仓库（默认）**：真实数据必须被 `.gitignore` 排除。这些**派生物**曾经漏掉过：

- `state/experience_index.md`（经验索引：标题/结论/适用条件）
- `STATUS.md`（全部任务的状态总览）
- `decisions.md`（决策记录）

它们由脚本生成、内容直接来自用户数据，`git add -A && push` 会把个人内容推上去。
v0.1.2 补进 `.gitignore`；本测试守住这条线。

**私有工作仓库（方案 A，存在 `PRIVATE-WORKSPACE.md` 标记）**：数据**本来就该跟踪**
（两台电脑共用经验库），此时改为断言：

- 任务/经验/教训/技能等数据路径**可以被 git 跟踪**（否则新写的经验永远 push 不上去）；
- `state/backups/`、`outputs/`、`reports/`、`STATUS.md`、`tests/tmp/` **仍然被忽略**
  （可重建/生成物不该进历史）。

标记文件只存在于私有副本里；公开仓库没有它，行为不受影响。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRIVATE_MARKER = ROOT / "PRIVATE-WORKSPACE.md"

# 公开仓库模式：必须被忽略（真实数据与含真实内容的派生文件）
SENSITIVE = [
    "state/tasks.json",
    "state/tasks.jsonl",
    "state/experience/EXP-20260101-001.json",
    "state/lessons/20260101-001.json",
    "state/backups/20260101T000000Z/manifest.json",
    "state/experience_index.md",
    "state/flowcharts/TN-20260101-001.json",
    "state/coverage_checks/TN-20260101-001.json",
    "state/self_reviews/TN-20260101-001.json",
    "STATUS.md",
    "decisions.md",
    "outputs/deliverables/TN-20260101-001/plan.md",
    "reports/evidence/T01/01_run.txt",
    "reports/TEST_RUN_REPORT.md",
]

# 私有工作仓库模式：这些数据必须**可跟踪**（同步才有意义）
PRIVATE_TRACKED = [
    "state/tasks.json",
    "state/tasks.jsonl",
    "state/experience/EXP-20260101-001.json",
    "state/lessons/20260101-001.json",
    "state/flowcharts/TN-20260101-001.json",
    "state/coverage_checks/TN-20260101-001.json",
    "state/self_reviews/TN-20260101-001.json",
    "state/experience_index.md",
    "decisions.md",
]

# 私有工作仓库模式：这些仍然必须被忽略（生成物/备份/临时）
PRIVATE_STILL_IGNORED = [
    "state/backups/20260101T000000Z/manifest.json",
    "outputs/deliverables/TN-20260101-001/plan.md",
    "reports/evidence/T01/01_run.txt",
    "reports/TEST_RUN_REPORT.md",
    "STATUS.md",
    "tests/tmp/x",
]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def ignored_paths(paths: list[str]) -> set[str] | None:
    """返回被忽略的路径集合；git 不可用时返回 None。"""
    # 路径全用 ASCII：git check-ignore 默认会把含中文的输出加引号，不好直接比对
    probe = git("check-ignore", "--", *paths)
    if probe.returncode not in (0, 1):
        return None
    return {line.strip() for line in probe.stdout.splitlines() if line.strip()}


def check_public(failures: list[str]) -> None:
    ignored = ignored_paths(SENSITIVE)
    if ignored is None:
        print("  ⚠️ 无法运行 git check-ignore（不是 git 仓库？）：跳过，不判失败")
        return
    for path in SENSITIVE:
        ok = path in ignored
        print(f"  {'✅' if ok else '❌'} 已忽略：{path}")
        if not ok:
            failures.append(path)

    # 双保险：被跟踪文件里不得出现这些路径（忽略规则对已被跟踪的文件无效）
    tracked = git("ls-files")
    tracked_paths = (
        {line.strip() for line in tracked.stdout.splitlines() if line.strip()}
        if tracked.returncode == 0
        else set()
    )
    leaked = [path for path in SENSITIVE if path in tracked_paths]
    print(f"  {'✅' if not leaked else '❌'} 敏感路径没有被纳入 git 跟踪")
    if leaked:
        failures.extend(f"已跟踪:{path}" for path in leaked)


def check_private(failures: list[str]) -> None:
    print("  （检测到 PRIVATE-WORKSPACE.md：按私有工作仓库模式检查）")
    ignored_tracked = ignored_paths(PRIVATE_TRACKED)
    if ignored_tracked is None:
        print("  ⚠️ 无法运行 git check-ignore（不是 git 仓库？）：跳过，不判失败")
        return
    for path in PRIVATE_TRACKED:
        ok = path not in ignored_tracked
        print(f"  {'✅' if ok else '❌'} 可被跟踪（数据同步）：{path}")
        if not ok:
            failures.append(f"被忽略:{path}")

    still = ignored_paths(PRIVATE_STILL_IGNORED)
    for path in PRIVATE_STILL_IGNORED:
        ok = path in (still or set())
        print(f"  {'✅' if ok else '❌'} 仍被忽略（生成物）：{path}")
        if not ok:
            failures.append(f"未忽略:{path}")


def main() -> int:
    failures: list[str] = []
    if PRIVATE_MARKER.is_file():
        check_private(failures)
    else:
        check_public(failures)

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
