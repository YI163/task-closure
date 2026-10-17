#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：跨平台路径探测（store.find_chrome / store.delivery_dir）。

## 为什么单独立这个测试

外部审查者指出「Windows 上直接不可用」，根因是两行写死的路径：

    CHROME  = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    DESKTOP = Path.home() / "Desktop" / "任务交付"

改成运行时探测之后，**探测逻辑本身必须被测试守住**——否则下次有人图省事
又写回一个字面量，Windows 用户会静默失效（而不是报错），最难查。

这个测试只验证「逻辑分支」，不要求本机真的装了 Chrome。
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import store  # noqa: E402


def _reset_env() -> None:
    os.environ.pop("CHROME_PATH", None)
    os.environ.pop("NAV_DELIVERY_DIR", None)


def check(condition: bool, label: str, failures: list[str]) -> None:
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        failures.append(label)


def main() -> int:
    failures: list[str] = []
    original_candidates = store.CHROME_CANDIDATES

    try:
        # ── find_chrome ──
        print("find_chrome：")

        # 1. 候选全不存在 → 返回 None（而不是抛异常，出图是可选能力）
        _reset_env()
        store.CHROME_CANDIDATES = ("/nonexistent/definitely-not-here",)
        check(store.find_chrome() is None, "候选都不存在时返回 None，不抛异常", failures)

        # 2. 环境变量覆盖优先级最高
        _reset_env()
        os.environ["CHROME_PATH"] = sys.executable     # 用一个必定存在的文件
        check(store.find_chrome() == pathlib.Path(sys.executable),
              "CHROME_PATH 环境变量优先于候选列表", failures)

        # 3. 环境变量指向不存在的文件 → 继续找候选（不因一个坏配置就放弃）
        _reset_env()
        os.environ["CHROME_PATH"] = "/nonexistent/browser"
        store.CHROME_CANDIDATES = (str(sys.executable),)
        check(store.find_chrome() == pathlib.Path(sys.executable),
              "CHROME_PATH 指向不存在文件时，回落到候选列表", failures)

        # 4. 显式参数优先级最高
        _reset_env()
        explicit = store.find_chrome(explicit=sys.executable)
        check(explicit == pathlib.Path(sys.executable),
              "显式参数优先于一切", failures)

        # 5. 显式参数指向不存在文件 → None（不静默改用别的浏览器）
        _reset_env()
        check(store.find_chrome(explicit="/nonexistent/x") is None,
              "显式参数无效时返回 None（不偷偷换一个）", failures)

        # 6. 找不到时的提示必须具体（含环境变量做法与 PowerShell 写法）
        text = store.chrome_help_text()
        check("CHROME_PATH" in text, "提示里给了 CHROME_PATH 的做法", failures)
        check("PowerShell" in text, "提示里给了 PowerShell 写法（Windows 用户需要）", failures)
        check("不需要" in text or "不依赖" in text, "提示里说明了核心功能不依赖它", failures)

        # ── delivery_dir ──
        print("delivery_dir：")

        _reset_env()
        default = store.delivery_dir()
        check(default == pathlib.Path.home() / "Desktop" / "任务交付",
              "默认仍是 ~/Desktop/任务交付（不改变现有用户的行为）", failures)

        _reset_env()
        os.environ["NAV_DELIVERY_DIR"] = "/tmp/custom-delivery"
        check(store.delivery_dir() == pathlib.Path("/tmp/custom-delivery"),
              "NAV_DELIVERY_DIR 可覆盖", failures)

        # 支持 ~ 展开（用户会写 ~/Documents/交付）
        _reset_env()
        os.environ["NAV_DELIVERY_DIR"] = "~/Documents/交付"
        resolved = store.delivery_dir()
        check(resolved == pathlib.Path.home() / "Documents" / "交付",
              "~ 会被展开（不返回字面量带波浪号的路径）", failures)

    finally:
        store.CHROME_CANDIDATES = original_candidates
        _reset_env()

    print()
    if failures:
        print(f"❌ {len(failures)} 项失败：")
        for f in failures:
            print(f"   · {f}")
        return 1

    print("✅ 跨平台路径探测：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
