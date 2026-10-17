#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台编码引导：让脚本在 Windows 上被重定向/接管输出时不再崩溃。

## 为什么需要它

Windows 上 Python 的 stdout/stderr 一旦**不是控制台**（管道、文件、CI 捕获），
就会使用系统区域编码（中文 Windows 是 cp936）。本项目输出里有 ✅ ❌ ▶ ═ ─
这类字符，cp936 编不出来，于是直接抛异常：

    UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'

后果比看起来严重：

- `python nav.py test > log.txt` 直接崩掉第一套；
- 测试运行器用管道捕获子进程输出时，**子进程**崩掉，父进程只看到 exit=1；
- CI、编辑器、Agent 等任何接管输出的场景都一样。

代码本身没有错，错的是「默认编码取决于运行环境」，而项目输出的字符集
不落在 cp936 里。

## 做法

- **控制台（TTY）**：不改编码。Windows 控制台由 Python 直接写 Unicode，
  不受区域编码限制；这里只把 errors 放宽，避免个别字符让整行崩掉。
- **非控制台（管道/文件）**：统一改成 UTF-8。读的一方（本项目的测试运行器、
  CI、日志工具）也按 UTF-8 解码，两侧约定一致，跨平台稳定。

作为库被 import 时没有副作用——只有调用 setup() 才会动 stdio。

## 用法

在每个「会被当作命令执行」的脚本入口调用一次：

    if __name__ == "__main__":
        import console
        console.setup()
        sys.exit(main(sys.argv))
"""

from __future__ import annotations

import sys

# 管道/文件场景统一使用的编码。测试运行器解码子进程输出时也用这个值。
TEXT_ENCODING = "utf-8"


def _configure(stream) -> None:
    """按「是否控制台」调整单个流；不可用时保持原样（绝不因此中断程序）。"""
    if stream is None or not hasattr(stream, "reconfigure"):
        return
    try:
        is_console = stream.isatty()
    except (AttributeError, ValueError, OSError):
        is_console = False
    try:
        if is_console:
            # 控制台本来就是 Unicode 的；只放宽错误处理，不换编码。
            stream.reconfigure(errors="backslashreplace")
        else:
            stream.reconfigure(encoding=TEXT_ENCODING, errors="backslashreplace")
    except (AttributeError, ValueError, OSError):
        pass


def setup() -> str:
    """调整 stdout/stderr，返回 stdout 实际采用的编码名（便于自检与排错）。"""
    _configure(sys.stdout)
    _configure(sys.stderr)
    return getattr(sys.stdout, "encoding", None) or TEXT_ENCODING


if __name__ == "__main__":
    # 自检：python scripts/console.py | cat
    print(f"stdout 编码：{setup()}")
    print("自检样本：✅ ❌ ▶ ═ ─ 中文")
