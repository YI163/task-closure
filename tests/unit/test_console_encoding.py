#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：输出被管道/文件接管时不得因编码崩溃。

## 为什么单独立这个测试

Windows 中文环境下，Python 的 stdout **一旦不是控制台**（管道、文件、CI 捕获），
就用系统区域编码 cp936。本项目大量使用 ✅ ❌ ▶ ═ ─，这些字符 cp936 编不出来：

    UnicodeEncodeError: 'gbk' codec can't encode character '\\u2705'

实测后果不是「一行乱码」，而是整条链崩掉：

- `python nav.py test > log.txt` 第一套就崩；
- 测试运行器用管道捕获子进程时，**子进程**崩，父进程只看到 exit=1；
- 最终表现为「5 套测试全部失败、输出为空」——非常容易误判成业务代码坏了。

修法是 scripts/console.py：非控制台流统一 UTF-8。这个测试用「真管道」捕获
子进程输出，复现的就是那个场景。

> 在 Linux/macOS 上这条测试天然通过（默认 UTF-8）——它守的是 Windows 的默认行为，
> 所以本地「过了」不代表没价值：CI 的 windows 矩阵会真正跑到它。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run_piped(args: list[str]) -> subprocess.CompletedProcess:
    """用管道捕获（capture_output=True）——这正是会触发 cp936 的形态。"""
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,  # 不指定 text：拿原始字节，自己判断编码
        timeout=120,
    )


def checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # 1) nav.py --help：最常用的入口，输出全是中文
    proc = run_piped(["nav.py", "--help"])
    try:
        text = proc.stdout.decode("utf-8")
        decoded = True
    except UnicodeDecodeError as exc:
        text, decoded = "", False
    results.append((
        "nav.py --help 的管道输出是合法 UTF-8",
        decoded,
        "可解码" if decoded else f"解码失败：{exc}",
    ))
    results.append((
        "nav.py --help 退出码 0 且含预期中文",
        proc.returncode == 0 and "日常必用" in text,
        f"exit={proc.returncode}",
    ))

    # 2) console.setup() 在管道下确实切到 UTF-8，并能打印 ✅
    scripts_dir = ROOT / "scripts"
    inline = (
        f"import sys; sys.path.insert(0, {str(scripts_dir)!r}); "
        "import console; "
        "encoding = console.setup(); "
        "print(encoding); "
        "print('✅ ❌ ▶ ═ ─ 中文样本')"
    )
    proc = run_piped(["-c", inline])
    out = proc.stdout.decode("utf-8", errors="replace")
    lines = out.splitlines()
    results.append((
        "管道下 console.setup() 返回 utf-8",
        bool(lines) and lines[0].strip() == "utf-8",
        f"实测 {lines[0].strip() if lines else '（无输出）'}",
    ))
    results.append((
        "管道下能打印 ✅/▶ 等字符（不抛 UnicodeEncodeError）",
        proc.returncode == 0 and "✅" in out and "UnicodeEncodeError" not in proc.stderr.decode("utf-8", "replace"),
        f"exit={proc.returncode}",
    ))

    # 3) 子进程若真的崩了，stderr 里会有 UnicodeEncodeError——显式排除这种假通过
    stderr_text = proc.stderr.decode("utf-8", errors="replace")
    results.append((
        "子进程 stderr 无 UnicodeEncodeError",
        "UnicodeEncodeError" not in stderr_text,
        stderr_text.strip().splitlines()[-1] if stderr_text.strip() else "（空）",
    ))

    return results


def main() -> int:
    print("输出编码（管道场景）：")
    failures: list[str] = []
    for label, ok, detail in checks():
        print(f"  {'✅' if ok else '❌'} {label}（{detail}）")
        if not ok:
            failures.append(label)

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
