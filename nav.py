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

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# 项目根目录的显式配置项（可选）。
#
# 为什么需要它：本 Skill 可以被链接到 ~/.agents/skills/ 供所有工作区加载，
# 那时「Skill 文件在哪」与「任务数据/仓库在哪」不是一回事。若只靠推算，
# AI 可能对着错误的目录操作，或悄悄建出第二套 state/。
# 约定：设置了 TASK_CLOSURE_HOME 就必须与本仓库一致；不一致时 nav.py 直接拒绝执行。
HOME_ENV = "TASK_CLOSURE_HOME"


def configured_home() -> Path | None:
    raw = os.environ.get(HOME_ENV, "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except OSError:
        return Path(raw).expanduser()


def _same_path(left: Path, right: Path) -> bool:
    # Windows 路径大小写不敏感；normcase 同时统一分隔符
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def home_mismatch() -> Path | None:
    """TASK_CLOSURE_HOME 已设置且与脚本所在仓库不一致时返回该目录，否则 None。"""
    configured = configured_home()
    if configured is None or _same_path(configured, ROOT.resolve()):
        return None
    return configured


def show_env() -> int:
    """打印当前实际使用的目录，并自检 TASK_CLOSURE_HOME 是否一致。"""
    resolved = ROOT.resolve()
    configured = configured_home()
    print("Task Closure 环境自检")
    print(f"  项目根目录        : {resolved}")
    print(f"  数据目录          : {resolved / 'state'}")
    # 经验/教训目录单独列：两台电脑共用经验库时，这两行会显示「链接 → 私有数据仓库」，
    # 一眼能确认自己写的经验到底落到了哪份数据里。
    for label, directory in (("经验目录", resolved / "state" / "experience"),
                             ("教训目录", resolved / "state" / "lessons")):
        link_note = ""
        try:
            real = directory.resolve()
            if real != directory:
                link_note = f"（链接 → {real}）"
        except OSError:
            pass
        print(f"  {label}        : {directory}{link_note}")
    print(f"  Python            : {PY}")
    print(f"  {HOME_ENV:<17} : {configured if configured is not None else '（未设置，以脚本所在仓库为准）'}")
    if configured is None:
        print("  状态              : 未设置环境变量（用脚本自身位置定位，不存在第二套状态）")
        return 0
    if _same_path(configured, resolved):
        print("  状态              : 一致")
        return 0
    print("  状态              : 不一致 —— 已停止，避免写进第二套 state/")
    print(f"  处理：① 在 {configured} 里执行；② 或把 {HOME_ENV} 改成 {resolved}；③ 或临时取消该环境变量")
    return 5


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
    print("先跑这个（换机器 / 换目录后尤其重要）：")
    print(f"  {'env':<12} 打印当前项目根目录、数据目录、Python，并自检 {HOME_ENV}")
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
    print("  python3 nav.py test --quick                 # 快速自检（约 16 秒）")
    print("  python3 nav.py flow --init my_flow.json     # 生成流程图模板")
    print()
    print("第一次用：按顺序跑 init → test，然后让 AI 读 skills/task-navigator/SKILL.md")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        return show_help()

    name, rest = args[0], args[1:]

    # 环境自检：打印实际使用的目录，并检查 TASK_CLOSURE_HOME 是否一致
    if name == "env":
        return show_env()

    # 路径守卫：环境变量指向别的仓库时不许继续。
    # 否则「以为在操作 A 仓库、实际写进 B 仓库的 state/」这种事只能靠事后发现。
    mismatch = home_mismatch()
    if mismatch is not None:
        print(f"错误：{HOME_ENV} 指向 {mismatch}", file=sys.stderr)
        print(f"      但本次执行的是 {ROOT.resolve()}", file=sys.stderr)
        print("两份目录不一致时不允许继续——那会把状态写进第二套 state/，或在错误仓库上操作。", file=sys.stderr)
        print(f"处理：① 在 {mismatch} 里执行；② 或把 {HOME_ENV} 改成 {ROOT.resolve()}；"
              "③ 或临时取消该环境变量。", file=sys.stderr)
        print(f"（先跑 `python nav.py env` 看它到底读的是哪个目录）", file=sys.stderr)
        return 5

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
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    sys.path.insert(0, str(ROOT / "scripts"))
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n中断", file=sys.stderr)
        sys.exit(130)
