#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spec_coverage.py —— 规格覆盖率台账。用来取代「我觉得做完了」。

为什么需要它（2026-10-15，用户追问促成）：
  用户问：「为什么我上次说『从头回顾一下最最开始的要求，你全都做到了吗』，
  结果一顿修复之后，你又说完成了呢」
  查证结果：队长四次说「完成」，依据分别是——
    自评 3 条 / 审查员报的 12 条 / 审查员报的 5 条 / 自己的校验工具全绿。
  **四次依据全是「缺口清单」，没有一次是「规格原文」。**
  而 spec 里约 437 条可编号的要求单元，历次核对过的约 20 条 → 覆盖率约 5%。
  §J 六类（复盘按六类整理教训）就是那 95% 里的一条：三轮审计都没报，因为
  审计的产物是「缺口清单」，而清单天生是不完整的。

  **清单空 ≠ 规格满。** 这个脚本让「规格有多少条、核对过多少条」变成可查的数字，
  并强制把「未核对」显式写出来——而不是让它等于 0。

用法：
    python3 scripts/spec_coverage.py            # 显示覆盖率与未核对项
    python3 scripts/spec_coverage.py --sync     # 重新扫描 spec（新增条目记为未核对）
    python3 scripts/spec_coverage.py --list     # 列出全部条目及状态
    python3 scripts/spec_coverage.py --set <id> --status 已实现 --evidence "..." 
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

SPEC_DIR = store.PROJECT_ROOT / "spec"
LEDGER = store.PROJECT_ROOT / "reports" / "SPEC_COVERAGE.json"

# 状态：默认「未核对」。**不允许把「没看」写成「已实现」。**
STATUSES = ["未核对", "已实现", "部分实现", "未实现", "不适用"]


def scan_spec() -> list[dict]:
    """扫描 spec 文件，抽出可编号的要求单元。

    ID 用「文件名 + 行号」，因为它在原文里稳定、可回查——
    不用自增编号，避免插入一行就整体错位。
    """
    units: list[dict] = []
    if not SPEC_DIR.is_dir():
        return units
    for f in sorted(SPEC_DIR.glob("*.md")):
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            kind = None
            if re.match(r"^#{2,4} .+", s):
                kind = "章节"
            elif re.match(r"^[-*] .+", s) or re.match(r"^\d+\. .+", s):
                kind = "条目"
            # 散文段落也算要求单元。**这一条是踩坑后加的**：
            # spec/01_PRODUCT_SPEC.md:136 的 §J 六类要求写在散文里、不在列表里，
            # 第一版扫描器只抓标题和列表，把最关键的那条漏掉了——
            # 而"漏掉要求"正是本脚本存在的原因。
            if not kind:
                if (len(s) >= 30 and not s.startswith(("|", "```", ">", "```"))
                        and re.search(r"[。；]", s)):
                    kind = "段落"
                else:
                    continue
            text = re.sub(r"^#{2,4} |^[-*] |^\d+\. ", "", s).strip()
            text = re.sub(r"\*\*|`", "", text)
            if len(text) < 6:
                continue
            units.append({
                "id": f"{f.name}:L{lineno}",
                "file": f.name,
                "line": lineno,
                "kind": kind,
                "text": text[:150],
                "status": "未核对",
                "evidence": "",
                "checked_at": None,
            })
    return units


def load_ledger() -> dict:
    if LEDGER.is_file():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"generated_at": None, "units": []}


def sync() -> dict:
    """把 spec 现状与台账合并：已有条目保留状态，新增条目记为未核对。"""
    existing = {u["id"]: u for u in load_ledger().get("units", [])}
    fresh = scan_spec()
    merged = []
    for u in fresh:
        old = existing.get(u["id"])
        if old:
            u["status"] = old.get("status", "未核对")
            u["evidence"] = old.get("evidence", "")
            u["checked_at"] = old.get("checked_at")
        merged.append(u)
    ledger = {"generated_at": store.now_iso(), "units": merged}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    ledger["units"].sort(key=lambda x: (x["file"], x["line"]))
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ledger


def report(ledger: dict, show_list: bool) -> int:
    units = ledger.get("units", [])
    if not units:
        print("台账为空，请先运行 --sync")
        return 1

    import collections
    c = collections.Counter(u["status"] for u in units)
    total = len(units)
    checked = total - c.get("未核对", 0)

    print("═══ 规格覆盖率台账 ═══")
    print(f"  台账生成时间：{ledger.get('generated_at')}")
    print(f"  规格条目总数：{total}")
    print()
    for s in STATUSES:
        if c.get(s):
            bar = "█" * int(c[s] / total * 40)
            print(f"  {s:<6} {c[s]:>4} 条  {bar}")
    print()
    pct = checked / total * 100
    print(f"  已核对：{checked}/{total}　覆盖率 {pct:.1f}%")
    print()
    if c.get("未核对"):
        print(f"  ⚠️ 还有 {c['未核对']} 条从未核对——**这些不等于已实现，也不等于未实现，就是没看**")
        print("     「清单走完」不等于「要求全做到」：本台账就是为了让这句话有数字。")

    if show_list:
        print()
        print("── 未核对条目（按文件与行号）──")
        byfile: dict[str, list[dict]] = {}
        for u in units:
            if u["status"] == "未核对":
                byfile.setdefault(u["file"], []).append(u)
        for fname, items in sorted(byfile.items()):
            print(f"\n  【{fname}】{len(items)} 条未核对")
            for u in items[:40]:
                print(f"    L{u['line']:<5} [{u['kind']}] {u['text'][:88]}")
            if len(items) > 40:
                print(f"    …… 另有 {len(items) - 40} 条")
    return 0


def set_status(unit_id: str, status: str, evidence: str) -> int:
    if status not in STATUSES:
        print(f"错误：status 必须是 {STATUSES} 之一", file=sys.stderr)
        return 2
    ledger = load_ledger()
    hit = None
    for u in ledger.get("units", []):
        if u["id"] == unit_id:
            hit = u
            break
    if hit is None:
        print(f"错误：台账里没有 {unit_id}（先跑 --sync 或核对 ID）", file=sys.stderr)
        return 2
    hit["status"] = status
    hit["evidence"] = evidence
    hit["checked_at"] = store.now_iso()
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✅ {unit_id} → {status}")
    if evidence:
        print(f"     依据：{evidence}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="规格覆盖率台账")
    ap.add_argument("--sync", action="store_true", help="重新扫描 spec 并合并进台账")
    ap.add_argument("--list", action="store_true", help="列出未核对条目")
    ap.add_argument("--set", metavar="ID", help="设置某条的状态")
    ap.add_argument("--status", help=f"状态：{'/'.join(STATUSES)}")
    ap.add_argument("--evidence", default="", help="依据（文件/命令/提交号）")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    if args.set:
        if not args.status:
            print("错误：--set 需要同时给 --status", file=sys.stderr)
            return 2
        return set_status(args.set, args.status, args.evidence)
    ledger = sync() if args.sync else load_ledger()
    if not ledger.get("units"):
        ledger = sync()
    return report(ledger, args.list)


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
