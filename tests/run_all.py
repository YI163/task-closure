#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一条命令跑完全部测试。

## 为什么需要它

项目有三套测试，但此前要分别跑三条命令、各自看退出码：

    python3 scripts/validate.py --all        # 数据完整性
    python3 tests/run_tests.py --all         # 场景测试（端到端）
    python3 tests/invalid/run_rules.py       # 反例测试（每条规则配一个必失败样本）

分开跑的代价：**容易只跑一条就以为全过了**。实测踩过——
改了校验规则只跑 `validate`，反例全红却不知道。
本项目为此付过代价：一条规则「看起来有护栏，实际检查没实现」，
因为没人跑反例，问题一直没暴露。

## 用法

    python3 tests/run_all.py            # 跑全部套件
    python3 tests/run_all.py --quick    # 跳过场景测试（约 15 秒）
    python3 tests/run_all.py --verbose  # 打印每套的完整输出

退出码：0 = 全部通过；1 = 有失败；2 = 环境问题（找不到测试文件等）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 单元测试：tests/unit/*.py 各自是独立脚本，逐个跑。
# 它们守的是「单点逻辑」——如跨平台路径探测、md2html 的围栏代码块渲染。
# 这类 bug 不会让任何校验器报错，只能靠单测守住。
UNIT_TESTS = sorted((ROOT / "tests" / "unit").glob("test_*.py"))

# (名称, 命令, 是否属于 --quick 子集, 超时秒数)
SUITES = [
    ("数据完整性校验", [str(ROOT / "scripts" / "validate.py"), "--all"], True, 120),
    ("反例测试（规则必须有失败样本）", [str(ROOT / "tests" / "invalid" / "run_rules.py")], True, 300),
    ("场景测试（端到端断言）", [str(ROOT / "tests" / "run_tests.py"), "--all"], False, 600),
] + [
    (f"单元测试 {t.stem}", [str(t)], True, 60) for t in UNIT_TESTS
]


def run_suite(name: str, cmd: list[str], timeout: int, verbose: bool) -> tuple[bool, str, float]:
    """跑一套测试。返回 (是否通过, 摘要行, 耗时)。"""
    started = time.perf_counter()
    try:
        # 必须显式按 UTF-8 解码：Windows 的文本模式默认用系统区域编码（中文为 cp936），
        # 而子进程输出 UTF-8（各脚本入口调用 console.setup()）。两侧不一致会抛
        # UnicodeDecodeError——实测表现为「5 套测试全部失败、输出为空」。
        proc = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"超时（>{timeout}s）", time.perf_counter() - started
    except FileNotFoundError as exc:
        return False, f"找不到测试入口：{exc}", time.perf_counter() - started

    elapsed = time.perf_counter() - started

    if verbose:
        print("─" * 68)
        print(output.rstrip())
        print("─" * 68)
    else:
        # 只留结论行：以「结论」「自动断言」「通过」「失败」开头的
        for line in output.splitlines():
            st = line.strip()
            if st.startswith(("结论", "自动断言", "通过      ", "失败      ", "错误    ")):
                print(f"    {st}")

    return code == 0, f"exit={code}", elapsed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="一条命令跑完全部测试")
    ap.add_argument("--quick", action="store_true", help="跳过慢的场景测试")
    ap.add_argument("--verbose", action="store_true", help="打印完整输出")
    args = ap.parse_args(argv[1:])

    selected = [s for s in SUITES if not args.quick or s[2]]

    print("═" * 68)
    print(f"任务导航 · 全部测试（{len(selected)} 套{'，quick 模式' if args.quick else ''}）")
    print("═" * 68)

    results = []
    total_started = time.perf_counter()
    for name, cmd, _, timeout in selected:
        print()
        print(f"▶ {name}")
        ok, detail, elapsed = run_suite(name, cmd, timeout, args.verbose)
        results.append((name, ok, detail, elapsed))
        print(f"    {'✅ 通过' if ok else '❌ 失败'}　{detail}　{elapsed:.1f}s")

    total = time.perf_counter() - total_started
    failed = [r for r in results if not r[1]]

    print()
    print("═" * 68)
    print(f"汇总：{len(results) - len(failed)}/{len(results)} 套通过，总耗时 {total:.1f}s")
    if failed:
        print("失败项：")
        for name, _, detail, _ in failed:
            print(f"  ❌ {name}（{detail}）")
        print()
        print("**没全过就不要说「测试通过」。**")
        print("═" * 68)
        return 1
    print("全部通过。")
    print("═" * 68)
    return 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    sys.path.insert(0, str(ROOT / "scripts"))
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n中断", file=sys.stderr)
        sys.exit(2)
