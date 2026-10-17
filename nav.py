#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task Closure · 统一入口。

## 为什么有这个文件

项目里有 17 个脚本，但**用户真正需要的只有 5 条命令**。
外部审查者的意见：「18 个脚本没有统一入口，用户不知道该从哪开始」。

本文件就是那个入口：`python3 nav.py` 列出能做什么，
`python3 nav.py <命令>` 直接调用，不用记脚本文件名。

## 用法

    python3 nav.py                 # 看能做什么
    python3 nav.py init            # 初始化数据目录
    python3 nav.py show            # 任务总览（每次开工先跑）
    python3 nav.py show --all      # 含已完成
    python3 nav.py new --input x.json
    python3 nav.py test            # 跑全部测试
    python3 nav.py test --quick    # 只跑快的（跳过场景测试）

本文件**只是转发**，不重新实现任何逻辑——所有实际工作仍在 scripts/ 里的对应脚本。
这样「入口」和「实现」不会分叉成两套。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# (命令, 对应脚本, 一句话说明, 是否属于「日常必用」)
COMMANDS = [
    ("init", "scripts/init.py", "初始化数据目录（建空的 state/）", True),
    ("show", "scripts/task_show.py", "任务总览 / 单个任务现场", True),
    ("new", "scripts/task_new.py", "建档（需要 --input 任务.json）", True),
    ("step", "scripts/task_update.py", "更新任务（也可用 evidence/decision/change/close 等子命令）", True),
    ("test", "tests/run_all.py", "跑全部测试", True),
    ("", "", "", False),  # 分隔线
    ("check", "scripts/deliver.py", "交付前检查（不通过不许交付）", False),
    ("flow", "scripts/flowchart.py", "把流程定义渲染成图（HTML+PNG+PDF）", False),
    ("exp", "scripts/exp.py", "经验库检索 / 入库 / 复核", False),
    ("retro", "scripts/retro.py", "复盘（六类教训）", False),
    ("status", "scripts/status.py", "生成人类可读 STATUS.md", False),
    ("validate", "scripts/validate.py", "数据完整性校验", False),
    ("coverage", "scripts/coverage_check.py", "覆盖对照（产出 vs 来源清单）", False),
    ("selfreview", "scripts/self_review.py", "交付前自审（对照清单逐条过）", False),
    ("export", "scripts/export.py", "导出数据", False),
    ("index", "scripts/build_index.py", "重建经验索引", False),
]


def show_help() -> int:
    print("Task Closure · 把模糊任务变成可执行、能跟踪、最终可验收的闭环")
    print()
    print("用法：python3 nav.py <命令> [参数…]")
    print()
    print("日常必用：")
    for cmd, script, desc, daily in COMMANDS:
        if daily:
            print(f"  {cmd:<12} {desc}")
    print()
    print("其余命令：")
    for cmd, script, desc, daily in COMMANDS:
        if not cmd:
            continue
        if not daily:
            print(f"  {cmd:<12} {desc}")
    print()
    print("直接透传：任何未列出的命令都会原样交给 scripts/<命令>.py")
    print()
    print("例：")
    print("  python3 nav.py show                        # 任务是哪些")
    print("  python3 nav.py show --task TN-...           # 某个任务的完整现场")
    print("  python3 nav.py test --quick                 # 快速自检（约 3 秒）")
    print("  python3 nav.py flow --init my_flow.json     # 生成流程图模板")
    print()
    print("第一次用：按顺序跑 init → test，然后让 AI 读 skills/task-navigator/SKILL.md")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        return show_help()

    name, rest = args[0], args[1:]

    # 查表
    target = None
    for cmd, script, _, _ in COMMANDS:
        if cmd and cmd == name:
            target = script
            break

    # 未列出的命令：透传给 scripts/<name>.py（方便老用户按脚本名调用）
    if target is None:
        guess = ROOT / "scripts" / f"{name}.py"
        if guess.is_file():
            target = str(guess.relative_to(ROOT))
        else:
            print(f"未知命令：{name}", file=sys.stderr)
            print(f"提示：运行 `python3 nav.py` 看有哪些命令。", file=sys.stderr)
            return 2

    script_path = ROOT / target
    if not script_path.is_file():
        print(f"找不到脚本：{target}", file=sys.stderr)
        print("（如果你移动了脚本，请同步更新 nav.py 的 COMMANDS 表）", file=sys.stderr)
        return 2

    # 原样转发，退出码透传——不吞错、不包装
    return subprocess.run([PY, str(script_path)] + rest, cwd=ROOT).returncode


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n中断", file=sys.stderr)
        sys.exit(130)
