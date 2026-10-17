#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：流程图渲染不得用「旧文件存在」冒充「本次生成成功」。

## 防止什么问题

审查报告 P1-3：旧 `render()` 在 Chrome 跑完后只看 `png_path.is_file()`。
目录里若有上一次成功留下的 PNG，本次渲染即使失败也会被判成功；PDF 更是
连返回码都不看。对一个把「证据」当核心的工具，这等于伪造证据。

本测试模拟 Chrome（monkeypatch `subprocess.run`），断言：

1. 预先放旧 PNG/PDF + 本次失败 → 必须返回失败，且旧文件不能被当成证据留下；
2. PNG 成功、PDF 失败 → 必须失败并明确指出是 PDF；
3. 两者都成功 → 文件存在且非空；
4. 渲染失败时脚本 main() 必须返回非零退出码。
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import flowchart  # noqa: E402


def check(condition: bool, label: str, failures: list[str], detail: str = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}" + (f"（{detail}）" if detail else ""))
    if not condition:
        failures.append(label)


def make_fake(png_ok: bool, pdf_ok: bool, png_rc: int = 0, pdf_rc: int = 0, capture=None):
    """假 Chrome：按参数决定写不写文件、返回什么退出码。"""

    def fake(cmd, **_kwargs):
        args = [str(item) for item in cmd]
        screenshot = next((a for a in args if a.startswith("--screenshot=")), None)
        if screenshot is not None:
            out = screenshot.split("=", 1)[1]
            if capture is not None:
                capture["png"] = out
            if png_ok:
                pathlib.Path(out).write_bytes(b"\x89PNG\r\n\x1a\nfake-image")
            return subprocess.CompletedProcess(cmd, png_rc, "stdout", "stderr: png")
        pdf = next((a for a in args if a.startswith("--print-to-pdf=")), None)
        if pdf is not None:
            out = pdf.split("=", 1)[1]
            if capture is not None:
                capture["pdf"] = out
            if pdf_ok:
                pathlib.Path(out).write_bytes(b"%PDF-1.4 fake-pdf")
            return subprocess.CompletedProcess(cmd, pdf_rc, "stdout", "stderr: pdf")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return fake


def render_with(tmp: pathlib.Path, fake, failures: list[str], label: str):
    html = tmp / "flow.html"
    html.write_text("<html></html>", encoding="utf-8")
    png = tmp / "flow.png"
    pdf = tmp / "flow.pdf"
    original_run = flowchart.subprocess.run
    original_find = flowchart.store.find_chrome
    try:
        flowchart.subprocess.run = fake
        flowchart.store.find_chrome = lambda *a, **k: pathlib.Path(sys.executable)
        return flowchart.render(html, png, pdf, 760, 1200), png, pdf
    finally:
        flowchart.subprocess.run = original_run
        flowchart.store.find_chrome = original_find


def main() -> int:
    failures: list[str] = []

    # 1) 旧产物 + 本次失败：不能成功，旧文件也不能留下
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        (tmp / "flow.png").write_bytes(b"OLD-PNG")
        (tmp / "flow.pdf").write_bytes(b"OLD-PDF")
        (ok, error), png, pdf = render_with(tmp, make_fake(False, False, png_rc=1), failures, "case1")
        check(ok is False and "PNG" in error, "旧 PNG/PDF 存在时，渲染失败必须判失败并指明 PNG",
              failures, error[:120])
        check(not png.exists() and not pdf.exists(), "失败后旧的 PNG/PDF 不能冒充本次产物", failures)

    # 2) PNG 成功、PDF 子进程失败：必须失败并指明 PDF
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        (ok, error), png, pdf = render_with(tmp, make_fake(True, False, pdf_rc=1), failures, "case2")
        check(ok is False and "PDF" in error, "PNG 成功但 PDF 失败时必须判失败并指明 PDF",
              failures, error[:120])
        check(png.is_file() and png.stat().st_size > 0, "PNG 已成功生成（本次产物保留）", failures)
        check(not pdf.exists(), "PDF 失败时不得留下 PDF 文件", failures)

    # 3) 两者都成功：结果存在且非空；临时路径必须保留真实扩展名
    #    （真实 Chrome 靠后缀判断格式：`x.png.part` 会直接报
    #     "Unsupported screenshot image file type: .part"）
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        capture: dict[str, str] = {}
        (ok, error), png, pdf = render_with(tmp, make_fake(True, True, capture=capture), failures, "case3")
        check(ok is True and not error, "PNG/PDF 都成功时返回成功", failures, repr(error))
        check(png.is_file() and png.stat().st_size > 0 and pdf.is_file() and pdf.stat().st_size > 0,
              "成功后两个文件都存在且非空", failures)
        check(capture.get("png", "").endswith(".png") and capture.get("pdf", "").endswith(".pdf"),
              "交给 Chrome 的临时文件保留 .png/.pdf 扩展名", failures, repr(capture))

    # 4) main() 在渲染失败时返回非零退出码
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        spec = tmp / "spec.json"
        spec.write_text(json.dumps({"title": "样本", "phases": [], "goal": None}, ensure_ascii=False),
                        encoding="utf-8")
        out = tmp / "out"
        original_render = flowchart.render
        stderr = io.StringIO()
        try:
            flowchart.render = lambda *a, **k: (False, "PNG 渲染失败：模拟")
            with contextlib.redirect_stderr(stderr):
                code = flowchart.main(["flowchart.py", "--spec", str(spec), "--out", str(out)])
        finally:
            flowchart.render = original_render
        check(code != 0, "渲染失败时 main() 返回非零退出码", failures, f"exit={code}")
        check("PNG" in stderr.getvalue() and "失败" in stderr.getvalue(),
              "main() 的错误信息指明失败格式", failures, stderr.getvalue().strip()[:120])

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
