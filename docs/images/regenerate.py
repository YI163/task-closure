#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成 README 里用的图片。

## 为什么有这个脚本

README 里有两张图，其中 `task-card.png` 是**程序真实输出**的渲染图。
如果只把图片提交进仓库、不提交生成方式，那么：
  · 输出格式变了 → 图过期 → 没人知道怎么重做
  · 图片与代码不一致 → 读者被误导

所以图必须**可重现**。本脚本就是那个重现方式。

## 用法

    python3 docs/images/regenerate.py

会在本目录下重写 `how-it-works.png` 与 `task-card.png`。
需要 Chrome（用无头模式渲染 HTML）。

## 两张图分别是什么

| 文件 | 内容 | 来源 |
|---|---|---|
| `how-it-works.png` | 四阶段流程图（建档→计划→跟踪→闭环） | `scripts/flowchart.py` 渲染 |
| `task-card.png`     | 一张真实任务卡的终端输出 | 临时建一个示例任务，跑 `task_show.py`，把输出套终端样式渲染 |

**示例任务是临时造的**（在系统临时目录里，用完即删），不会碰任何真实数据。
"""

from __future__ import annotations

import html
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
PY = sys.executable
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ── 图 1：流程图的定义 ──
FLOWCHART_SPEC = {
    "title": "Task Closure 怎么运转",
    "subtitle": "状态写在文件里，不在对话里——<b>所以换一个会话，它还记得</b>",
    "phases": [
        {"style": "p1", "label": "① 建档", "name": "接收", "cards": [
            {"num": "", "title": "你说一件要做的事",
             "meta": "「下周五前把季度复盘给总监看」",
             "hint": "信息不足时它反问，不硬做——契约规定「信息不足不得建档」"}]},
        {"style": "p2", "label": "② 拆解", "name": "计划", "cards": [
            {"num": "", "title": "写成结构化任务卡",
             "meta": "目标 · 完成标准 · 约束 · 谁用结果 · 决策权限",
             "hint": "原始请求逐字保留，不改写"},
            {"num": "", "title": "拆成步骤，每步九项",
             "meta": "执行者 · 目的 · 产出 · 完成标准 · 耗时 · 前置 · 技能 · 风险 · 沟通点",
             "star": True}]},
        {"style": "p3", "label": "③ 执行", "name": "跟踪", "cards": [
            {"num": "", "title": "你去做，回来说一声",
             "meta": "「做完了 S1」/「卡住了」/「要求变了」",
             "hint": "它先读状态再回答——不许凭对话印象猜"},
            {"num": "", "title": "改一处，自动记一笔",
             "meta": "计划变更留痕：为什么计划不是原来那样",
             "hint": "防止「悄悄改需求」"}]},
        {"style": "p4", "label": "④ 收尾", "name": "闭环", "cards": [
            {"num": "", "title": "验收三问（脚本强制，不能只答一半）",
             "meta": "承诺做了吗 · 交付物合规吗 · <b>原始目标真实现了吗</b>",
             "warn": "第 3 问答「部分实现」时，结论必须是「我方工作已完成，但目标尚待确认」——不许把勾完步骤说成目标达成"},
            {"num": "", "title": "复盘 → 经验入库",
             "meta": "六类教训落成可检索条目，下次动手前先搜",
             "hint": "「无新经验」是合法结果，不为凑数而写"}]},
    ],
    "goal": {"label": "核心", "value": "模糊任务 → 有依据 → 可执行 → 能跟踪 → 可调整 → 最终可验收"},
    "footnote": "全部数据是本地 JSON 文本文件，无任何网络调用。<br>本图由项目自带的 scripts/flowchart.py 渲染生成。",
}

# ── 图 2：示例任务（与 README 描述一致）──
DEMO_TASK = {
    "title": "给团队做一次季度复盘",
    "original_request": "下周五之前，把我们组这个季度的项目情况整理一下，做个复盘给总监看",
    "goal": "产出一份能让总监在 15 分钟内看懂季度进展与问题的复盘材料，并在会上讲清楚",
    "success_criteria": [
        "覆盖本季度 6 个项目的进度、延期原因、人力占用",
        "有数据支撑，不是印象描述",
        "会上能在 15 分钟内讲完，且能接住追问",
    ],
    "domain": "work", "task_type": "writing", "planning_depth": "standard",
    "requester_or_beneficiary": "总监",
    "constraints": [
        "【主路径】数据由本人从项目管理系统导出，AI 负责整理与可视化",
        "总监只看结论页，细节放附件",
        "涉及同事绩效的内容不写进材料",
    ],
    "primary_path": {"description": "本人出数据，AI 做整理与成稿", "decided_by": "user"},
}
DEMO_STEPS = [
    {"step_id": "S1", "name": "导出并核对项目数据", "purpose": "先确保数据是真的，避免后面整轮返工",
     "actions": ["从项目管理系统导出本季度全部项目记录", "与周报交叉核对，标出对不上的项"],
     "required_skills": [{"skill_ref": "取数代码", "gap": "未评估，按 can_with_checklist 对待"}],
     "deliverable": "一份核对过的项目清单", "completion_criteria": "每个项目的进度与人力占用都有来源",
     "executor": "user", "executor_basis": "数据在你手上，AI 拿不到项目管理系统",
     "time_estimate": "40 分钟", "estimate_basis": "按 6 个项目估算",
     "risks_and_fallbacks": ["导出缺字段 → 用周报补齐并标注来源"], "status": "pending",
     "inputs_or_dependencies": ["不适用：本步为首步"],
     "communication": ["不适用：本步无需对外沟通"]},
    {"step_id": "S2", "name": "做成结论页 + 附件", "purpose": "总监只看结论页，所以结论页必须能独立成篇",
     "actions": ["先写结论页（一页）", "再把明细放附件", "标注三处最需要他决策的地方"],
     "required_skills": [{"skill_ref": "撰写正式汇报", "gap": "未评估，按 not_yet 对待，AI 提供结构"}],
     "deliverable": "结论页 + 附件", "completion_criteria": "结论页单独看也能成立",
     "executor": "joint", "executor_basis": "AI 出结构与初稿，本人定口径",
     "time_estimate": "2 小时", "estimate_basis": "含一轮返工",
     "risks_and_fallbacks": ["口径把握不准 → 先出提纲给总监确认再展开"], "status": "pending",
     "inputs_or_dependencies": ["依赖 S1 的核对结果"],
     "communication": ["需与总监确认：结论页要回答哪三个问题"]},
]

TERMINAL_CSS = """*{margin:0;padding:0;box-sizing:border-box}
body{width:920px;background:#1a1d21}
.bar{background:#2c3138;height:44px;padding:0 16px;display:flex;align-items:center;gap:8px}
.dot{width:12px;height:12px;border-radius:50%}
.d1{background:#ff5f57}.d2{background:#febc2e}.d3{background:#28c840}
.title{color:#8b949e;font:13px -apple-system,sans-serif;margin-left:10px}
pre{font:13.5px/22px "SF Mono",Menlo,Consolas,monospace;color:#c9d1d9;
    padding:18px 22px 24px;white-space:pre-wrap;word-break:break-word}
.h{color:#58a6ff;font-weight:600}
.step{color:#d29922;font-weight:600}
.k{color:#7ee787}
.n{color:#79c0ff}
.tag{color:#8b949e}"""

LABELS = ("执行者：", "完成标准：", "产出：", "目的：",
          "预计耗时：", "前置：", "技能：", "风险/备用：", "沟通点：")


def render_html_to_png(doc: str, out: pathlib.Path, width: int, height: int) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp()) / "page.html"
    tmp.write_text(doc, encoding="utf-8")
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=2", "--default-background-color=FF1A1D21",
         f"--screenshot={out}", f"--window-size={width},{height}", str(tmp)],
        capture_output=True, text=True, timeout=120, check=False)


def make_flowchart() -> None:
    spec = pathlib.Path(tempfile.mkdtemp()) / "spec.json"
    spec.write_text(json.dumps(FLOWCHART_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")
    r = subprocess.run([PY, str(REPO / "scripts" / "flowchart.py"),
                        "--spec", str(spec), "--out", str(HERE),
                        "--name", "how-it-works", "--height", "1500"],
                       capture_output=True, text=True)
    if not (HERE / "how-it-works.png").is_file():
        raise SystemExit(f"流程图渲染失败：{r.stdout}{r.stderr}")
    for extra in ("how-it-works.html", "how-it-works.pdf"):
        (HERE / extra).unlink(missing_ok=True)
    print("  ✅ how-it-works.png")


def make_task_card() -> None:
    work = pathlib.Path(tempfile.mkdtemp())
    sandbox = work / "repo"
    shutil.copytree(REPO, sandbox,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "backups"))
    subprocess.run([PY, "scripts/init.py"], cwd=sandbox, capture_output=True)
    (work / "task.json").write_text(json.dumps(DEMO_TASK, ensure_ascii=False), encoding="utf-8")
    subprocess.run([PY, "scripts/task_new.py", "--input", str(work / "task.json")],
                   cwd=sandbox, capture_output=True)

    sys.path.insert(0, str(sandbox / "scripts"))
    import store  # type: ignore
    data = store.load_tasks()
    data["tasks"][-1]["plan"] = DEMO_STEPS
    store.write_json(store.STATE_DIR / "tasks.json", data)
    tid = data["tasks"][-1]["task_id"]

    out = subprocess.run([PY, "scripts/task_show.py", "--task", tid],
                         cwd=sandbox, capture_output=True, text=True).stdout
    lines = out.splitlines()

    def grab(start: str, end: str) -> list[str]:
        s = next((i for i, l in enumerate(lines) if l.startswith(start)), None)
        if s is None:
            raise SystemExit(f"输出里找不到：{start}")
        e = next((i for i, l in enumerate(lines) if i > s and l.startswith(end)), None)
        return lines[s:e] if e else lines[s:]

    body_lines = grab("■ 任务目标", "■ 计划与逐步状态") + \
                 grab("■ 计划与逐步状态", "■ 已完成步骤及证据")
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    def colorize(line: str) -> str:
        e = html.escape(line)
        if line.startswith("■"):
            return f'<span class="h">{e}</span>'
        if line.lstrip().startswith("○"):
            # 状态标签单独染色（用变量拼，避免 f-string 里嵌套引号）
            tag = '<span class="tag">[未开始]</span>'
            return '<span class="step">' + e.replace("[未开始]", tag) + "</span>"
        if line.strip().startswith(("1.", "2.", "3.")):
            return f'<span class="n">{e}</span>'
        for k in LABELS:
            if k in e:
                e = e.replace(k, f'<span class="k">{k}</span>', 1)
        return e

    body = "\n".join(colorize(l) for l in body_lines)
    height = int(44 + 18 + len(body_lines) * 22 + 24)
    doc = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{TERMINAL_CSS}</style>'
           f'</head><body><div class="bar"><span class="dot d1"></span>'
           f'<span class="dot d2"></span><span class="dot d3"></span>'
           f'<span class="title">python3 scripts/task_show.py --task {tid}</span></div>'
           f'<pre>{body}</pre></body></html>')
    render_html_to_png(doc, HERE / "task-card.png", 920, height)
    if not (HERE / "task-card.png").is_file():
        raise SystemExit("任务卡渲染失败")
    print(f"  ✅ task-card.png（示例任务 {tid}，{len(body_lines)} 行）")


def main() -> int:
    if not pathlib.Path(CHROME).is_file():
        print(f"找不到 Chrome：{CHROME}", file=sys.stderr)
        return 1
    print("重新生成 README 图片：")
    make_flowchart()
    make_task_card()
    print(f"\n输出目录：{HERE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
