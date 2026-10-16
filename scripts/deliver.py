#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deliver.py —— 交付脚本。把「靠记性」的规则变成「不跑这条命令就交不出去」。

为什么需要它：SKILL.md 有 8 条硬前置，实测 8 条全靠自觉，结果 6 次违规。
而唯一被机械强制的一条（executor 字段，写入侧直接拒绝）从未被违反。
结论：规则必须变成可执行的检查，否则等于没写。

本脚本做两件事：
  A. 机械检查（能做自动化的一律自动化，不靠人记）
  B. 判断检查（不能自动化的，必须逐条回答并留痕）

用法：
    python3 scripts/deliver.py check --task TN-20261015-004
    python3 scripts/deliver.py seal  --task TN-20261015-004 --file answers.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

DESKTOP = Path.home() / "Desktop" / "任务交付"
PROJECT = store.PROJECT_ROOT
DELIVERABLES = PROJECT / "outputs" / "deliverables"

# 交付物里出现这些措辞，说明「承诺了动作」，必须配方案
COMMITMENT_PATTERNS = [
    r"建议[^。；\n]{0,20}(做|安排|找|问|联系|索取|核实|确认)",
    r"可以[^。；\n]{0,20}(安排|找|问|联系|索取)",
    r"另[：:]\s*是否",
    r"下一步[^。；\n]{0,10}(安排|联系|索取)",
    r"应当[^。；\n]{0,20}(安排|联系|索取|核实)",
]

# 判断类检查：不能自动化，必须逐条回答
JUDGMENT_CHECKS = [
    ("constraints_checked", "逐条对照过任务的 constraints 字段？交付物是不是建在这些约束上？"),
    ("primary_path_respected", "交付物是否仍然服务于任务声明的 primary_path（没有被后续问答换掉）？"),
    ("promises_have_plans", "交付物里每一句「建议/可以/另：是否」，是否都配了可执行方案？没有配的，是否已删除？"),
    ("nature_correct", "任务性质判断过吗？（这是分析 / 调研 / 执行 / 协调 / 学习？要产出结论还是行动？）"),
    ("uncertainty_marked", "事实 / 推断 / 未知 三者是否区分清楚？有没有把推断写成事实？"),
    ("html_default_respected",
     "本次交付用的是不是 .html（第 ⑦ 条的默认格式）？"
     "如果用了别的格式，是用户**这一次明确要求**的，还是我自己改的？"
     "（实测犯过：一次被要求 PDF，之后擅自全改成 PDF）"),
    ("no_unauthorized_merge",
     "本次交付有没有把「多份独立文档」合并成一个文件？"
     "（用户只要「同一内容少几种格式」，不要「多份文档并成一册」——"
     "实测已犯两次，见 SKILL.md §0 第 11 条）"),
    ("spec_coverage_known",
     "你知道当前规格覆盖率是多少吗？（跑 python3 scripts/spec_coverage.py）"
     "——说「做完了」之前必须先给出这个数字；"
     "「缺口清单走完」不等于「规格全做到」"),
    ("executor_declared", "每一步的执行者是否已声明（user/ai/joint）？AI 代做是否写明理由？"),
]


def die(msg: str) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(2)


def scan_commitments(path: Path) -> list[tuple[int, str]]:
    """扫描交付物里「承诺了动作」的句子。

    注意：这是**模式匹配，不是语义理解**，一定会有误报和漏报。
    它的定位是「提醒人去看」，不是「替人判断」——所以宁可少报也不要乱报
    （项目已有教训：cried-wolf 的提示比不提示更糟）。
    因此主动排除三类明显不是承诺的行：
      · 表格行（表头/表体，通常是清单而不是承诺）
      · 引号内的引用（例如引用自己此前说过的话）
      · 已经在讲「方案/怎么办」的行（说明它已经配了方案）
    """
    SOLUTION_HINTS = ("执行方案", "方案见", "怎么办", "怎么做", "问法", "模板", "清单见", "见配套")
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        # 排除表格行
        if stripped.startswith("|"):
            continue
        # 排除标题行（2026-10-16 修假阳性）
        # 实测误报：行动清单里的小节标题「## ✅ 明确不建议做的」被当成「建议做 X」的承诺。
        # 标题是结构性文本，不是承诺句——与今日已修的 _HAS_DIGIT 同类问题
        # （判据未排除结构性文本 → 假阳性 → 训练人忽略警告）。
        if stripped.startswith("#"):
            continue
        # 排除否定形式（「不建议做」「不要做」不是承诺做）
        if any(neg in stripped for neg in ("不建议", "不要做", "不该做", "勿")) and "建议" in stripped:
            continue
        # 排除已在讲方案的行
        if any(h in stripped for h in SOLUTION_HINTS):
            continue
        # 排除纯引用行（整行以 > 开头且含引号，通常是在引用别人/自己的话）
        if stripped.startswith(">") and ("「" in stripped or '"' in stripped or "」" in stripped):
            continue
        for pat in COMMITMENT_PATTERNS:
            if re.search(pat, stripped):
                hits.append((i, stripped[:100]))
                break
    return hits


def naming_ok(name: str) -> tuple[bool, str]:
    """命名规则：短 + 讲什么放最前 + 不前缀任务 ID。"""
    if name.startswith(("TN-", "EXP-", "SK-")):
        return False, "任务 ID 前缀会占满 Finder 显示宽度，用户分不清文件"
    if len(name) > 25:
        return False, f"过长（{len(name)} 字符 > 25），Finder 里会被截断"
    return True, ""


def check(task_id: str) -> int:
    data = store.load_tasks()
    task = store.find_task(data["tasks"], task_id)
    problems: list[str] = []
    notes: list[str] = []

    print(f"═══ 交付检查：{task_id} ═══")
    print(f"标题：{task['title']}")
    print()

    # ── A. 机械检查 ──────────────────────────────────────────
    print("【A. 机械检查】")

    declared = task.get("deliverables") or []
    actual = sorted(p.name for p in (DELIVERABLES / task_id).glob("*")) if (DELIVERABLES / task_id).is_dir() else []
    if not actual:
        problems.append(f"outputs/deliverables/ 下没有 {task_id} 的交付物")
    else:
        print(f"  ✅ 项目内交付物 {len(actual)} 个")
        for name in actual:
            ok, why = naming_ok(name)
            mark = "✅" if ok else "⚠️"
            print(f"     {mark} {name}" + ("" if ok else f"　← {why}"))

    # 流程图检查（spec/00 阶段1-6 与 spec/01 §5 要求必须给）
    #
    # 【判据方向在 2026-10-15 被纠正——此前判据本身在鼓励错误做法】
    #   第 1 版「含 ┌ 且含 │」→ 任何 ASCII 表格都能冒充（t24 的 N1）
    #   第 2 版「框线 + 箭头」→ 正文里一句「白板 → 站位固定」就能冒充（实测假阳性）
    #   第 3 版「框线 + 分叉符」→ **等于在要求手写 ASCII 框图**，而用户明确说过
    #          「别整这种很不好看的代码块，来点格式」「能不能导出图片」
    #   本版：**只认渲染出来的图（PNG/PDF）**，并**主动拒绝 ASCII 代码块冒充**。
    #   渲染统一走 scripts/flowchart.py（CSS 排版 + Chrome 渲染），不手拼字符。
    task_dir_fc = DELIVERABLES / task_id
    if task_dir_fc.is_dir():
        rendered = [f.name for f in task_dir_fc.glob("*")
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".html")]
        ascii_flow = []
        for f in list(task_dir_fc.glob("*.md")) + list(task_dir_fc.glob("*.html")):
            body = f.read_text(encoding="utf-8", errors="ignore")
            if ("┌" in body and "│" in body
                    and any(s in body for s in ("┬", "┴", "├", "┤", "┼"))):
                ascii_flow.append(f.name)
        if rendered:
            print(f"  ✅ 存在流程图（渲染版：{'、'.join(rendered[:3])}）")
        else:
            problems.append(
                "缺少流程图（渲染版）：spec/00 阶段1-6 与 spec/01 §5 要求必须给。"
                "**请用 scripts/flowchart.py 渲染成 PNG/PDF**，"
                "不要手写 ASCII 框图——用户明确要求过「不要代码块、格式好看、导出图片」"
            )
        if ascii_flow:
            problems.append(
                "发现手写的 ASCII 框图（" + "、".join(ascii_flow) + "）——"
                "用户明确说过不要这种形式。请改用 scripts/flowchart.py："
                "写一个 JSON 流程定义 → CSS 排版 → 渲染成 PNG/PDF"
            )

    # 行动清单检查（SKILL.md §0 第 10 条：交付必须包含「一步一步做什么」的流程文件）
    task_dir = DELIVERABLES / task_id
    if task_dir.is_dir():
        # 判据不能只看文件名（实测假阳性：一个「0-从这里开始（流程总览）.md」是流程图，
        # 却因为文件名以「0-」开头被判成行动清单）。
        # 真正的行动清单要有可勾选步骤，因此要求：文件名命中 **且** 正文含勾选框。
        def _is_action_list(path: pathlib.Path) -> bool:
            n = path.name
            if not ("行动清单" in n or "从这里开始" in n):
                return False
            if path.suffix.lower() not in (".md", ".html"):
                return False
            body = path.read_text(encoding="utf-8", errors="ignore")
            return ("□" in body or "- [ ]" in body or "☐" in body)

        has_guide = any(_is_action_list(p) for p in task_dir.glob("*"))
        if not has_guide:
            name_hit = [p.name for p in task_dir.glob("*")
                        if "行动清单" in p.name or "从这里开始" in p.name]
            if name_hit:
                # 名字命中但内容不合格 —— 只报这一条，不再叠加「缺少文件」
                problems.append(
                    "行动清单文件存在但**正文没有可勾选步骤**（缺 □ 或 - [ ]）："
                    + "、".join(name_hit)
                    + "。第 10 条要求的是可勾选顺序，不是标题里带「行动清单」四个字"
                )
        if not has_guide:
            if not name_hit:
                problems.append(
                    "缺少「行动清单」文件：用户明确要求交付时给出「一步一步做什么」的流程。"
                    "命名建议：`0-从这里开始（行动清单）.md`"
                )
        else:
            print("  ✅ 存在行动清单（一步一步做什么）")

    # 同一内容多种格式检查 —— **查桌面（用户实际看到的地方），不查项目内**
    # 为什么位置很关键（实测纠错）：第一次把这条加在项目内目录上，
    # 结果报「流程总览 → [.html,.pdf,.png]」——但项目内**必须**保留渲染源
    # （PNG 是 PDF 的来源），用户看不到项目内。用户要求「只留一种格式」针对的是**桌面交付目录**。
    if DESKTOP.is_dir():
        import collections as _c
        for d in sorted(x for x in DESKTOP.iterdir() if x.is_dir()):
            _g: dict[str, list[str]] = _c.defaultdict(list)
            for f in d.iterdir():
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in (
                        ".html", ".png", ".pdf", ".jpg", ".svg"):
                    _g[f.stem].append(f.suffix.lower())
            for k, v in _g.items():
                if len(v) > 1:
                    problems.append(
                        f"桌面 {d.name}/ 里「{k}」有 {len(v)} 种格式 {v}——"
                        "用户要求同一内容只留一种（流程图明确要求只留 PDF）"
                    )

    # 合并本检测（SKILL.md §0 第 11 条）
    #
    # 【判据演进三次，前两版都被实测证伪——这段留在这里是为了不再走回头路】
    #   第 1 版：文件名含「合集/完整材料」→ 只查桌面且只匹配名字，**漏过**（实测）
    #   第 2 版：一级标题 ≥2 就报 → **误报** `1-结论（交给老板的）.md`（那本是
    #           「第一页结论 + 第二页依据」，3 个一级标题是**一份文档内部的分节**）
    #   第 3 版：阈值提到 ≥4 → **仍误报** `2-三天怎么做.md`（第一部分/二/三，5 个）
    #   → 结论：**「一级标题数量」区分不了「文档内分节」与「多文档拼接」**，
    #     再怎么调阈值都是错的判据，已放弃。
    #
    #   现版：**让合并这个动作自己留痕**——只有生成合并本的工具会写标记；
    #   合法文档不会有。误报率 0，且真实风险（我用工具合并）必被抓住。
    MERGE_MARK = "<!-- GENERATED-MERGE-BUNDLE"
    if task_dir.is_dir():
        for f in list(task_dir.glob("*.md")) + list(task_dir.glob("*.html")):
            body = f.read_text(encoding="utf-8", errors="ignore")
            if MERGE_MARK in body:
                problems.append(
                    f"{f.name} 带有「合并本」标记——它是把多份文档拼在一起生成的。"
                    "SKILL.md §0 第 11 条：用户要的是「同一内容少几种格式」，"
                    "**不是把多份不同文档并成一个文件**"
                )

    # 行动清单检查（SKILL.md §0 第 10 条：交付必须包含「一步一步做什么」的流程文件）
    task_dir = DELIVERABLES / task_id

    # 同一内容多种格式检查 —— **查桌面（用户实际看到的地方），不查项目内**
    # 为什么位置很关键（实测纠错）：第一次把这条加在项目内目录上，
    # 结果报「流程总览 → [.html,.pdf,.png]」——但项目内**必须**保留渲染源
    # （PNG 是 PDF 的来源），用户看不到项目内。用户要求「只留一种格式」针对的是**桌面交付目录**。
    if DESKTOP.is_dir():
        import collections as _c
        for d in sorted(x for x in DESKTOP.iterdir() if x.is_dir()):
            _g: dict[str, list[str]] = _c.defaultdict(list)
            for f in d.iterdir():
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in (
                        ".html", ".png", ".pdf", ".jpg", ".svg"):
                    _g[f.stem].append(f.suffix.lower())
            for k, v in _g.items():
                if len(v) > 1:
                    problems.append(
                        f"桌面 {d.name}/ 里「{k}」有 {len(v)} 种格式 {v}——"
                        "用户要求同一内容只留一种（流程图明确要求只留 PDF）"
                    )

    # 合并本检测（SKILL.md §0 第 11 条）——**内容级**，不靠文件名
    # 为什么不能只查文件名（实测漏过）：曾造一个「完整材料合集.md」测试样本，
    # 而检测只查桌面、且只匹配文件名关键词 → 漏掉了。
    # 判据：一个文件里出现**多个一级标题**（# ），说明它是把几份文档拼在一起的。
    if task_dir.is_dir():
        for f in list(task_dir.glob("*.md")) + list(task_dir.glob("*.html")):
            body = f.read_text(encoding="utf-8", errors="ignore")
    # 覆盖对照检查：来源里写明的清单，产出里是否都有
    # 背景：用户问「有没有什么能让你做得更好、更准确的办法」——
    # 实测最有效的是「换个角度并排看」，但此前一直依赖用户或审查员来做。
    # 本项把它机械化：没有跑过 coverage_check 或跑出缺口，就不许交付。
    cc_dir = store.PROJECT_ROOT / "state" / "coverage_checks"
    cc_file = cc_dir / f"{task_id}.json"
    if not cc_file.is_file():
        problems.append(
            "没有跑过覆盖对照：请执行 "
            f"`python3 scripts/coverage_check.py --task {task_id} --source \"<来源里写明的清单>\"`"
            "——它把「我的产出」与「来源清单」并排列出，让漏项显形"
        )
    else:
        try:
            import json as _json
            cc = _json.loads(cc_file.read_text(encoding="utf-8"))
            if cc.get("missing"):
                problems.append(
                    "覆盖对照发现缺口：" + "、".join(cc["missing"])
                    + "（来源清单里有，但产出里找不到——确认是真漏还是用词不一致）"
                )
            else:
                print(f"  ✅ 覆盖对照通过（{len(cc.get('source_items', []))} 项来源清单都在产出里）")
        except Exception as exc:
            problems.append(f"覆盖对照记录读取失败：{type(exc).__name__}: {exc}")

    # 自审记录检查（用户提议的「做完一项自我审查一遍」）
    # 设计要点：**不打分**——只产出「打回清单」。理由是实测教训：
    # 一旦有分数，执行者会优化分数而非目标（本会话已把「缺口清单走完」当成「要求全做到」）。
    sr_file = store.STATE_DIR / "self_reviews" / f"{task_id}.json"
    if not sr_file.is_file():
        problems.append(
            "没有跑过交付前自审：请执行 "
            f"`python3 scripts/self_review.py --task {task_id}` 并记录结果"
            "——它对照任务 constraints 与成功标准逐条过，产出打回清单"
        )
    else:
        try:
            import json as _j
            sr = _j.loads(sr_file.read_text(encoding="utf-8"))
            if sr.get("rejects"):
                problems.append(
                    "自审有未清掉的打回项：" + "；".join(sr["rejects"])
                )
            else:
                print(f"  ✅ 自审通过（{sr.get('items_total')} 条全过）")
        except Exception as exc:
            problems.append(f"自审记录读取失败：{type(exc).__name__}: {exc}")

    # 桌面可达性
    if not DESKTOP.exists():
        problems.append(f"桌面交付目录不存在：{DESKTOP}")
    else:
        task_dirs = [d for d in DESKTOP.iterdir() if d.is_dir()]
        print(f"  · 桌面交付目录含 {len(task_dirs)} 个任务分组：{[d.name for d in task_dirs]}")

        # 找该任务相关的 html 文件名是否合规
        htmls = [p.name for d in task_dirs for p in d.glob("*.html")]
        bad = [(n, naming_ok(n)[1]) for n in htmls if not naming_ok(n)[0]]
        if bad:
            for n, why in bad:
                problems.append(f"桌面文件名不合规：{n}（{why}）")
        else:
            print(f"  ✅ 桌面 {len(htmls)} 个文件名全部合规")

    # 承诺扫描
    print()
    print("  ── 承诺扫描（交付物里「建议做 X」的句子）")
    total_commitments = 0
    task_dir = DELIVERABLES / task_id
    for path in (task_dir.glob("*") if task_dir.is_dir() else []):
        if path.suffix != ".md":
            continue
        hits = scan_commitments(path)
        if hits:
            total_commitments += len(hits)
            print(f"     · {path.name}：{len(hits)} 处")
            for line_no, text in hits[:5]:
                print(f"         第 {line_no} 行：{text}")
    if total_commitments == 0:
        print("     （无承诺句）")
    else:
        notes.append(
            f"发现 {total_commitments} 处「承诺了动作」的句子——"
            "必须确认每一处是否配了可执行方案（谁做/问什么/判断标准/怎么记录）"
        )

    # ── B. 判断检查（不能自动化） ────────────────────────────
    print()
    print("【B. 判断检查（不能自动化，必须你逐条回答并留痕）】")
    sealed = task.get("delivery_check") or {}
    unanswered = []
    for key, question in JUDGMENT_CHECKS:
        answer = sealed.get(key)
        if answer is None:
            unanswered.append((key, question))
            print(f"  ⬜ [{key}] {question}")
        else:
            mark = "✅" if answer.get("answer") == "yes" else "❌"
            print(f"  {mark} [{key}] {answer.get('note', '')[:70]}")

    # ── 汇总 ─────────────────────────────────────────────────
    print()
    print("【汇总】")
    if problems:
        print(f"  ❌ 机械检查发现 {len(problems)} 个问题：")
        for p in problems:
            print(f"     · {p}")
    else:
        print("  ✅ 机械检查通过")
    for n in notes:
        print(f"  ⚠️ {n}")
    if unanswered:
        print(f"  ⬜ 还有 {len(unanswered)} 条判断检查未回答——未回答不得交付")
    else:
        print("  ✅ 判断检查全部已回答")

    ok = not problems and not unanswered
    print()
    print("结论：" + ("可以交付" if ok else "不得交付，先解决上面标出的项"))
    return 0 if ok else 1


def seal(task_id: str, answers_path: Path) -> int:
    if not answers_path.exists():
        die(f"答案文件不存在：{answers_path}")
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    data = store.load_tasks()
    task = store.find_task(data["tasks"], task_id)

    record = {}
    for key, question in JUDGMENT_CHECKS:
        entry = answers.get(key)
        if not isinstance(entry, dict) or entry.get("answer") not in ("yes", "no"):
            die(f"答案缺少 {key}，或 answer 不是 yes/no（每条都必须明确回答）")
        record[key] = {
            "answer": entry["answer"],
            "note": entry.get("note", ""),
            "question": question,
            "answered_at": store.now_iso(),
        }
    task["delivery_check"] = record
    store.append_history(task, "deliver", "记录交付前判断检查")
    backup = store.save_tasks(data, f"记录 {task_id} 的交付检查")
    store.append_event(task_id, "deliver_check", {"keys": list(record)})
    print(f"✅ 已记录 {len(record)} 条判断检查")
    print(f"   写前备份：{backup.relative_to(PROJECT)}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="交付前检查（把靠记性的规则变成可执行检查）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="跑交付检查")
    c.add_argument("--task", required=True)
    s = sub.add_parser("seal", help="记录判断检查的答案")
    s.add_argument("--task", required=True)
    s.add_argument("--file", required=True, type=Path)
    args = ap.parse_args(argv[1:])

    store.find_project_root()
    if args.cmd == "check":
        return check(args.task)
    return seal(args.task, args.file)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
