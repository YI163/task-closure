#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：md2html.py 必须把围栏代码块渲染成 <pre><code>。

为什么单独立这个测试：本项目实测过一次严重 bug——转换器不认识围栏代码块，
把流程图逐行当成段落输出成 <p>，框线全部散掉，用户反馈「完全没有可读性」。
这类渲染错误不会让任何校验器报错，只能靠测试守住。
"""
import pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]

SAMPLE = """# 标题

正文一段。

```
┌──────────┐
│ 中文内容  │
└──────────┘
```

结尾。
"""

def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        src = pathlib.Path(td) / "in.md"
        dst = pathlib.Path(td) / "out.html"
        src.write_text(SAMPLE, encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "md2html.py"), str(src), str(dst)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"转换失败：{r.stderr}"
        h = dst.read_text(encoding="utf-8")

        checks = [
            ("生成 <pre><code> 块", "<pre><code" in h),
            ("无裸围栏被当段落", "<p>```" not in h),
            ("框线字符在 pre 内", "│ 中文内容" in h),
            ("指定等宽字体", "monospace" in h),
            ("中文未被 HTML 转义破坏", "中文内容" in h),
        ]
        failed = [name for name, ok in checks if not ok]
        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")
        print()
        print("结论：" + ("通过" if not failed else f"失败：{failed}"))
        return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
