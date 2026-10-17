#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""package_deliverables.py —— 整理一个任务的桌面交付目录。

⚠️ 范围（2026-10-15 因一次过度执行而写死在这里）：
   本脚本**不合并文档**。用户要的是——
     · 同一内容的多种格式挨在一起时，只保留一种（用户明确要 PDF 就留 PDF）
     · 各份独立文档保持独立，不要合并成一册
   把「只留一个格式」误读成「并成一册」，就是过度执行。

用法：
    python3 scripts/package_deliverables.py --task TN-20261015-004
    python3 scripts/package_deliverables.py --task TN-20261015-004 --check
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

# 浏览器路径改为运行时探测（见 store.find_chrome）
HERE = Path(__file__).resolve().parent


def load_md2html():
    spec = importlib.util.spec_from_file_location("md2html", HERE / "md2html.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 交付目录**不再写死**：Windows 桌面可能被 OneDrive 重定向；
# 也有人不用桌面。探测逻辑在 store.delivery_dir()，
# 可用环境变量 NAV_DELIVERY_DIR 覆盖。
DESKTOP = store.delivery_dir()
# 同一内容的多种格式：保留优先级（前面的优先保留，其余移出视线）
FORMAT_PRIORITY = [".pdf", ".html", ".png", ".jpg"]


def stem_of(name: str) -> str:
    """去掉扩展名，并去掉格式后缀，用于识别「同一内容的不同格式」。"""
    p = Path(name)
    stem = p.stem
    for suffix in ("（完整材料）", "-完整材料", "_完整材料"):
        stem = stem.replace(suffix, "")
    return stem.strip()


def merge_bundle_marker() -> str:
    """生成合并本时必须写入的标记（deliver.py 靠它识别合并行为）。

    设计说明：合并本检测的判据试过三版（文件名 / 一级标题数≥2 / ≥4），
    前两版都被实测证伪——**「一级标题数量」根本区分不了「文档内分节」与「多文档拼接」**。
    现改为标记法：合并这个动作自己留痕，合法文档不会有，误报率 0。
    """
    return "<!-- GENERATED-MERGE-BUNDLE: 由多份文档合并生成 -->\n\n"


def check(task_id: str) -> int:
    """检查桌面交付目录：同一内容是否残留多种格式。"""
    # 找任务对应的桌面子目录
    targets = [d for d in DESKTOP.iterdir() if d.is_dir()] if DESKTOP.is_dir() else []
    if not targets:
        print(f"  （桌面交付目录为空：{DESKTOP}）")
        return 0
    problems = []
    for d in targets:
        groups: dict[str, list[Path]] = {}
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() in FORMAT_PRIORITY and not f.name.startswith("."):
                groups.setdefault(stem_of(f.name), []).append(f)
        for stem, files in groups.items():
            if len(files) > 1:
                names = ", ".join(sorted(f.name for f in files))
                problems.append(f"{d.name}/：同一内容「{stem}」有 {len(files)} 种格式 → {names}")
    print("═══ 交付目录格式检查 ═══")
    # 合并本检测：文件名里出现「完整材料／合集／合并」等字样，
    # 通常意味着把多份独立文档并成了一册——那正是用户两次纠正过的行为。
    merge_marks = ("完整材料", "合集", "合并", "汇总本")
    merged = [f.name for d in targets for f in d.iterdir()
              if f.is_file() and any(m in f.name for m in merge_marks)]
    if merged:
        print("  ❌ 发现疑似「合并本」——用户明确要求各份文档保持独立：")
        for m in merged:
            print(f"     · {m}")
        print("     （SKILL.md §0 第 11 条：只做同内容格式去重，不做多文档合并）")
        return 1
    if problems:
        print("  ❌ 同一内容存在多种格式（用户明确要求：只留一种）：")
        for p in problems:
            print(f"     · {p}")
        return 1
    print("  ✅ 同一内容只保留一种格式")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把任务交付物合并成一册单个 PDF")
    ap.add_argument("--task", required=True)
    ap.add_argument("--title", default=None, help="PDF 标题")
    ap.add_argument("--out", type=Path, default=None, help="输出 PDF 路径")
    ap.add_argument("--check", action="store_true", help="只检查，不改动")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    return check(args.task)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
