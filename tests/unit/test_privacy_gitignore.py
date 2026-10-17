#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：任务/经验等真实内容不得被 git 跟踪（推送前不会被带上去）。

## 防止什么问题

用户问过：「我用这个然后 push 了之后，经验会不会直接暴露？」
默认答案是「不会」——但这些**派生物**曾经没被 `.gitignore` 覆盖：

- `state/experience_index.md`（经验索引：标题/结论/适用条件）
- `STATUS.md`（全部任务的状态总览）
- `decisions.md`（决策记录）

它们由脚本生成、内容直接来自用户数据，`git add -A && push` 会把个人内容推上去。
v0.1.2 补进 `.gitignore`；本测试守住这条线。

注：`state/user_skills.json` 是**有意跟踪**的脱敏示例（README 有说明），不在本测试范围。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

# 必须被忽略的路径（真实数据与含真实内容的派生文件）
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


def main() -> int:
    failures: list[str] = []

    # 路径全用 ASCII：git check-ignore 默认会把含中文的输出加引号，不好直接比对
    probe = git("check-ignore", "--", *SENSITIVE)
    if probe.returncode not in (0, 1):
        print("  ⚠️ 无法运行 git check-ignore（不是 git 仓库？）：跳过，不判失败")
        print()
        print("结论：跳过")
        return 0
    ignored = {line.strip() for line in probe.stdout.splitlines() if line.strip()}

    for path in SENSITIVE:
        ok = path in ignored
        print(f"  {'✅' if ok else '❌'} 已忽略：{path}")
        if not ok:
            failures.append(path)

    # 双保险：被跟踪文件里不得出现这些路径（忽略规则对已被跟踪的文件无效）
    tracked = git("ls-files")
    tracked_paths = {line.strip() for line in tracked.stdout.splitlines() if line.strip()} if tracked.returncode == 0 else set()
    leaked = [path for path in SENSITIVE if path in tracked_paths]
    print(f"  {'✅' if not leaked else '❌'} 敏感路径没有被纳入 git 跟踪")
    if leaked:
        failures.extend(f"已跟踪:{path}" for path in leaked)

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
