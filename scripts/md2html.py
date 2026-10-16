#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把交付物 Markdown 转成可直接双击打开的 HTML。

为什么需要它：用户的交付物放在桌面，双击 .md 在 macOS 上不一定能打开，
而 textutil 转出的 HTML 不支持 Markdown 表格（表格会散成一行行文字）。
本脚本用 Python 标准库实现一个最小但够用的 Markdown 渲染器：
标题 / 表格 / 加粗 / 列表 / 引用块 / 分隔线 / 行内代码，并带中文友好样式。
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

CSS = """
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  max-width: 860px; margin: 0 auto; padding: 32px 24px 80px;
  line-height: 1.75; font-size: 16px;
  background: #fdfdfc; color: #1c1c1e;
}
h1 { font-size: 26px; border-bottom: 3px solid #2c6bed; padding-bottom: 10px; margin-top: 8px; }
h2 { font-size: 21px; margin-top: 34px; border-left: 5px solid #2c6bed; padding-left: 12px; }
h3 { font-size: 18px; margin-top: 26px; color: #2c3e50; }
h4 { font-size: 16px; margin-top: 20px; color: #444; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 15px; }
th, td { border: 1px solid #d7dbe0; padding: 8px 11px; text-align: left; vertical-align: top; }
th { background: #eef3fb; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
blockquote {
  margin: 16px 0; padding: 12px 16px; background: #fff8e6;
  border-left: 5px solid #e8a33d; border-radius: 0 6px 6px 0;
}
code { background: #f0f2f5; padding: 2px 6px; border-radius: 4px; font-size: 14px;
       font-family: "SF Mono", Menlo, Consolas, monospace; }
pre { background: #f6f8fa; padding: 14px; border-radius: 8px; overflow-x: auto;
      font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace;
      font-size: 13px; line-height: 1.45; white-space: pre; }
pre code { font-family: inherit; }
pre code { background: none; padding: 0; }
hr { border: none; border-top: 1px dashed #c8ccd2; margin: 30px 0; }
ul, ol { padding-left: 26px; }
li { margin: 5px 0; }
strong { color: #14213d; }
a { color: #2c6bed; }
.meta { color: #6b7280; font-size: 14px; margin-bottom: 24px; }
@media print {
  body { max-width: none; padding: 0; }
  h1, h2, h3 { page-break-after: avoid; }
  table, pre, blockquote { page-break-inside: avoid; }
  img { page-break-inside: avoid; page-break-before: auto; }
  a { color: inherit; text-decoration: none; }
}
"""


IMAGE_BASE: Path | None = None


def inline(text: str) -> str:
    """行内元素：先转义 HTML，再处理加粗、行内代码、链接。"""
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?[\s:|-]+\|?", line.strip())) and "-" in line


def convert(markdown: str, title: str) -> str:
    lines = markdown.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 围栏代码块（``` ... ```）——必须先于其它规则判断，
        # 否则流程图/示意图会被逐行当成段落，框线全部散掉（这是本项目实测到的 bug）
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            code = html.escape("\n".join(body), quote=False)
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        # 图片：![](路径) —— 内嵌为 base64，这样 HTML 单文件就能看，不必再开别的文件。
        # 用户反馈：「有了图就直接把图放这里，而不是整一个文件名让人自己打开，很麻烦」
        mimg = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if mimg:
            alt, raw_src = mimg.group(1), mimg.group(2)
            path = Path(raw_src)
            if not path.is_absolute() and IMAGE_BASE is not None:
                path = (IMAGE_BASE / path).resolve()
            if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}[
                            path.suffix.lower().lstrip(".")]
                import base64
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                out.append(f'<p><img src="data:{mime};base64,{data}" alt="{html.escape(alt)}" '
                           f'style="max-width:100%;height:auto;border:1px solid #e2e8f0;'
                           f'border-radius:10px"></p>')
                i += 1
                continue

        # 表格
        if stripped.startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            header = split_row(stripped)
            out.append("<table><thead><tr>")
            out.extend(f"<th>{inline(c)}</th>" for c in header)
            out.append("</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_row(lines[i])
                out.append("<tr>")
                out.extend(f"<td>{inline(c)}</td>" for c in cells)
                out.append("</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            out.append("<hr>")
            i += 1
            continue

        # 引用块
        if stripped.startswith(">"):
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(b) for b in block) + "</blockquote>")
            continue

        # 列表
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>")
            while i < len(lines):
                s = lines[i].strip()
                mm = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", s)
                if not mm:
                    break
                out.append(f"<li>{inline(mm.group(1))}</li>")
                i += 1
            out.append(f"</{tag}>")
            continue

        # 空行
        if not stripped:
            i += 1
            continue

        # 普通段落
        out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    body = "\n".join(out)
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("用法：md2html.py <输入.md> <输出.html>", file=sys.stderr)
        return 2
    global IMAGE_BASE
    src, dst = Path(argv[1]), Path(argv[2])
    IMAGE_BASE = src.parent
    text = src.read_text(encoding="utf-8")
    dst.write_text(convert(text, src.stem), encoding="utf-8")
    print(f"{src.name} → {dst.name}（{dst.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
