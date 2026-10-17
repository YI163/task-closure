#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flowchart.py —— 把流程定义渲染成「好看的图」（HTML + PNG + PDF）。

## 为什么有这个工具

用户明确要求过两次：
1. 「别整这种很不好看的这种代码块，来点格式」—— 不要 ASCII 框图
2. 「能不能导出图片之类的」+「这个流程给我整一个文件就好，就 PDF 的」—— 要图片、要 PDF

**但下一个任务里，执行者又手写了 ASCII 框图塞在代码块里——规则写了却没生效。**
根因不是「忘了」，是**规则与检查都在鼓励那个做法**：
  · SKILL.md 里没有这条要求
  · deliver.py 的流程图判据是「含 ┌ 且含 │ 且含 ┬┴├┤」——**等于在要求 ASCII 框图**
所以本工具的目标是：**让「做一张好看的图」变成一条命令，而不是每次手拼字符。**

## 用法

    # 1. 写一个流程定义（JSON）
    python3 scripts/flowchart.py --init my_flow.json     # 生成模板
    # 2. 渲染
    python3 scripts/flowchart.py --spec my_flow.json --out ~/Desktop/任务交付/xxx

输出：`<名字>.html`（源）、`<名字>.png`（2 倍分辨率图）、`<名字>.pdf`（打印/转发）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402

# 浏览器路径**不再写死**：Windows / Linux 上 macOS 路径根本不存在。
# 探测逻辑集中在 store.find_chrome()，可用环境变量 CHROME_PATH 覆盖。
# 实测教训：外部审查者据此指出「Windows 上直接不可用」。

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: #f4f6fa; color: #1c1c1e; padding: 44px 40px 52px; width: 760px;
}
.head { margin-bottom: 30px; }
.head h1 { font-size: 27px; letter-spacing: .5px; margin-bottom: 10px; color: #14213d; }
.head .sub { font-size: 15px; color: #5b6472; line-height: 1.7; }
.head .sub b { color: #b3541e; }

.phase { display: flex; gap: 16px; margin-bottom: 6px; }
.badge {
  flex: 0 0 92px; text-align: center; border-radius: 12px; padding: 14px 6px;
  color: #fff; font-weight: 600; line-height: 1.35; align-self: flex-start;
}
.badge .d { font-size: 13px; opacity: .85; display: block; }
.badge .n { font-size: 22px; }
.cards { flex: 1; display: flex; flex-direction: column; gap: 11px; }
.card {
  background: #fff; border-radius: 11px; padding: 14px 17px;
  box-shadow: 0 1px 3px rgba(16,24,40,.07), 0 1px 2px rgba(16,24,40,.04);
  border-left: 4px solid #cbd5e1;
}
.card .t { font-size: 15.5px; font-weight: 600; margin-bottom: 5px; }
.card .t .num { color: #94a3b8; margin-right: 6px; }
.card .m { font-size: 13.5px; color: #4b5563; line-height: 1.7; }
.card .hint { font-size: 13px; color: #0f766e; margin-top: 6px; line-height: 1.65; }
.card .warn { font-size: 13px; color: #b45309; margin-top: 6px; line-height: 1.65; }
.card.star { border-left-color: #e8a33d; background: #fffdf6; }
.branch { display: flex; gap: 9px; margin-top: 9px; }
.branch div { flex: 1; font-size: 12.5px; padding: 8px 10px; border-radius: 8px; line-height: 1.6; }
.ok { background: #eef7f1; color: #1f6b45; }
.no { background: #fdf2f2; color: #9b2c2c; }
.warnbox { background: #fff8e6; color: #92400e; }

.p1 .badge { background: #2c6bed; } .p1 .card { border-left-color: #2c6bed; }
.p2 .badge { background: #b45309; } .p2 .card { border-left-color: #b45309; }
.p3 .badge { background: #0f766e; } .p3 .card { border-left-color: #0f766e; }
.p4 .badge { background: #6d28d9; } .p4 .card { border-left-color: #6d28d9; }
.p5 .badge { background: #be123c; } .p5 .card { border-left-color: #be123c; }

.arrow { text-align: center; color: #b6c2d2; font-size: 20px; margin: 9px 0 9px 108px; }
.goal {
  margin-top: 22px; background: #14213d; color: #fff; border-radius: 12px;
  padding: 16px 20px; display: flex; gap: 14px; align-items: center;
}
.goal .k { font-size: 13px; opacity: .7; flex: 0 0 auto; }
.goal .v { font-size: 15px; font-weight: 600; line-height: 1.5; }
.foot { margin-top: 18px; font-size: 12.5px; color: #7b8494; line-height: 1.7; }
"""

TEMPLATE = {
    "title": "（标题：这个流程是什么）",
    "subtitle": "（一句话说明目标；用 <b>…</b> 可加粗）",
    "phases": [
        {"style": "p1", "label": "阶段一", "name": "做什么", "cards": [
            {"num": "①", "title": "第一步", "meta": "具体做什么",
             "hint": "为什么要这样做 / 做完什么样算完成", "star": False},
            {"num": "②", "title": "第二步", "meta": "具体做什么",
             "warn": "⚠️ 这一步容易出错的地方", "star": False},
            {"num": "③", "title": "关键一步", "meta": "具体做什么", "star": True,
             "branches": [["ok", "顺利的话 → 怎么走"], ["no", "出问题的话 → 怎么走"]]},
        ]},
        {"style": "p2", "label": "阶段二", "name": "收尾", "cards": [
            {"num": "④", "title": "最后一步", "meta": "具体做什么", "hint": "交付什么"},
        ]},
    ],
    "goal": {"label": "最终交付", "value": "（做完得到什么）"},
    "footnote": "（可选：补充说明，可写多行用 <br> 分隔）",
}


def build_html(spec: dict) -> str:
    L: list[str] = [f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                    f"<style>{CSS}</style></head><body>"]
    head = f'<div class="head"><h1>{spec.get("title", "")}</h1>'
    if spec.get("subtitle"):
        head += f'<div class="sub">{spec["subtitle"]}</div>'
    L.append(head + "</div>")

    phases = spec.get("phases", [])
    for i, ph in enumerate(phases):
        L.append(f'<div class="phase {ph.get("style", "p1")}">')
        L.append(f'<div class="badge"><span class="d">{ph.get("label", "")}</span>'
                 f'<span class="n">{ph.get("name", "")}</span></div>')
        L.append('<div class="cards">')
        for c in ph.get("cards", []):
            L.append(f'<div class="card{" star" if c.get("star") else ""}">')
            num = f'<span class="num">{c["num"]}</span>' if c.get("num") else ""
            L.append(f'<div class="t">{num}{c.get("title", "")}</div>')
            if c.get("meta"):
                L.append(f'<div class="m">{c["meta"]}</div>')
            if c.get("hint"):
                L.append(f'<div class="hint">→ {c["hint"]}</div>')
            if c.get("warn"):
                L.append(f'<div class="warn">{c["warn"]}</div>')
            if c.get("branches"):
                L.append('<div class="branch">')
                for cls, text in c["branches"]:
                    L.append(f'<div class="{cls}">{text}</div>')
                L.append("</div>")
            L.append("</div>")
        L.append("</div></div>")
        if i < len(phases) - 1:
            L.append('<div class="arrow">▼</div>')

    g = spec.get("goal")
    if g:
        L.append(f'<div class="goal"><span class="k">{g.get("label", "最终交付")}</span>'
                 f'<span class="v">{g.get("value", "")}</span></div>')
    if spec.get("footnote"):
        L.append(f'<div class="foot">{spec["footnote"]}</div>')
    L.append("</body></html>")
    return "\n".join(L)


def render(html_path: Path, png_path: Path, pdf_path: Path | None,
           width: int, height: int) -> tuple[bool, str]:
    chrome = store.find_chrome()
    if chrome is None:
        return False, store.chrome_help_text()
    base = [str(chrome), "--headless", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=2", "--default-background-color=FFFFFFFF"]
    r = subprocess.run(base + [f"--screenshot={png_path}",
                               f"--window-size={width},{height}", str(html_path)],
                       capture_output=True, text=True, timeout=120)
    if not png_path.is_file():
        return False, (r.stdout + r.stderr)[-300:]
    if pdf_path:
        subprocess.run(base + [f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                               str(html_path)], capture_output=True, timeout=120)
    return True, ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="把流程定义渲染成好看的图（HTML+PNG+PDF）")
    ap.add_argument("--spec", type=Path, help="流程定义 JSON")
    ap.add_argument("--init", type=Path, help="生成模板 JSON")
    ap.add_argument("--out", type=Path, default=Path.cwd(), help="输出目录")
    ap.add_argument("--name", default=None, help="输出文件名（不含扩展名）")
    ap.add_argument("--width", type=int, default=760)
    ap.add_argument("--height", type=int, default=1200, help="不够会裁切，看防裁检查提示")
    ap.add_argument("--task", help="任务 ID：把定义存到 state/flowcharts/<id>.json，供自审核对")
    args = ap.parse_args(argv[1:])

    if args.init:
        args.init.write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        print(f"  ✅ 模板已生成：{args.init}")
        print("     编辑里面的 title / phases / cards，然后：")
        print(f"     python3 scripts/flowchart.py --spec {args.init} --out <目录>")
        return 0

    if not args.spec:
        print("错误：需要 --spec（流程定义）或 --init（生成模板）", file=sys.stderr)
        return 2
    store.find_project_root()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    name = args.name or spec.get("title", "流程总览")
    name = name.replace("/", "-")[:60]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    html_p, png_p, pdf_p = out / f"{name}.html", out / f"{name}.png", out / f"{name}.pdf"

    html_p.write_text(build_html(spec), encoding="utf-8")
    print(f"  ✅ HTML：{html_p.name}")

    # 同时把定义存到 state/flowcharts/<task_id>.json ——
    # 这样 self_review.py 能把流程图**内容**打给审稿人看，
    # 否则审稿人只看到一个 PDF 文件名，无法核对「覆盖完整流程」那一条。
    if args.task:
        fd = store.STATE_DIR / "flowcharts"
        fd.mkdir(parents=True, exist_ok=True)
        fd.joinpath(f"{args.task}.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  ✅ 定义已存：state/flowcharts/{args.task}.json（供自审核对）")
    ok, err = render(html_p, png_p, pdf_p, args.width, args.height)
    if not ok:
        print(f"  ❌ 渲染失败：{err}", file=sys.stderr)
        return 1
    print(f"  ✅ PNG ：{png_p.name}（{png_p.stat().st_size/1024:.0f} KB）")
    if pdf_p.is_file():
        print(f"  ✅ PDF ：{pdf_p.name}（{pdf_p.stat().st_size/1024:.0f} KB）")

    # 防裁检查（此前吃过亏：窗口高度写死导致大片空白）
    try:
        from PIL import Image
        im = Image.open(png_p)
        w, h = im.size
        bg = im.getpixel((5, h - 5))
        last = h
        for y in range(h - 1, 0, -1):
            if any(abs(im.getpixel((x, y))[0] - bg[0]) + abs(im.getpixel((x, y))[1] - bg[1])
                   + abs(im.getpixel((x, y))[2] - bg[2]) > 12 for x in range(0, w, 40)):
                last = y
                break
        if last >= h - 4:
            print(f"  ⚠️ 内容可能被裁切（内容底 {last} / 图高 {h}）——请加大 --height", file=sys.stderr)
        else:
            print(f"  ✓ 未裁切（留白 {h - last}px）")
    except Exception as exc:
        print(f"  （防裁检查跳过：{exc}）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as e:
        print(f"[StoreError] {e}", file=sys.stderr)
        sys.exit(1)
