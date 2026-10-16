#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_review.py —— 交付前的「第二档审查」：对照清单逐条过，留下打回项。

## 为什么是这个设计（用户提议 + 一次失败教训）

用户提议：「做完一项内容，自我审查一遍怎么样，过了某个评分就过，没有过就打回」。

**采纳的部分**：交付前自审、不过就打回——对。
**改掉的部分**：**不做评分**。理由是本会话的实测教训：
用户问「你全都做到了吗」，队长把「**缺口清单走完了**」（可打分）说成
「**要求全做到了**」（不可打分）。**一旦有分数，执行者会优化分数而不是目标。**
→ 所以本工具**只产出「打回清单」**，不给分、不给合格线。
   要么清单是空的（可以交付），要么清单里有条目（逐条清掉再交）。

## 为什么「自己审」也可能有用（此前判断过严）

队长此前说过「自己审会为自己辩护」。**那说的是凭感觉审。**
如果审的动作是「**对照别人定的清单逐条过**」（规则、任务 constraints、来源材料），
辩护空间就小得多——**因为清单不是执行者自己定的**。

## 三档分工（实测耗时，差三个数量级）

| 档 | 手段 | 耗时 | 用在哪 |
|---|---|---|---|
| 一档 | 机械检查（deliver/validate/coverage） | **6 秒** | 每次交付，强制 |
| 二档 | **本工具：自审清单** | **~10 秒** | 每次交付，强制记录 |
| 三档 | 独立 agent 审查 | **5–15 分钟** | 高风险任务（现场交付、对外材料） |

## 用法

    python3 scripts/self_review.py --task TN-20261015-005          # 生成清单
    python3 scripts/self_review.py --task X --record --all-clear   # 记录「全部通过」
    python3 scripts/self_review.py --task X --record --reject "第3条：流程图缺环节"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

REC_DIR = store.STATE_DIR / "self_reviews"


def build_items(task: dict, task_id: str) -> list[dict]:
    """从「别人定的东西」生成清单——任务 constraints、来源材料、规则要点。

    关键：清单项**不由执行者当场编**，而是从已有材料里抽。
    这样「逐条过」才是真的对照，而不是自我确认。
    """
    items: list[dict] = []

    # 只把「可检查的要求」变成检查项；纯参考信息（题目内容、答案数值）跳过。
    # 实测噪音：CONSTRAINT「题目为…；(1)证…(2)求 PD」与「答案 PD=28.8」
    # 是**参考信息**，不是要我核对的动作——列进去只会让清单变长、稀释注意力。
    SKIP_HINTS = ("答案", "题目为", "已两法互验")
    for i, c in enumerate(task.get("constraints") or [], 1):
        if any(h in c for h in SKIP_HINTS):
            continue
        items.append({
            "id": f"CONSTRAINT-{i}",
            "source": "任务 constraints（用户声明）",
            "ask": f"这条做到了吗？—— {c}",
        })

    sc = task.get("success_criteria") or []
    for i, c in enumerate(sc, 1):
        items.append({
            "id": f"CRITERIA-{i}",
            "source": "成功标准（建档时定）",
            "ask": f"这条能拿出证据吗？—— {c}",
        })

    # 固定项：每项都对应一次实测事故
    FIXED = [
        ("DELIV-1", "交付物在用户能打开的位置？命名短且讲什么放最前？"),
        ("DELIV-2", "文档格式是 .html？（用户点名要 PDF 的那类除外）"),
        ("DELIV-3", "没有把多份独立文档合并成一个文件？"),
        ("DELIV-4", "同一内容只留了一种格式？"),
        ("FLOW-1", "流程图是渲染出来的图（不是手写 ASCII 代码块）？"),
        ("FLOW-2", "流程图覆盖了来源里写明的**全部**环节？"),
        ("GUIDE-1", "有「一步一步做什么」的行动清单，且步骤可勾选？"),
        ("SRC-1", "凡引用二手/机器转写素材，写明了它的准确率与不确定处？"),
        ("PROMISE-1", "交付物里每句「建议做 X」都配了怎么做？"),
        ("UNKNOWN-1", "我不知道/没核实的部分，显式标出来了（没写成事实）？"),
    ]
    for fid, ask in FIXED:
        items.append({"id": fid, "source": "SKILL.md 硬前置与实测事故", "ask": ask})

    return items


def cmd_build(task_id: str) -> int:
    data = store.load_tasks()
    task = store.find_task(data["tasks"], task_id)
    items = build_items(task, task_id)

    # ══ 立场声明（用户提议「打上别人的标记」的可落地版本）══
    # 我做不到真的以为这是别人写的——推理链就在上下文里，改标签不会消失。
    # 但**换立场**有效：把自己定位成审稿人，去掉作者的辩护权。
    # 两种辩护在这里都不成立：
    #   ① 用意图辩护（「我本意是…」）→ 审稿人只能看稿子，看不到意图
    #   ② 用自己的推理辩护（「我当时想的是…」）→ 审的是"作者当时想的是什么"
    # 关键操作：**把产出本身打出来**，跟清单并排——
    #   这样审的是眼前这份东西，不是记忆里的意图。
    print("=" * 64)
    print("  审查立场：你此刻是**审稿人**，不是作者。")
    print("  · 稿子下面这份提交物。你只能看它，看不到作者的意图。")
    print("  · 不许用「我本意是…」或「我当时想的是…」为任何一条开脱。")
    print("  · 每条只回答：**这份稿子里看得见吗？** 看不见就是不通过。")
    print("=" * 64)
    print()
    print(f"═══ 待审提交物：{task_id} ═══")
    print(f"标题：{task['title']}")
    print()

    # ── 把产出打出来（这是关键：审眼前的东西，不审记忆）──
    d = store.PROJECT_ROOT / "outputs" / "deliverables" / task_id
    if d.is_dir():
        print("【这份提交物包含以下文件】")
        for f in sorted(d.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                size = f.stat().st_size
                print(f"    {f.name}　（{size/1024:.0f} KB）")
        print()
        # 文本类文件打印摘要（首尾各若干行），供对照
        for f in sorted(d.glob("*.md")):
            body = f.read_text(encoding="utf-8", errors="ignore")
            lines = [l for l in body.splitlines() if l.strip()]
            print(f"  ── {f.name} 的一级标题与结构：")
            for l in lines:
                if l.startswith("#"):
                    print(f"       {l[:78]}")
            print()
    # 把流程图的**内容**也打出来——否则审稿人无法核对「覆盖完整流程」那一条
    # （流程图是 PDF/PNG，清单里看不见文字）
    flow_dir = store.STATE_DIR / "flowcharts"
    found_flow = False
    for cand in (flow_dir, store.PROJECT_ROOT / "flowcharts"):
        if not cand.is_dir():
            continue
        for f in sorted(cand.glob(f"{task_id}*.json")) + sorted(cand.glob("*.json")):
            try:
                spec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not spec.get("phases"):
                continue
            found_flow = True
            print(f"  ── 流程图《{spec.get('title', f.stem)}》的环节与卡片：")
            for ph in spec["phases"]:
                print(f"       {ph.get('label','')} {ph.get('name','')}")
                for c in ph.get("cards", []):
                    print(f"           {c.get('num','')} {c.get('title','')}")
            print()
            break
        if found_flow:
            break
    if not found_flow:
        print("  ⚠️ 没找到流程图定义 JSON —— 审稿人无法核对「覆盖完整流程」这一条。")
        print("     （流程图定义应放在 state/flowcharts/<task_id>.json）")
        print()

    print(f"共 {len(items)} 条检查项。**逐条过，不要跳。**")
    print("规则：全部通过 → 记录 --all-clear；有任何一条不通过 → 记录 --reject，先修再交。")
    print()
    for it in items:
        print(f"  [ ] {it['id']:<12} {it['ask']}")
        print(f"      （来源：{it['source']}）")
    print()
    print("记录方式：")
    print(f"  全部通过：python3 scripts/self_review.py --task {task_id} --record --all-clear")
    print(f"  有打回项：python3 scripts/self_review.py --task {task_id} --record "
          f'--reject "DELIV-3：把两份文档合并了"')
    return 0


def cmd_record(task_id: str, all_clear: bool, rejects: list[str], note: str = "") -> int:
    data = store.load_tasks()
    task = store.find_task(data["tasks"], task_id)
    items = build_items(task, task_id)

    if all_clear and rejects:
        print("错误：--all-clear 与 --reject 不能同时给", file=sys.stderr)
        return 2
    if not all_clear and not rejects:
        print("错误：要么 --all-clear，要么至少给一条 --reject（不许空着不提）", file=sys.stderr)
        return 2

    REC_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "task_id": task_id,
        "reviewed_at": store.now_iso(),
        "items_total": len(items),
        "all_clear": all_clear,
        "rejects": rejects,
        "note": note,
    }
    REC_DIR.joinpath(f"{task_id}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  ✅ 自审已记录：{len(items)} 条，"
          + ("全部通过" if all_clear else f"打回 {len(rejects)} 条"))
    for r in rejects:
        print(f"      ❌ {r}")
    if rejects:
        print()
        print("  ⚠️ 有打回项 → **先修再交付**。修完重新自审。")
        return 1
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="交付前自审：对照清单逐条过，留下打回项")
    ap.add_argument("--task", required=True)
    ap.add_argument("--record", action="store_true", help="记录审查结果")
    ap.add_argument("--all-clear", action="store_true", help="全部通过")
    ap.add_argument("--reject", action="append", default=[], help="打回项（可多次）")
    ap.add_argument("--note", default="", help="补充说明：本轮发现并已修掉的问题（不算打回）")
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    if args.record:
        return cmd_record(args.task, args.all_clear, args.reject, args.note)
    return cmd_build(args.task)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
