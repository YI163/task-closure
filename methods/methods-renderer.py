#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""methods/index.md 生成器（methods/index.json 的派生视图）。

来源说明：本脚本原为 t9 交付物 reports/METHOD_RESEARCH.md §9.2 内嵌的 heredoc——
t9 当轮除 methods/ 外的路径不可写，故未落成独立文件，导致 t11 的漂移检查无从调用。
队长按原样（报告第 407–498 行）提取并落成本文件，代码逻辑未经改动，仅新增本文件头。

定位：派生产物生成器。权威数据永远是 methods/index.json；本脚本只读它、只写 methods/index.md。
用法：在项目根目录执行  python3 methods/methods-renderer.py
"""
import hashlib, json, datetime, re, sys

raw = open("methods/index.json","rb").read()
sha = hashlib.sha256(raw).hexdigest()
d = json.loads(raw.decode("utf-8"))

def render(data, source_sha, generated_at):
    L = []
    L.append("<!-- AUTO-GENERATED — 自动生成，请勿手工编辑（DO NOT EDIT BY HAND） -->")
    L.append("# AI 方法/Skill 库索引（自动生成，请勿手工编辑）")
    L.append("")
    L.append("> ⚠️ **本文件是派生产物，不是权威数据。** 方法条目的唯一权威来源是 `methods/index.json`。")
    L.append("> 若本文件与 `methods/index.json` 不一致，**以 JSON 为准**，并重新运行生成命令（见 `reports/METHOD_RESEARCH.md` §9.2）。")
    L.append("> 手工编辑本文件会在下次生成时被覆盖，并造成与权威数据的漂移。")
    L.append("")
    L.append("## 元信息（由生成器写入）")
    L.append("")
    L.append(f"- 生成来源（authoritative source）：`methods/index.json`")
    L.append(f"- 生成来源 SHA256：`{source_sha}`")
    L.append(f"- 生成时间（UTC）：`{generated_at}`")
    L.append(f"- 方法条目数：{len(data['methods'])}")
    L.append("- 生成器：python3 标准库内联脚本（仅读 JSON、只写本文件；命令见报告 §9.2）")
    L.append("- 权威性说明：机器（Skill/脚本）应读 `methods/index.json`；本文件只供人阅读与快速浏览")
    L.append("- 目录")
    for i, m in enumerate(data["methods"], 1):
        L.append(f"  {i}. [{m['name']}](#{i}-{m['method_id']})")
    L.append("")
    for i, m in enumerate(data["methods"], 1):
        s = m["source"]
        L.append(f"## {i}. {m['name']}")
        L.append("")
        L.append(f"- `method_id`: `{m['method_id']}`")
        L.append(f"- **名称**：{m['name']}")
        L.append(f"- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：{'、'.join(m['applicable_task_types'])}")
        L.append(f"- **解决的问题**：{m['problem_solved']}")
        L.append(f"- **预期结果**：{m['expected_outcome']}")
        L.append(f"- **verification_status**：`{m['verification_status']}`（枚举值 `method_verification`；含义见 `state/schema.json`）")
        L.append(f"- **正文（步骤/检查表/模板/失败处理）**：[`methods/{m['method_id']}.md`]({m['method_id']}.md)")
        L.append(f"- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == \"{m['method_id']}\"`")
        L.append("")
        L.append("### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）")
        L.append("")
        for x in m["not_applicable_when"]:
            L.append(f"- {x}")
        L.append("")
        L.append("### 来源")
        L.append("")
        L.append(f"- `source.kind`：`{s['kind']}`")
        L.append(f"- `source.citation`：{s['citation']}")
        L.append(f"- `source.retrieved_at`：`{s['retrieved_at']}`")
        L.append("")
        L.append("### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）")
        L.append("")
        for x in m.get("limitations", []):
            L.append(f"- {x}")
        L.append("")
        L.append("### 相关方法与验收测试")
        L.append("")
        L.append(f"- `related_method_ids`：{'、'.join('`'+x+'`' for x in m.get('related_method_ids', [])) or '（无）'}")
        L.append(f"- `related_test_ids`：{'、'.join('`'+x+'`' for x in m.get('related_test_ids', [])) or '（无）'}")
        L.append(f"- `tool_requirements`：{'; '.join(m.get('tool_requirements', [])) or '（无）'}")
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 生成与一致性校验")
    L.append("")
    L.append("生成命令（在项目根目录执行）：")
    L.append("")
    L.append("```bash")
    L.append("python3 - <<'PY'   # 读取 methods/index.json，重写本文件；脚本见 reports/METHOD_RESEARCH.md §9.2")
    L.append("PY")
    L.append("```")
    L.append("")
    L.append("一致性校验命令与原始输出见 `reports/METHOD_RESEARCH.md` §9.3（比对 `method_id` 集合、缺失/多余条目、重复条目与可重现性）。")
    L.append("")
    return "\n".join(L)

now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
text = render(d, sha, now)
open("methods/index.md","w",encoding="utf-8").write(text)

# 可重现性自检：从文件头取回 generated_at，用同一 JSON 重新渲染并逐字节比对
cur = open("methods/index.md",encoding="utf-8").read()
m = re.search(r"- 生成时间（UTC）：`([^`]+)`", cur)
again = render(d, sha, m.group(1))
print("source_sha256:", sha)
print("generated_at :", now)
print("bytes        :", len(cur.encode("utf-8")))
print("lines        :", cur.count("\n"))
print("regenerate_matches_file:", again == cur)
print("sections(## n.):", len(re.findall(r"^## \d+\. ", cur, re.M)))
print("method_id lines:", len(re.findall(r"^- `method_id`: `[a-z0-9-]+`$", cur, re.M)))
