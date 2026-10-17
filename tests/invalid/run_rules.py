#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_rules.py —— 反例回归：断言每条规则都能让 validate.py 失败。

做三件事
--------
1. **反例必须失败**：expect.json 里 `kind=fail` 的样本必须让 `validate.py --all` 非零退出，
   并且报出该案例声明的规则 id（只失败但报错规则不对，也算不合格）。
2. **合规样本必须通过**：`kind=pass` 必须 exit 0，且 `absent` 列出的规则**不得**出现
   （防止「收紧规则后误报合法数据」这类回归）；`kind=pass_with_warning` 必须 exit 0
   且报出声明的警告规则 id（例：legacy 字段名的迁移提醒必须可见）。
3. **基线必须通过**：tests/invalid/baseline/ 必须 exit 0——否则样本的失败可能来自别处，
   而不是注入的违规。
3. **备份反例必须失败**：tests/invalid/backups/ 下的样本必须让 `--backup-verify` 非零退出
   并报出 B-HASH / B-RECORDS。

另外检查：整轮回归前后，state/ 的真实数据文件 sha256 与 tests/invalid/ 的样本文件都不得变化
（证明「反例样本放在 tests/invalid/，不污染 state/ 真实数据」，且回归不会自己改样本）。

用法
----
    python3 tests/invalid/run_rules.py                 # 跑全部
    python3 tests/invalid/run_rules.py --only R05      # 只跑名字含 R05 的案例
    python3 tests/invalid/run_rules.py --python <解释器>  # 指定解释器（默认当前解释器）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import store  # noqa: E402

VALIDATE = PROJECT_ROOT / "scripts" / "validate.py"
EXP = PROJECT_ROOT / "scripts" / "exp.py"
# 运行期产物目录（每次回归会重建，不参与「样本未被改动」指纹比对）
RUNTIME_DIRS = ("_seam_run", "_seam_privacy_run")
STATE_DATA_FILES = ("tasks.json", "tasks.jsonl", "user_skills.json", "schema.json")


def fingerprint(paths) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(paths):
        path = Path(path)
        if path.is_file():
            result[str(path.resolve())] = store.sha256_file(path)
    return result


def state_fingerprint() -> dict[str, str]:
    files = []
    for name in STATE_DATA_FILES:
        files.append(store.STATE_DIR / name)
    experience_dir = store.STATE_DIR / "experience"
    if experience_dir.exists():
        files.extend(sorted(experience_dir.glob("*.json")))
    return fingerprint(files)


def samples_fingerprint() -> dict[str, str]:
    files = []
    for path in HERE.rglob("*"):
        if not path.is_file():
            continue
        if any(part in path.parts for part in RUNTIME_DIRS) or any(part.startswith("_seam") for part in path.parts):
            continue
        files.append(path)
    return fingerprint(files)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))


def evidence_lines(text: str, rule: str) -> list[str]:
    return [line for line in text.splitlines() if f"[{rule}]" in line]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="反例回归：证明校验器真的会失败")
    parser.add_argument("--python", default=sys.executable, help="运行 validate.py 的解释器")
    parser.add_argument("--only", help="只跑名称包含该子串的案例")
    parser.add_argument("--validate", type=Path, default=VALIDATE,
                        help="被测 validate.py 路径（默认仓库 scripts/validate.py；仅供变异测试指向副本）")
    args = parser.parse_args(argv[1:])

    validate_script = Path(args.validate).resolve()
    if not validate_script.exists():
        print(f"找不到被测脚本 {validate_script}", file=sys.stderr)
        return 2

    # (名称, 命令, 期望规则或 "" , 说明, kind, absent[, scenario])
    cases: list[tuple] = []

    baseline = HERE / "baseline" / "state"
    if baseline.exists() and (not args.only or "baseline" in args.only):
        cases.append((
            "baseline（合法基线，必须通过）",
            [args.python, str(validate_script), "--all", "--state-dir", str(baseline)],
            "",
            "基线样本 exit 0",
            "pass",
            [],
        ))

    for expect_path in sorted((HERE / "rules").glob("*/expect.json")):
        case_dir = expect_path.parent
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
        name = case_dir.name
        if args.only and args.only not in name:
            continue
        kind = expect.get("kind", "fail")
        label = {
            "fail": f"期望失败：{expect['rule']}",
            "pass": "合规样本：必须通过",
            "pass_with_warning": f"合规样本：必须通过并报警告 {expect.get('rule')}",
        }.get(kind, kind)
        cases.append((
            f"{name}（{label}）",
            [args.python, str(validate_script), "--all", "--state-dir", str(case_dir / "state")],
            expect.get("rule", ""),
            expect.get("why", ""),
            kind,
            list(expect.get("absent", [])),
        ))

    # 显式跳过 / 完整校验 的 CLI 场景（断言「未执行」不会被算成「通过」）
    scenarios = [
        {
            "name": "SC01_显式只选部分域（跳过 methods/experience）→ exit 0 但不得输出「结论：通过」",
            "argv": ["--tasks", "--skills"],
            "exit": 0,
            "contain": ["未选择域", "未执行", "部分校验", "不宣称整体通过"],
            "not_contain": ["结论         : 通过"],
        },
        {
            "name": "SC03_search 冲突必须显式提示（G3）：三对冲突 + 1 条干净经验",
            "script": "exp",
            "argv": ["search", "--query", "竞品研究 汇报 经理",
                     "--experience-dir", "tests/invalid/exp_conflict/state/experience"],
            "exit": 0,
            "contain": ["【适用经验】", "✓ 可采用 1. EXP-20260401-007", "【适用但有冲突的条目】",
                        "⚠ 不得直接采用", "不得直接采用，须先核实",
                        "【冲突提示】", "G3-CONFLICT-ACTION", "G3-CONFLICT-TRIGGER", "G3-CONFLICT-COUNTEREXAMPLE",
                        "证据强度", "条件差异", "建议先核实什么", "不是语义理解"],
            "lines_forbidden": [
                ["✓ 可采用", "EXP-20260401-001"], ["✓ 可采用", "EXP-20260401-002"],
                ["✓ 可采用", "EXP-20260401-003"], ["✓ 可采用", "EXP-20260401-004"],
                ["✓ 可采用", "EXP-20260401-005"], ["✓ 可采用", "EXP-20260401-006"],
            ],
            "count_matches": [["^冲突 \\d+：", 3], ["^  [^\n]*建议先核实什么", 3]],
        },
        {
            "name": "SC04_general 域命中机密特征且未确认 → 必须拒绝（G4）",
            "script": "exp",
            "argv": ["add", "--file", "tests/invalid/exp_payloads/add_general_confidential.json",
                     "--experience-dir", "tests/invalid/exp_privacy/state/experience"],
            "exit": 1,
            "contain": ["【隐私检查】", "G4-PRIVACY-MARKER", "G4-PRIVACY-CUSTOMER", "G4-PRIVACY-METRIC",
                        "拒绝写入", "--privacy-ack", "不能替代人工判断", "客户名称：", "毛利"],
            "not_contain": ["已写入    :"],
        },
        {
            "name": "SC05_general 域命中机密特征 + --privacy-ack → 可真实写入（不阻止使用者）",
            "script": "exp",
            "prepare_copy": ["tests/invalid/exp_privacy", "tests/invalid/_seam_privacy_run"],
            "argv": ["add", "--file", "tests/invalid/exp_payloads/add_general_confidential.json",
                     "--privacy-ack",
                     "--experience-dir", "tests/invalid/_seam_privacy_run/state/experience"],
            "exit": 0,
            "contain": ["【隐私检查】", "已确认", "按使用者的决定继续写入", "不能替代人工判断", "已写入    :"],
            "not_contain": ["拒绝写入"],
            "expect_file": "tests/invalid/_seam_privacy_run/state/experience/EXP-20260402-001.json",
        },
        {
            "name": "SC06_非 general 域（work）不被跨域隐私检查阻断",
            "script": "exp",
            "argv": ["add", "--file", "tests/invalid/exp_payloads/add_work_confidential.json", "--dry-run",
                     "--experience-dir", "tests/invalid/exp_privacy/state/experience"],
            "exit": 0,
            "contain": ["privacy_scope=work", "非 general 域不做跨域泛化检查", "dry-run"],
            "not_contain": ["【隐私检查】", "拒绝写入"],
        },
        {
            "name": "SC07_既有写入门禁未弱化：未执行写成已验证仍被拒（T09）",
            "script": "exp",
            "argv": ["add", "--file", "tests/invalid/exp_payloads/add_unverified_upgrade.json",
                     "--experience-dir", "tests/invalid/exp_privacy/state/experience"],
            "exit": 1,
            "contain": ["拒绝写入", "E-STATUS-CTX", "未执行不得写成已验证経験" if False else "未执行不得写成已验证经验"],
            "not_contain": ["已写入    :"],
        },
        {
            "name": "SC08_数据层隐私警告必须出现（t12 的 E-PRIVACY-GENERAL 不许被静默移除/绕过）",
            "argv": ["--experience", "--state-dir", "tests/invalid/exp_privacy_warn/state"],
            "exit": 0,
            "contain": [
                "E-PRIVACY-GENERAL",
                "EXP-20260501-001",                       # 样本：general + 机密特征
                "命中 G4-PRIVACY-MARKER：title 含机密标记「内部口径」",       # 实际命中位置（三类各一条）
                "命中 G4-PRIVACY-MARKER：context 含机密标记「公司内部」",
                "命中 G4-PRIVACY-CUSTOMER：context 含客户名称或占位符「XX 集团」",
                "命中 G4-PRIVACY-METRIC：context 同时含指标词「毛利率」与具体数值",
                "命中 G4-PRIVACY-MARKER：trigger_conditions[0] 含机密标记「内部指标」",
            ],
            "regex": [r"扫描 [1-9]\d* 条 privacy_scope=general 条目，命中 [1-9]\d* 处"],
            "min_count_matches": [[r"\[警告\] \[E-PRIVACY-GENERAL\]", 12]],
            "lines_forbidden": [
                ["E-PRIVACY-GENERAL", "EXP-20260501-002"],   # general 但全字段干净 → 不得报（防「见 general 就报」）
                ["E-PRIVACY-GENERAL", "EXP-20260501-003"],   # work 域同内容 → 不得报（scope 边界）
            ],
        },
        {
            "name": "SC02_完整 --all（真实 state + 项目根 methods/index.json）→ exit 0 且结论为「通过」",
            "argv": ["--all"],
            "exit": 0,
            "contain": ["方法 methods/index.json", "结论         : 通过"],
            "not_contain": ["未执行       :"],
            "regex": [r"方法 methods/index\.json\s+记录 \d+ 条"],
        },
    ]
    for scenario in scenarios:
        if args.only and args.only not in scenario["name"]:
            continue
        script = EXP if scenario.get("script") == "exp" else validate_script
        cases.append((
            scenario["name"],
            [args.python, str(script), *scenario["argv"]],
            "",
            "",
            "scenario",
            [],
            scenario,
        ))

    index_path = HERE / "backups" / "index.json"
    if index_path.exists():
        for item in json.loads(index_path.read_text(encoding="utf-8"))["cases"]:
            name = f"{item['dir']}（期望失败：{item['rule']}）"
            if args.only and args.only not in name:
                continue
            cases.append((
                name,
                [args.python, str(validate_script), "--backup-verify", "--backup", str(HERE / item["dir"] / "backups" / "20260101T000000Z")],
                item["rule"],
                item.get("why", ""),
                "fail",
                [],
            ))

    if not cases:
        print("没有匹配的案例。先运行 python3 tests/invalid/make_samples.py 生成样本。", file=sys.stderr)
        return 2

    print("=== 反例回归：validate.py 必须对每个违规样本失败 ===")
    print(f"解释器    : {args.python}")
    print(f"样本目录  : {HERE}")
    print()

    state_before = state_fingerprint()
    samples_before = samples_fingerprint()

    failures: list[str] = []
    for case in cases:
        name, cmd, expected_rule, why, kind, absent = case[:6]
        scenario = case[6] if len(case) > 6 else None
        prepared_note = ""
        if scenario and scenario.get("prepare_copy"):
            src, dst = scenario["prepare_copy"]
            src_path, dst_path = (PROJECT_ROOT / src), (PROJECT_ROOT / dst)
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
            prepared_note = f"（已先重建副本 {dst}）"
        result = run(cmd)
        print(f"■ {name}")
        if why:
            print(f"  说明      : {why}")
        print(f"  命令      : {' '.join(cmd)}{prepared_note}")
        print(f"  退出码    : {result.returncode}")

        if kind == "scenario":
            ok = result.returncode == scenario["exit"]
            if not ok:
                failures.append(f"{name}：期望 exit {scenario['exit']}，实际 {result.returncode}")
            for needle in scenario.get("contain", []):
                if needle not in result.stdout:
                    failures.append(f"{name}：输出缺少应有内容「{needle}」")
                    ok = False
            for needle in scenario.get("not_contain", []):
                if needle in result.stdout:
                    failures.append(f"{name}：输出了不该有的内容「{needle}」")
                    ok = False
            for pattern in scenario.get("regex", []):
                if not re.search(pattern, result.stdout):
                    failures.append(f"{name}：输出不匹配应有模式 /{pattern}/")
                    ok = False
            for group in scenario.get("lines_forbidden", []):
                for line in result.stdout.splitlines():
                    if all(needle in line for needle in group):
                        failures.append(f"{name}：出现了不该并列的内容「{' + '.join(group)}」→ {line.strip()[:80]}")
                        ok = False
            for pattern, expected in scenario.get("count_matches", []):
                actual = len(re.findall(pattern, result.stdout, flags=re.MULTILINE))
                if actual != expected:
                    failures.append(f"{name}：/{pattern}/ 期望 {expected} 处，实际 {actual} 处")
                    ok = False
            for pattern, minimum in scenario.get("min_count_matches", []):
                actual = len(re.findall(pattern, result.stdout, flags=re.MULTILINE))
                if actual < minimum:
                    failures.append(
                        f"{name}：/{pattern}/ 至少应有 {minimum} 处（防「警告被静默移除」），实际只有 {actual} 处"
                    )
                    ok = False
                else:
                    print(f"  最小计数  : /{pattern}/ 实际 {actual} 处 ≥ 要求 {minimum} 处 ✅")
            if scenario.get("expect_file"):
                target = PROJECT_ROOT / scenario["expect_file"]
                if not target.exists():
                    failures.append(f"{name}：期望写入的文件不存在 {scenario['expect_file']}")
                    ok = False
                else:
                    print(f"  文件断言  : 已生成 {scenario['expect_file']}（{target.stat().st_size} 字节）")
        elif kind == "fail":
            ok = result.returncode != 0 and f"[{expected_rule}]" in result.stdout
            if result.returncode == 0:
                failures.append(f"{name}：期望非零退出，实际 exit 0（规则未生效！）")
            elif f"[{expected_rule}]" not in result.stdout:
                failures.append(f"{name}：确实失败了，但没有报出预期规则 {expected_rule}")
        elif kind == "pass":
            ok = result.returncode == 0
            if result.returncode != 0:
                failures.append(f"{name}：期望 exit 0，实际 {result.returncode}（合规数据被误报！）")
        else:  # pass_with_warning
            ok = result.returncode == 0 and f"[{expected_rule}]" in result.stdout
            if result.returncode != 0:
                failures.append(f"{name}：期望 exit 0（警告不应导致失败），实际 {result.returncode}")
            elif f"[{expected_rule}]" not in result.stdout:
                failures.append(f"{name}：没有报出应有的警告 {expected_rule}")

        false_positives = [rule for rule in absent if f"[{rule}]" in result.stdout]
        for rule in false_positives:
            failures.append(f"{name}：出现不该有的规则 {rule}（误报）")
            ok = False

        if kind == "scenario":
            hits = [line for line in result.stdout.splitlines() if "结论" in line or "未选择域" in line or "未执行" in line]
        else:
            hits = evidence_lines(result.stdout, expected_rule) if expected_rule else \
                [line for line in result.stdout.splitlines() if line.startswith("结论")]
        for line in hits[:3]:
            print(f"  原始证据  : {line.strip()}")
        if kind == "scenario":
            print(f"  断言      : contain={scenario.get('contain')} not_contain={scenario.get('not_contain')}")
        if absent:
            print(f"  误报检查  : {', '.join(absent)} → {'未出现 ✅' if not false_positives else '出现 ❌'}")
        print(f"  判定      : {'符合预期 ✅' if ok else '不符合预期 ❌'}")
        print()

    state_after = state_fingerprint()
    samples_after = samples_fingerprint()

    state_changed = sorted(set(state_before) | set(state_after))
    state_diff = [p for p in state_changed if state_before.get(p) != state_after.get(p)]
    samples_diff = sorted(p for p in set(samples_before) | set(samples_after)
                          if samples_before.get(p) != samples_after.get(p))

    print("── 副作用检查 ─────────────────────────────────────────────")
    print(f"state/ 真实数据文件 ：{len(state_before)} 个 → 变化 {len(state_diff)} 个")
    for path in state_diff:
        print(f"  ! 发生变化：{path}")
    print(f"tests/invalid 样本  ：{len(samples_before)} 个 → 变化 {len(samples_diff)} 个")
    for path in samples_diff:
        print(f"  ! 发生变化：{path}")
    if state_diff:
        failures.append("state/ 真实数据在回归过程中发生变化（校验器本应只读；请确认是否有其他写入者在并发运行）")
    if samples_diff:
        failures.append("tests/invalid 样本在回归过程中被改动（回归应当只读）")

    print()
    print("── 汇总 ───────────────────────────────────────────────────")
    refuse = sum(1 for case in cases if case[4] == "fail")
    print(f"案例总数  : {len(cases)}（必失败 {refuse} 个 + 必通过 {len(cases) - refuse} 个，其中 legit 基线 1 个）")
    print(f"通过      : {len(cases) - len(failures)}")
    print(f"失败      : {len(failures)}")
    for item in failures:
        print(f"  ! {item}")
    print(f"结论      : {'全部符合预期' if not failures else '存在不符合预期的案例'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(2)
