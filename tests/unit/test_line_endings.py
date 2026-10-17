#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：仓库内的文本文件必须是 LF 换行。

## 为什么单独立这个测试

本项目用 sha256 校验「派生文件是否落后于权威数据」：
`methods/index.md` 里记录了 `methods/index.json` 的哈希。

Git for Windows 默认 `core.autocrlf=true`，检出时把 LF 转成 CRLF。
于是**同一个提交**在两台机器上算出两个哈希，`validate.py` 直接报：

    [M-INDEX-HASH] 记录的来源哈希 670d82… 与当前 … 的 b5a078… 不一致
    [M-INDEX-DRIFT] 第 11 行 期望 … 实际 …

数据根本没坏，是换行符变了。仓库已用 `.gitattributes`（`* text=auto eol=lf`）
把换行固定成 LF；这个测试守住它，防止将来某个提交/某次检出又把它弄回去。

## 失败时怎么办

说明当前副本是 CRLF 检出（旧版 clone，或本地覆盖了 core.autocrlf）：

    git rm --cached -r .
    git reset --hard

或者直接重新 clone。不要改这个测试去迁就换行符——哈希校验会随之失效。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

# 二进制：不参与换行检查（.gitattributes 里也单独声明了 binary）
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
    ".woff", ".woff2", ".ttf", ".xlsx", ".xls", ".docx", ".pptx",
}

# 这些目录里是生成物/本地状态，不属于「提交内容」（且已被 .gitignore 排除）
SKIP_PARTS = {".git", "outputs", "__pycache__", "node_modules", "reports"}


def tracked_files() -> list[pathlib.Path] | None:
    """用 git 列出被跟踪的文件；没有 git 时返回 None（跳过而不是误报）。"""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    raw = completed.stdout.decode("utf-8", errors="replace")
    return [ROOT / item for item in raw.split("\0") if item]


def main() -> int:
    files = tracked_files()
    if files is None:
        print("  ⚠️ 未找到 git（或不是 git 仓库）：跳过换行检查，不判失败")
        print()
        print("结论：跳过")
        return 0

    offenders: list[pathlib.Path] = []
    checked = 0
    for path in files:
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if not path.is_file():
            continue
        checked += 1
        if b"\r\n" in path.read_bytes():
            offenders.append(path)

    if offenders:
        print(f"  ❌ {len(offenders)} 个文本文件是 CRLF（应为 LF）：")
        for path in offenders[:10]:
            print(f"       {path.relative_to(ROOT)}")
        if len(offenders) > 10:
            print(f"       …另有 {len(offenders) - 10} 个")
        print("     修法：git rm --cached -r . && git reset --hard（或重新 clone）")
        print()
        print(f"结论：失败：{len(offenders)} 个 CRLF 文件")
        return 1

    print("LF 检查：")
    print(f"  ✅ {checked} 个被跟踪的文本文件全部为 LF")
    print()
    print("结论：通过")
    return 0


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    sys.path.insert(0, str(ROOT / "scripts"))
    import console  # noqa: E402

    console.setup()
    sys.exit(main())
