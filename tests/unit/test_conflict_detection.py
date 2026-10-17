#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：经验冲突检测的误报/漏报边界。

## 背景（来自交接报告第 1、4 项）

`_action_conflict` 原来的否定分支是「共享 ≥2 个片段 + 一侧带否定词」。同领域经验
天然共享「单独 / 痛点 / 验证 / 机制」这类 2 字片段，这个条件几乎恒真——实测连续
4 对互不相干的经验被判 `G3-CONFLICT-ACTION`，其中两对还是同一批写入的互补条目。

修复（v0.1.3）：否定分支额外要求**至少一个 4 字中文共享片段**。
真冲突（「先与经理确认研究范围…」vs「不要先与经理确认研究范围…」）共享 8 个
4 字片段；词表碰撞共享 0 个。

`_trigger_conflict` 结构同源，但交接报告明确：**没有复现误报就不要改逻辑**，
只补下面三条构造样例作为回归（第 4 项）。

> 说明：报告里的 4 对原始经验内容没有随仓库提供，这里用**同等结构**的句子复现
> 同一类误报（共享 2 字片段、无 4 字重合、否定不对称），并用真正的长片段冲突对
> 做正控制。测试防的是「判据不能只靠 2 字片段」这个回归，不冒充原始样本本身。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import exp  # noqa: E402


def check(condition: bool, label: str, failures: list[str], detail: str = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


# 共享 ≥2 个 2 字片段、但没有 4 字重合，且一侧带否定词 —— 旧判据会误报
FALSE_PAIRS = [
    ("先单独验证机制，再扩大范围", "不要直接把痛点当需求，先做小范围验证"),
    ("先把验证结果写进复盘，机制单独记录", "不要只记录痛点，验证与机制要分开写"),
    ("先做小范围验证，确认机制有效再扩展", "不要用痛点代替验证，机制要单独核对"),
    ("按清单逐项核对后保存记录", "不要跳过核对，保存前先看清单"),
]

TRUE_PAIR = ("先与经理确认研究范围，再开始研究", "不要先与经理确认研究范围，直接开始研究")

# 交接报告第 4 项给的三个构造样例（不改逻辑，只锁行为）
TRIGGER_CASES = [
    ("资料齐全、可以直接开始对比", "资料缺失、还不能开始对比", True,
     "互斥词对 齐全/缺失"),
    ("准备把用户抱怨当成产品卖点", "整理历史文档、不涉及产品判断", False,
     "只共享「产品」一个词，不应误报"),
    ("准备做竞品定价核对", "不要做竞品定价核对", True,
     "真互斥：同一做法一侧被否定"),
]


def action_pair(a_text: str, b_text: str):
    return exp._action_conflict(
        {"recommended_action": a_text}, {"recommended_action": b_text}
    )


def main() -> int:
    failures: list[str] = []

    print("_action_conflict：")
    for a_text, b_text in FALSE_PAIRS:
        result = action_pair(a_text, b_text)
        check(result is None, f"不误报：{a_text[:12]}… vs {b_text[:12]}…", failures,
              result or "无冲突（正确）")

    result = action_pair(*TRUE_PAIR)
    check(result is not None and "共享片段" in result,
          "真冲突（长片段重合 + 否定不对称）仍能检出", failures, result or "漏报")

    print("\n_trigger_conflict（只加回归，不改逻辑）：")
    for a_text, b_text, expected, why in TRIGGER_CASES:
        result = exp._trigger_conflict(
            {"trigger_conditions": [a_text]}, {"trigger_conditions": [b_text]}
        )
        ok = (result is not None) == expected
        check(ok, f"{'应检出' if expected else '不应检出'}：{why}", failures,
              result or "无冲突")

    print("\n否定词表：")
    check(exp._negated("判断值不值得做") is False,
          "「值不值得」不被误判为否定（不含「不得」子串）", failures)

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
