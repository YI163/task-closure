#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：SKILL.md 的摘要（frontmatter description）必须包含入口触发词。

## 防止什么问题

交接报告第 2 项：AI 决定「要不要加载这个 Skill」时只看得到 description 那一行；
正文写得再清楚也不算数。实测用户说「把这个存到经验里」时，技能没被加载，
AI 转去用一个通用记忆工具——因为正文有「记经验」的入口，摘要里没有「经验」二字。

修复：description 补上「经验/教训/结论」等触发词。
约定（报告第 5 项）：**以后每新增一种入口行为，必须同时更新 description**；
本测试把已登记的入口行为触发词固定下来，漏改就失败。

注意：本测试只能证明「摘要包含触发词」，**不能**证明模型会因此选中技能——
那取决于模型读摘要后的判断，没有脚本能测（报告里也写明了这一点）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "task-navigator" / "SKILL.md"

# 已登记的入口行为 → 摘要里必须出现的触发词。
# 新增入口行为时：先在 description 补触发词，再把词加到这里。
REQUIRED_TRIGGERS = {
    "经验沉淀": "经验",
    "复盘": "复盘",
    "验收": "验收",
    "下一步建议": "下一步",
    "新任务建档": "提出一项要做的事",
}


def check(condition: bool, label: str, failures: list[str], detail: str = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


def frontmatter() -> dict[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def main() -> int:
    failures: list[str] = []
    meta = frontmatter()
    description = meta.get("description", "")

    check(meta.get("name") == "task-closure", "frontmatter 含 name: task-closure", failures,
          meta.get("name", "（缺）"))
    check(bool(description), "frontmatter 含 description", failures)
    check("\n" not in description, "description 是单行", failures)

    for behavior, trigger in REQUIRED_TRIGGERS.items():
        check(trigger in description,
              f"摘要含入口触发词：{behavior} → 「{trigger}」", failures,
              "" if trigger in description else "缺，会导致该入口不加载技能")

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
