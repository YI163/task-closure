#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 tests/cases/T*/input*.json 的步骤补齐执行者字段（t21 新增必填字段的 fixture 维护）。

背景：t21 把「步骤必须声明执行者」变成机械门禁后，tests/cases/ 下的场景输入
（T01–T14 的固定 fixture）会在写入侧被拒绝——它们都是 t21 之前写的、没有 executor。

设计取舍（重要，不要静默改语义）：
* 统一填**默认规则**的值：executor="user"（用户自己的事务默认用户做、AI 指导），
  executor_basis 写明这是「测试夹具按默认规则补齐」。不替场景编造「谁做」的判断，
  只满足必填约束——这些场景要测的是别的规则。
* 只补缺失的字段，已有 executor 的步骤不动；幂等，可反复运行。
* **逐处文本插入，不做 JSON 重新序列化**：原文件里短数组写在一行内，
  json.dumps 会把它们全部展开，产生与本次维护无关的大量 diff。
* 支持两种既有写法：`    {`（键在后续行）与 `    {"step_id": …`（首键与左花括号同行）。
* 找不到 plan 区间、或步骤数与解析结果不一致时**放弃整份文件**（不做部分修改）。
* 默认 dry-run，加 --apply 才落盘。

用法：
    python3 tests/invalid/add_executor_to_cases.py           # 预览
    python3 tests/invalid/add_executor_to_cases.py --apply   # 落盘
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CASES = ROOT / "tests" / "cases"
DEFAULT_EXECUTOR = "user"
DEFAULT_BASIS = "测试夹具：按默认规则补齐（用户自己的事务默认用户做、AI 指导）——本场景测的是其它规则"


def plan_region(text: str) -> tuple[int, int] | None:
    """返回 "plan": [ … ] 的字符区间（含方括号）。"""
    match = re.search(r'"plan"\s*:\s*\[', text)
    if not match:
        return None
    start = text.index("[", match.start())
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return start, index + 1
    return None


def step_starts(text: str, region: tuple[int, int]) -> list[tuple[int, int]]:
    """plan 区间内每个步骤对象的 (行号, 左花括号列号)，按出现顺序。

    只取最外层缩进（步骤一定是最外层的对象），避免把嵌套对象当成步骤。
    """
    start, end = region
    head = text[:start]
    first_line = head.count("\n")
    lines = text[:end].splitlines(keepends=True)
    candidates: list[tuple[int, int, str]] = []
    for lineno in range(first_line, len(lines)):
        line = lines[lineno]
        match = re.match(r"([ \t]*)\{", line)
        if match and lineno > first_line:
            candidates.append((lineno, match.end() - 1, match.group(1)))
    if not candidates:
        return []
    outer = min(len(indent) for _, _, indent in candidates)
    return [(lineno, col) for lineno, col, indent in candidates if len(indent) == outer]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="为场景 fixture 补齐 executor/executor_basis（t21）")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认只预览）")
    args = parser.parse_args(argv[1:])

    # 不只 input*.json：T07 的 change_urgent.json 这类「换计划」载荷同样带 plan 数组，
    # 缺执行者会被写入侧拒绝，同样属于本次必填字段带来的 fixture 维护。
    targets = sorted(CASES.glob("T*/*.json"))
    if not targets:
        print(f"找不到场景数据：{CASES}/T*/*.json", file=sys.stderr)
        return 2

    touched_files, touched_steps, skipped = 0, 0, []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or "plan" not in data:
            continue
        steps = [s for s in (data.get("plan") or []) if isinstance(s, dict)]
        if not steps:
            continue
        region = plan_region(text)
        starts = step_starts(text, region) if region else []
        if len(starts) != len(steps):
            skipped.append((path, f"区间内找到 {len(starts)} 个步骤起点、解析出 {len(steps)} 个步骤"))
            continue

        lines = text.splitlines(keepends=True)
        edits = 0
        # 逆序处理，避免行号/列号位移
        for index in range(len(steps) - 1, -1, -1):
            lineno, col = starts[index]
            span_end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
            span = "".join(lines[lineno:span_end])
            add_executor = '"executor"' not in span
            add_basis = '"executor_basis"' not in span
            if not (add_executor or add_basis):
                continue
            payload = []
            if add_executor:
                payload.append(f'"executor": "{DEFAULT_EXECUTOR}", ')
            if add_basis:
                payload.append(f'"executor_basis": "{DEFAULT_BASIS}", ')
            line = lines[lineno]
            if line[col + 1:].strip():                     # 首键与左花括号同行 → 就地插入
                lines[lineno] = line[: col + 1] + " " + "".join(payload) + line[col + 1:].lstrip()
            else:                                          # 左花括号独占一行 → 另起两行
                indent = re.match(r"([ \t]*)", line).group(1) + "  "
                new_lines = [f'{indent}"executor": "{DEFAULT_EXECUTOR}",\n'] if add_executor else []
                if add_basis:
                    new_lines.append(f'{indent}"executor_basis": "{DEFAULT_BASIS}",\n')
                lines[lineno + 1:lineno + 1] = new_lines
            edits += 1

        if not edits:
            continue
        touched_files += 1
        touched_steps += edits
        print(f"{'写入' if args.apply else '将改'} {path.relative_to(ROOT)}：{edits} 个步骤")
        if args.apply:
            path.write_text("".join(lines), encoding="utf-8")

    for path, why in skipped:
        print(f"跳过 {path.relative_to(ROOT)}：{why}（不做任何修改）", file=sys.stderr)
    verb = "已写入" if args.apply else "预览"
    print(f"\n{verb}：{touched_files} 个文件 / {touched_steps} 个步骤"
          + ("" if args.apply else "（加 --apply 才落盘）"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
