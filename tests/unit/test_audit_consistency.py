#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：审计表与 SKILL.md 的条款数量/编号必须一致，且机械规则必须有行为测试。

## 防止什么问题

审查报告 P1-4：

- 审计表与文档脱节过两次（表里漏了第 11、12 条，编号写成 102/103）；
- 旧审计只要源码里出现特征字符串就宣称「机械」，没有行为证据。

这个测试守着三件事：

1. 审计表条数 == SKILL.md §0 的条款条数（含 10-2）；
2. 编号逐条一致；
3. 凡是声称「机械」的规则，都必须关联一个真实存在的行为探针。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import audit  # noqa: E402

NUMERALS = {"十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16}


def check(condition: bool, label: str, failures: list[str], detail: str = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    failures: list[str] = []
    text = audit.SKILL.read_text(encoding="utf-8")
    head = text.split("### 4.1")[0]
    pattern = re.compile(r"^(\d+(?:-\d+)?)\. \*\*", re.M)
    doc_numbers = pattern.findall(head)
    rule_numbers = [str(rule[0]) for rule in audit.RULES]

    check(len(doc_numbers) == len(audit.RULES),
          "审计表条数与 SKILL.md 一致", failures,
          f"文档 {len(doc_numbers)} / 审计表 {len(audit.RULES)}")
    check(doc_numbers == rule_numbers,
          "编号逐条一致（含 10-2，不用 102/103 自编号）", failures,
          f"文档 {doc_numbers} / 审计表 {rule_numbers}")

    heading = re.search(r"^## 0\. (\S+?)条硬前置", text, re.M)
    if heading and heading.group(1) in NUMERALS:
        check(NUMERALS[heading.group(1)] == len(audit.RULES),
              "标题里的中文条数与实际条数一致", failures,
              f"标题 {heading.group(1)} / 实际 {len(audit.RULES)}")

    mechanical = [rule for rule in audit.RULES if rule[2] == "机械"]
    missing = [rule[0] for rule in mechanical if not rule[4]]
    check(not missing, "所有「机械」规则都有关联的行为探针", failures,
          f"缺探针：{missing}" if missing else f"{len(mechanical)} 条")

    probe_source = audit.PROBE_SCRIPT.read_text(encoding="utf-8") if audit.PROBE_SCRIPT.is_file() else ""
    unknown = sorted({rule[4] for rule in audit.RULES if rule[4] and f'"{rule[4]}"' not in probe_source})
    check(audit.PROBE_SCRIPT.is_file(), "行为探针脚本存在", failures, str(audit.PROBE_SCRIPT))
    check(not unknown, "审计表引用的探针都真的定义在探针脚本里", failures,
          f"未定义：{unknown}" if unknown else "全部已定义")

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
