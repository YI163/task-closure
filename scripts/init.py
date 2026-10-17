#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init.py —— 初始化一个空的工作数据目录。让新用户拿到包就能用。

为什么需要它：实测把代码包发给别人后，`validate.py --all` 会 exit=1——
因为 state/ 下没有 tasks.json / user_skills.json / experience/，脚本找不到数据。
分享包必须自带「第一次怎么开始」，否则对方第一步就卡住。

用法：
    python3 scripts/init.py                 # 在当前目录建 state/（若不存在）
    python3 scripts/init.py --dir my-task   # 指定目录
    python3 scripts/init.py --force         # 覆盖已存在的骨架（不动已有数据文件）
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent

SKELETON = {
    "tasks.json": {
        "schema_version": "1.0",
        "tasks": [],
    },
    "user_skills.json": {
        "schema_version": "1.0",
        "skills": [],
    },
}


def seed_state(target: Path, force: bool) -> int:
    state = target / "state"
    state.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    kept: list[str] = []

    # schema.json 是契约，必须与脚本一起分发
    schema_src = PACKAGE_ROOT / "state" / "schema.json"
    schema_dst = state / "schema.json"
    if schema_src.exists():
        if not schema_dst.exists() or force:
            shutil.copy2(schema_src, schema_dst)
            created.append("state/schema.json")
        else:
            kept.append("state/schema.json")
    else:
        print(f"警告：找不到契约文件 {schema_src}——脚本将无法运行", file=sys.stderr)

    for name, content in SKELETON.items():
        path = state / name
        if path.exists() and not force:
            kept.append(f"state/{name}")
            continue
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(f"state/{name}")

    exp = state / "experience"
    exp.mkdir(exist_ok=True)
    (exp / ".gitkeep").touch()
    created.append("state/experience/")

    (state / "backups").mkdir(exist_ok=True)

    print(f"═══ 初始化完成：{target} ═══")
    for c in created:
        print(f"  + {c}")
    for k in kept:
        print(f"  = {k}（已存在，未改动）")
    print()
    print("下一步：")
    print("  1. 把你自己的技能档案填进 state/user_skills.json（可以是空数组，也能直接开始用）")
    print("  2. 让 AI 读 skills/task-navigator/SKILL.md——**这一步不做，整套东西不会自动生效**")
    print("  3. 之后每次涉及任务，先跑： python3 scripts/task_show.py")
    print()
    print("验证是否可用： python3 scripts/validate.py --all")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="初始化工作数据目录（分享包开箱第一步）")
    ap.add_argument("--dir", type=Path, default=Path.cwd(), help="目标目录，默认当前目录")
    ap.add_argument("--force", action="store_true", help="覆盖已有骨架文件（不删数据）")
    args = ap.parse_args(argv[1:])
    return seed_state(args.dir.resolve(), args.force)


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    sys.exit(main(sys.argv))
