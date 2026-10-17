#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exp.py —— 领域经验库：检索（带适用性判断）/ 写入（带证据门禁）/ 复核（留历史）。

用法
----
    python3 scripts/exp.py search --query "对比三家竞品并汇报" [--domain work] [--task-type research] [--limit 3]
    python3 scripts/exp.py add    --file entry.json [--dry-run]
    python3 scripts/exp.py review --id EXP-20261015-001 --status repeatedly_supported --note "第二次独立观察"

硬规则（脚本强制，不靠模型自觉）
------------------------------
* **未执行不得写成已验证**：observed_outcome.executed=false 时 status 只能是 to_verify；
  single_observation / repeatedly_supported 必须 executed=true 且有证据（spec/03 §8、T09）。
* **未执行不得写结果性结论**：executed=false 时出现「显著提升效率」这类词会被拒绝（E-CLAIM）。
* **写入门禁复用校验器规则**：add 直接调用 validate.py 的单条经验规则，只有零错误才写入；
  因此 exp.py 与 validate.py 不会出现两套判断标准。
* **冲突必须显式提示（G3）**：search 对互相矛盾的适用经验单列【冲突提示】，写明双方证据强度、
  条件差异与「建议先核实什么」；这类条目用「⚠ 不得直接采用」标记，**不与可采用条目并列**。
* **隐私有强制点但不假装完备（G4）**：privacy_scope=general 且命中高置信度机密特征时，
  add 警告并要求 --privacy-ack 才写入；自动检测只能拦截明显情形，**不能替代人工判断**，
  也不会阻止使用者明确确认后写入。
* **只增不改**：写入前 store.create_backup；复核把历史追加进 review_history，不覆盖旧值。

关于 --experience-dir（测试接缝）
--------------------------------
默认读写 state/experience/。指定 --experience-dir 时改用该目录（例如

t18：接缝模式的**写前备份落在接缝自己的同级 backups/**（或用 --backup-dir 显式指定），
不再写正式 state/backups/；若落点指向正式备份目录会明确报错而不是静默回落。
默认读写 state/experience/ 时行为不变。指定 --experience-dir 时改用该目录（例如
tests/invalid/exp_seam/state/experience），用于在不触碰真实用户数据的前提下验证
写入/复核/排除逻辑；此时交叉引用按该目录所属的 state 树校验（找不到就退回真实 state/）。
真实路径一律走 store.save_experience，不绕过 store.py。

退出码：0=成功（检索为空也算成功）；1=数据问题或门禁拒绝；2=用法错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402
import validate as validator  # noqa: E402

EXP_STATUS_ZH = {
    "to_verify": "待验证（计划/假设，未被实际执行）",
    "single_observation": "单次观察",
    "repeatedly_supported": "重复支持",
    "challenged_by_counterexample": "被反例挑战",
    "obsolete": "已失效",
}

# 中文虚词/功能词片段：避免「需要」「可以」这类高频片段制造假相关
STOP_GRAMS = {
    "的时", "时候", "如果", "需要", "可以", "进行", "以及", "并且", "但是", "一个", "我们",
    "这个", "那个", "是否", "没有", "不是", "就是", "而且", "然后", "因为", "所以", "这些",
    "那些", "任何", "什么", "怎么", "如何", "为了", "对于", "关于", "以及", "或者", "可能",
    "使用", "情况", "问题", "方法", "时候", "这样", "那样", "已经", "还是", "比较",
}

# ---------------------------------------------------------------- 规则清单（供报告与断言引用）
EXP_RULES: dict[str, str] = {
    "G3-CONFLICT-ACTION": "两条经验的 recommended_action 语义相反（同一做法一侧被否定，或使用相反措辞）",
    "G3-CONFLICT-TRIGGER": "两条经验的 trigger_conditions 互斥（同一条件一侧被否定，或含互斥词对）",
    "G3-CONFLICT-COUNTEREXAMPLE": "一条经验的 counterexamples 指向另一条的结论（共享显著片段或直接引用 id）",
    "G4-PRIVACY-MARKER": "privacy_scope=general 且正文命中机密标记（公司内部 / 未公开 / 保密 / 受控…）",
    "G4-PRIVACY-CUSTOMER": "privacy_scope=general 且正文命中客户名称或其占位符",
    "G4-PRIVACY-METRIC": "privacy_scope=general 且同一字段内同时出现经营指标词与具体数值",
}

# 否定词：用于判断「同一做法的相反表述」
NEGATION_MARKERS = ("不要", "不得", "不应", "不必", "避免", "禁止", "切勿", "先别", "别", "不宜", "无需", "不用")
# 做法层面的相反措辞（两侧各出现一个才算）
ACTION_ANTONYMS = (("先", "直接"), ("确认", "跳过"), ("压缩", "扩大"), ("减少", "增加"), ("缩短", "延长"), ("放弃", "坚持"))
# 条件层面的互斥词对
CONDITION_ANTONYMS = (
    ("齐全", "缺失"), ("齐全", "不全"), ("完整", "不全"), ("充裕", "紧张"), ("充裕", "紧"),
    ("充足", "不足"), ("简单", "复杂"), ("单次", "多次"), ("稳定", "多变"), ("宽裕", "紧迫"),
    ("可核实", "无法核实"),
)

# 高置信度机密特征（只覆盖明显情形，不保证完备）
PRIVACY_MARKERS = (
    "公司内部", "内部资料", "内部数据", "内部指标", "内部口径", "内部使用", "仅限内部", "内部机密",
    "未公开", "尚未公开", "未对外公开", "未对外", "保密", "机密", "受控", "商密", "禁止外传",
)
PRIVACY_CUSTOMER_PATTERNS = (
    r"客户名称?\s*[:：]", r"客户\s*[:：]\s*\S", r"(?:XX|xx|某某|某大型|某知名|某头部)\s*(?:公司|集团|企业)",
    r"<客户名>", r"【客户名】",
)
PRIVACY_METRICS = (
    "营收", "营业收入", "毛利", "毛利率", "净利", "利润", "成本", "预算", "薪资", "工资", "薪酬",
    "离职率", "留存率", "转化率", "客单价", "回款", "应收", "库存", "产能", "市占率", "份额", "内部指标",
)
# 「具体数值」的判据（2026-10-16 改严——此前只查「有没有数字」，误报三次）
#
# 旧判据 `re.compile(r"\d")` 把引用编号也当成数值，实测误报：
#   · 「spec/00 不要做#2」→ 命中（那是规范章节号，不是经营数据）
#   · 「EXP-20261015-003」→ 命中（那是本条目的 ID 格式）
#   · 「2026-06 判例」→ 命中（那是日期）
# 改严后的判据：数字必须**带度量信号**才算具体数值——
#   ① 带单位/百分号/货币：20万元、42.5%、3亿、5 天、100 人
#   ② 带小数的数：42.5（纯章节号不会写成小数）
#   ③ 纯数字串 ≥3 位且**不紧邻** - / 与字母数字混合的 ID（避开 2026-06 / EXP-20261015-003）
# 宁可略宽也不要重蹈「只查有没有数字」的假阳性——G4 的定位是「提示人工确认」，不是精确判定。
_HAS_DIGIT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万|亿|千|百|元|块|美元|人民币|%|％|人|个|天|小时|分钟|次|倍)"
    r"|\d+\.\d+"
    r"|(?<![\dA-Za-z-])\d{3,}(?![\dA-Za-z-])"
)

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
ASCII_WORD = re.compile(r"[a-z0-9_]{2,}")


def tokens_of(text: str, max_run: int = 60) -> set[str]:
    """把文本切成「关键词集合」：ASCII 词 + 中文 2~4 字片段（去高频虚词）。"""
    text = str(text or "")
    tokens = set(ASCII_WORD.findall(text.lower()))
    for run in CJK_RUN.findall(text):
        run = run[:max_run]
        for size in (2, 3, 4):
            for index in range(len(run) - size + 1):
                gram = run[index:index + size]
                if gram in STOP_GRAMS:
                    continue
                tokens.add(gram)
    return tokens


def split_tags(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        parts = re.split(r"[,\s，、;；]+", value)
    else:
        parts = list(value)
    return {str(part).strip() for part in parts if str(part).strip()}


# ---------------------------------------------------------------- 读取经验

def resolve_context(args) -> tuple[Path, Path]:
    """返回 (经验目录, 用于交叉引用校验的 state 树)。"""
    if args.experience_dir:
        directory = Path(args.experience_dir).resolve()
        candidate = directory.parent
        if (candidate / "tasks.json").exists() or (candidate / "user_skills.json").exists():
            return directory, candidate
        return directory, store.STATE_DIR
    return store.EXPERIENCE_DIR, store.STATE_DIR


def load_entries(directory: Path) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    problems: list[str] = []
    if not directory.exists():
        return entries, problems
    for path in sorted(directory.glob("*.json")):
        try:
            data = store.read_json(path)
        except store.StoreError as exc:
            problems.append(f"{path.name}：{exc}")
            continue
        if isinstance(data, dict):
            data["_file"] = str(path)
            entries.append(data)
        else:
            problems.append(f"{path.name}：顶层不是 JSON 对象")
    return entries, problems


# ---------------------------------------------------------------- search

def score_entry(entry: dict, query_tokens: set[str], domain: str | None,
                task_type: str | None, want_tags: set[str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    tag_hits = sorted(query_tokens & tokens_of(" ".join(map(str, entry.get("tags") or []))))
    if tag_hits:
        points = min(3 * len(tag_hits), 9)
        score += points
        reasons.append(f"标签命中「{ '、'.join(tag_hits[:3]) }」+{points}")

    title_hits = sorted(query_tokens & tokens_of(entry.get("title") or ""))
    if title_hits:
        points = min(2 * len(title_hits), 4)
        score += points
        reasons.append(f"标题命中「{ '、'.join(title_hits[:3]) }」+{points}")

    trigger_hits = sorted(query_tokens & tokens_of(" ".join(map(str, entry.get("trigger_conditions") or []))))
    if trigger_hits:
        points = min(2 * len(trigger_hits), 6)
        score += points
        reasons.append(f"适用条件命中「{ '、'.join(trigger_hits[:3]) }」+{points}")

    body = " ".join(str(entry.get(key) or "") for key in ("conclusion", "recommended_action", "reasoning", "context"))
    body_hits = sorted(query_tokens & tokens_of(body))
    if body_hits:
        points = min(len(body_hits), 3)
        score += points
        reasons.append(f"结论/做法命中「{ '、'.join(body_hits[:3]) }」+{points}")

    if domain and entry.get("domain") == domain:
        score += 2
        reasons.append(f"领域一致（{domain}）+2")
    if task_type and entry.get("task_type") == task_type:
        score += 2
        reasons.append(f"任务类型一致（{task_type}）+2")

    extra = sorted(want_tags & tokens_of(" ".join(map(str, entry.get("tags") or []))))
    if extra:
        score += 3 * len(extra)
        reasons.append(f"指定标签命中「{ '、'.join(extra[:3]) }」+{3 * len(extra)}")

    return score, reasons


def classify(entry: dict, domain: str | None, task_type: str | None) -> tuple[bool, str]:
    """返回 (是否适用, 不适用/排除原因)。"""
    status = entry.get("status")
    outcome = entry.get("observed_outcome") or {}
    executed = outcome.get("executed") if isinstance(outcome, dict) else None
    evidence = entry.get("evidence") or []

    if status == "obsolete":
        reason = "已失效（obsolete）"
        if entry.get("limitations"):
            reason += f"：{entry['limitations'][0]}"
        return False, reason
    if status == "challenged_by_counterexample":
        counter = entry.get("counterexamples") or []
        return False, "被反例挑战（challenged_by_counterexample）" + (f"：{counter[0]}" if counter else "：未记录具体反例")
    if status == "to_verify" or executed is False:
        return False, "仅有未验证假设：计划从未执行（executed=false），不可当作已验证经验使用"
    if not evidence:
        return False, "没有证据记录（evidence 为空）"

    today = store.now_iso()[:10]
    review_after = entry.get("review_after")
    if review_after and str(review_after)[:10] < today:
        return False, f"已超过复核期（review_after={review_after}，今天 {today}）——需重新复核后才可用"

    if domain and entry.get("domain") != domain:
        return False, f"条件不匹配：领域 {entry.get('domain')} ≠ 本次 {domain}，且触发条件与本次线索无交集"
    if task_type and entry.get("task_type") != task_type:
        return False, f"条件不匹配：任务类型 {entry.get('task_type')} ≠ 本次 {task_type}，且触发条件与本次线索无交集"
    return True, ""


def _negated(text: str) -> bool:
    return any(marker in text for marker in NEGATION_MARKERS)


def _text_of(value) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value)
    return str(value or "")


def _long_shared(shared: set[str]) -> list[str]:
    """shared 里的 4 字中文片段（「同一件事」才会长片段重合，词表碰撞不会）。"""
    return [gram for gram in shared if len(gram) == 4 and CJK_RUN.fullmatch(gram)]


def _action_conflict(a: dict, b: dict) -> str | None:
    """recommended_action 语义相反（否定不对称 / 相反措辞）。"""
    ta, tb = str(a.get("recommended_action") or ""), str(b.get("recommended_action") or "")
    if not ta or not tb:
        return None
    shared = tokens_of(ta) & tokens_of(tb)
    # 否定分支（v0.1.3 修误报）：同领域经验天然共享「单独/痛点/验证/机制」这类 2 字片段，
    # 只看「≥2 个共享片段 + 否定不对称」几乎恒真——实测 4 对互不相干的经验被判
    # G3-CONFLICT-ACTION，其中两对还是同一批写入的互补条目，等于把经验库封掉。
    # 真冲突（「先与经理确认研究范围…」vs「不要先与经理确认研究范围…」）会共享
    # 大量 4 字连续片段（实测 8 个）；词表碰撞不会。因此否定分支额外要求
    # 至少一个 4 字中文共享片段。
    if len(shared) >= 2 and _negated(ta) != _negated(tb) and _long_shared(shared):
        return f"同一做法一侧被否定（共享片段：{'、'.join(sorted(shared)[:4])}）：「{ta}」vs「{tb}」"
    # 相反措辞：要求两侧各自只含词对中的一侧，且确有共享片段（否则会把不相关做法误判为冲突）
    if shared:
        for left, right in ACTION_ANTONYMS:
            left_only_a = left in ta and right not in ta
            right_only_b = right in tb and left not in tb
            right_only_a = right in ta and left not in ta
            left_only_b = left in tb and right not in tb
            if (left_only_a and right_only_b) or (right_only_a and left_only_b):
                return f"做法使用相反措辞（{left} / {right}）：「{ta}」vs「{tb}」"
    return None


def _trigger_conflict(a: dict, b: dict) -> str | None:
    """trigger_conditions 互斥（一侧被否定 / 含互斥词对）。"""
    ta, tb = _text_of(a.get("trigger_conditions")), _text_of(b.get("trigger_conditions"))
    if not ta or not tb:
        return None
    shared = tokens_of(ta) & tokens_of(tb)
    # 否定型：要求共享片段足够多（≥3），避免「不要在公司内部讨论时」这类误判
    if len(shared) >= 3 and _negated(ta) != _negated(tb):
        return f"适用条件一侧被否定（共享片段：{'、'.join(sorted(shared)[:4])}）：「{ta}」vs「{tb}」"
    # 词对型：必须还有共享上下文（同一个条件轴），否则「资料齐全」vs「预算缺失」会被误判
    for left, right in CONDITION_ANTONYMS:
        if shared and ((left in ta and right in tb) or (right in ta and left in tb)):
            return f"适用条件含互斥词对（{left} / {right}）：「{ta}」vs「{tb}」"
    return None


def _lcs_len(a: str, b: str, cap: int = 300) -> tuple[int, str]:
    """最长公共连续片段长度与其内容（用于判断「是否在说同一件事」）。"""
    a, b = a[:cap], b[:cap]
    if not a or not b:
        return 0, ""
    previous = [0] * (len(b) + 1)
    best_len, best_end = 0, 0
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len, best_end = current[j], i
        previous = current
    return best_len, a[best_end - best_len:best_end]


def _counterexample_conflict(holder: dict, target: dict) -> str | None:
    """holder 的 counterexamples 是否指向 target 的结论。

    判定标准（高精度）：直接引用对方 experience_id，或与对方结论/标题存在 ≥8 个连续相同字符
    且该片段至少占较短一方的 30%——用词集重叠判定会把「三个维度」这类通用词算成指向。
    """
    conclusion = str(target.get("conclusion") or "")
    title = str(target.get("title") or "")
    for text in (holder.get("counterexamples") or []):
        line = str(text)
        if str(target.get("experience_id")) in line:
            return f"反例直接引用了 {target.get('experience_id')}：{line}"
        for other, label in ((conclusion, "结论"), (title, "标题")):
            if not other:
                continue
            length, chunk = _lcs_len(line, other)
            if length >= 8 and length >= 0.3 * min(len(line), len(other)):
                return (
                    f"反例与 {target.get('experience_id')}《{target.get('title')}》的{label}有 {length} 字连续相同片段"
                    f"「{chunk}」，视为指向该结论：{line}"
                )
    return None


def detect_conflicts(entries: list[dict]) -> list[dict]:
    """两两检测冲突，返回 [{rule, a, b, detail}]。

    明确说明：这是**模式匹配**（否定词 / 互斥词对 / 显著片段重叠），不是语义理解，
    只能抓明显矛盾，漏检是可能的；因此输出里始终要求「先核实」。
    """
    conflicts: list[dict] = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            for rule, finder in (
                ("G3-CONFLICT-ACTION", _action_conflict),
                ("G3-CONFLICT-TRIGGER", _trigger_conflict),
            ):
                detail = finder(a, b) or finder(b, a)
                if detail:
                    conflicts.append({"rule": rule, "a": a, "b": b, "detail": detail})
            detail = _counterexample_conflict(a, b) or _counterexample_conflict(b, a)
            if detail:
                conflicts.append({"rule": "G3-CONFLICT-COUNTEREXAMPLE", "a": a, "b": b, "detail": detail})
    return conflicts


def _strength(entry: dict) -> str:
    confidence = entry.get("confidence")
    level = confidence if isinstance(confidence, str) else (confidence or {}).get("level")
    return (
        f"status={entry.get('status')}（{EXP_STATUS_ZH.get(entry.get('status'), '?')}）"
        f"、证据 {len(entry.get('evidence') or [])} 条、confidence={level}"
    )


def privacy_hits(entry: dict) -> list[tuple[str, str]]:
    """检测高置信度机密特征，返回 [(规则 id, 命中位置)]。

    只覆盖明显情形（机密标记 / 客户名称占位符 / 指标词与具体数值同现），**不保证完备**。
    """
    hits: list[tuple[str, str]] = []
    single_fields = ("title", "conclusion", "context", "recommended_action", "reasoning")
    list_fields = ("trigger_conditions", "evidence", "limitations", "counterexamples", "tags")

    def scan(field: str, text: str) -> None:
        if not text:
            return
        for marker in PRIVACY_MARKERS:
            if marker in text:
                hits.append(("G4-PRIVACY-MARKER", f"{field} 含机密标记「{marker}」"))
        for pattern in PRIVACY_CUSTOMER_PATTERNS:
            match = re.search(pattern, text)
            if match:
                hits.append(("G4-PRIVACY-CUSTOMER", f"{field} 含客户名称或占位符「{match.group(0)}」"))
        for metric in PRIVACY_METRICS:
            if metric in text and _HAS_DIGIT.search(text):
                hits.append(("G4-PRIVACY-METRIC", f"{field} 同时含指标词「{metric}」与具体数值"))

    for field in single_fields:
        scan(field, str(entry.get(field) or ""))
    for field in list_fields:
        for index, item in enumerate(entry.get(field) or []):
            scan(f"{field}[{index}]", str(item))

    seen = set()
    unique: list[tuple[str, str]] = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            unique.append(hit)
    return unique


def cmd_search(args) -> int:
    directory, _ = resolve_context(args)
    entries, problems = load_entries(directory)

    # 同时纳入「流程类教训」：它们跨任务、按本次任务类型与领域检索不到，
    # 但恰恰是这类任务最容易重蹈的错。分开存放、合并检索。
    lesson_dir = getattr(store, "LESSONS_DIR", None)
    if lesson_dir and Path(lesson_dir).is_dir() and Path(lesson_dir).resolve() != Path(directory).resolve():
        lesson_entries, lesson_problems = load_entries(Path(lesson_dir))
        for item in lesson_entries:
            item["_kind"] = "lesson"
        entries = entries + lesson_entries
        problems = problems + lesson_problems
    want_tags = split_tags(args.tags)
    query_tokens = tokens_of(args.query) | want_tags | split_tags(args.domain) | split_tags(args.task_type)

    print("=== 经验检索（结构化关键词打分：domain/task_type/tags/trigger_conditions，不是语义检索）===")
    print(f"经验目录  : {directory}")
    print(f"检索线索  : query=\"{args.query}\"  领域={args.domain or '（未指定）'}  类型={args.task_type or '（未指定）'}  标签={sorted(want_tags) or '（无）'}")
    for problem in problems:
        print(f"  ! 读取问题：{problem}")

    scored = []
    for entry in entries:
        score, reasons = score_entry(entry, query_tokens, args.domain, args.task_type, want_tags)
        scored.append((score, reasons, entry))

    candidates = [(s, r, e) for s, r, e in scored if s >= args.min_score]
    applicable, excluded = [], []
    for score, reasons, entry in sorted(candidates, key=lambda item: -item[0]):
        ok, why = classify(entry, args.domain, args.task_type)
        if ok:
            applicable.append((score, reasons, entry))
        else:
            excluded.append((score, entry, why))
    irrelevant = len(entries) - len(candidates)

    conflict_preview = detect_conflicts([entry for _, _, entry in applicable])
    conflicted_preview = {c["a"].get("experience_id") for c in conflict_preview} | {c["b"].get("experience_id") for c in conflict_preview}
    print(
        f"候选      : {len(candidates)} 条（相关度 ≥ {args.min_score}）；"
        f"适用 {len(applicable)} 条"
        + (f"（其中 {len(conflicted_preview)} 条存在冲突，见【冲突提示】）" if conflict_preview else "")
        + f"；显式排除 {len(excluded)} 条；"
        f"未进候选（认为不相关）{irrelevant} 条；经验库共 {len(entries)} 条"
    )
    print()

    conflicts = detect_conflicts([entry for _, _, entry in applicable])
    conflicted_ids = {c["a"].get("experience_id") for c in conflicts} | {c["b"].get("experience_id") for c in conflicts}
    usable = [item for item in applicable if item[2].get("experience_id") not in conflicted_ids]
    conflicted = [item for item in applicable if item[2].get("experience_id") in conflicted_ids]

    def render_entry(mark: str, index: int, score: int, reasons: list[str], entry: dict) -> None:
        outcome = entry.get("observed_outcome") or {}
        confidence = entry.get("confidence")
        print(f"{mark} {index}. {entry.get('experience_id')} 《{entry.get('title')}》　相关度 {score}")
        print(f"   命中依据：{'；'.join(reasons)}")
        print(f"   结论：{entry.get('conclusion')}")
        print(f"   建议做法：{entry.get('recommended_action')}")
        print(f"   适用条件：{'；'.join(map(str, entry.get('trigger_conditions') or []))}")
        print(
            f"   证据强度：status={entry.get('status')}（{EXP_STATUS_ZH.get(entry.get('status'), '?')}）；"
            f"证据 {len(entry.get('evidence') or [])} 条；confidence={confidence if isinstance(confidence, str) else (confidence or {}).get('level')}"
        )
        print(f"   实际观察到的结果：{outcome.get('result') if isinstance(outcome, dict) else outcome}")
        limits = entry.get("limitations") or []
        counters = entry.get("counterexamples") or []
        print(f"   限制：{'；'.join(map(str, limits)) if limits else '未记录'}")
        print(f"   反例：{'；'.join(map(str, counters)) if counters else '未记录'}")
        print( "   使用要求：先核对当前任务条件是否与上述适用条件一致；若与当前事实冲突，先核实，不得盲目套用")

    if usable:
        print("【适用经验】（标记「✓ 可采用」；作为建议或检查点使用，不得覆盖当前任务事实）")
        for index, (score, reasons, entry) in enumerate(usable[: args.limit], start=1):
            render_entry("✓ 可采用", index, score, reasons, entry)
        if len(usable) > args.limit:
            print(f"   （另有 {len(usable) - args.limit} 条适用经验未列出——只给少量最相关的，避免把整个经验库塞进上下文）")
    elif applicable:
        print("【适用经验】无：本次检索到的适用经验之间存在冲突，任何一条都不能直接采用（见下方【冲突提示】）。")
    else:
        print("【适用经验】本次没有检索到可用经验。")
        print("  说明：空结果是合法结果——经验库不是必用清单，宁可不用，也不要为了「用上」而套用不相关经验。")

    if conflicted:
        print()
        print("【适用但有冲突的条目】⚠ 不得直接采用，须先核实（不与「可采用」条目并列）")
        partners: dict[str, list[str]] = {}
        for conflict in conflicts:
            partners.setdefault(str(conflict["a"].get("experience_id")), []).append(
                f"{conflict['rule']}↔{conflict['b'].get('experience_id')}"
            )
            partners.setdefault(str(conflict["b"].get("experience_id")), []).append(
                f"{conflict['rule']}↔{conflict['a'].get('experience_id')}"
            )
        for index, (score, reasons, entry) in enumerate(conflicted, start=1):
            print(f"⚠ 不得直接采用 {index}. {entry.get('experience_id')} 《{entry.get('title')}》　相关度 {score}")
            print(f"   证据强度：{_strength(entry)}")
            print(f"   建议做法：{entry.get('recommended_action')}")
            print(f"   适用条件：{'；'.join(map(str, entry.get('trigger_conditions') or []))}")
            print(f"   冲突：{'；'.join(partners.get(str(entry.get('experience_id')), []))}（详见【冲突提示】）")

    if conflicts:
        print()
        print("【冲突提示】（工具只能发现明显矛盾；未发现不等于没有矛盾）")
        for index, conflict in enumerate(conflicts, start=1):
            a, b = conflict["a"], conflict["b"]
            print(f"冲突 {index}：{conflict['rule']} —— {EXP_RULES.get(conflict['rule'], '')}")
            print(f"  双方：{a.get('experience_id')}《{a.get('title')}》 vs {b.get('experience_id')}《{b.get('title')}》")
            print(f"  证据强度：{a.get('experience_id')} → {_strength(a)}")
            print(f"            {b.get('experience_id')} → {_strength(b)}")
            print(f"  条件差异：{a.get('experience_id')} 适用条件：{'；'.join(map(str, a.get('trigger_conditions') or []))}")
            print(f"            {b.get('experience_id')} 适用条件：{'；'.join(map(str, b.get('trigger_conditions') or []))}")
            print(f"  争议点：{conflict['detail']}")
            print(
                "  建议先核实什么：先确认本次任务实际满足哪一侧的适用条件（对照上面两行条件差异），"
                "再决定采用哪一条；核实前两条都不得当作既定事实，也不得把其中一条当成普遍规律"
            )
        print("  说明：冲突判定基于否定词 / 互斥词对 / 显著片段重叠的模式匹配，不是语义理解；")
        print("        因此「未提示冲突」不代表两条经验一定相容，条件接近时仍应人工对比。")

    print()
    if excluded:
        print("【显式排除的条目（不参与本次建议）】")
        for score, entry, why in excluded:
            print(f"- {entry.get('experience_id')}（相关度 {score}）→ 排除原因：{why}")
    else:
        print("【显式排除的条目】无（本次没有命中任何 已失效 / 被反例挑战 / 条件不匹配 / 未验证假设 的条目）")

    print()
    print("【检索限制】关键词打分不是语义检索：字面相似不等于适用；过时、被反例挑战、")
    print("条件不匹配、未执行的假设都会被显式排除，并在上面写明原因。")
    return 1 if problems else 0


# ---------------------------------------------------------------- add

def build_report_and_context(experience_state_dir: Path) -> tuple[validator.Report, validator.Context]:
    report = validator.Report()
    schema = validator.load_schema(experience_state_dir, report)
    ctx = validator.load_context(experience_state_dir, schema, report)
    return report, ctx


def display_path(path: Path) -> str:
    """项目内的路径显示为相对路径；接缝落在项目外时回退为绝对路径（不因展示而失败）。"""
    try:
        return str(path.relative_to(store.PROJECT_ROOT))
    except ValueError:
        return str(path)


def seam_backup_dest(directory: Path, explicit: Path | None) -> Path:
    """接缝模式的备份落点（t18）：显式 --backup-dir 优先，否则落在接缝自己的同级 backups/。

    为什么不能回落到正式 state/backups/：接缝写入只存在于样本树/副本里，把它的「写前备份」
    放进正式目录会让冻结判据「受测面不可变」字面上永远无法满足（t17 §9-O1）。
    三种失败情形一律**明确报错**，绝不静默回落：
      * 显式落点就是（或位于）正式备份目录；
      * 落点无法创建（交给 store.create_backup 抛 StoreError）；
      * 落点为空字符串等非法输入（Path 解析后仍是当前目录时会被下面的比较拦下）。
    """
    if explicit is not None:
        candidate = Path(explicit).expanduser()
    else:
        # 接缝数据通常形如 <样本>/state/experience，备份与 experience/ 同级；
        # 若接缝只是一个临时目录，则落在它的父目录下——两种情况下都在接缝旁边。
        candidate = Path(directory).resolve().parent / "backups"
    resolved = candidate.resolve()
    real = store.BACKUP_DIR.resolve()
    if resolved == real or real in resolved.parents:
        raise store.StoreError(
            f"接缝模式的备份落点不能是正式备份目录 {real}（收到 {resolved}）。"
            "那会把接缝写入的备份混进正式恢复链，使「受测面不可变」无法成立；"
            "请用 --backup-dir 指向接缝自己的位置，或去掉 --experience-dir 走正式路径。"
        )
    return candidate


def write_entry(payload: dict, directory: Path, reason: str, backup_dest: Path | None = None) -> Path | None:
    """真实路径走 store.save_experience（其内部自带 create_backup）。

    测试接缝（t18）：仍然**先备份再写入**（不取消写前备份纪律），但落点是接缝自己的
    backups/ 或调用方用 --backup-dir 显式指定的位置，绝不写正式 state/backups/。
    """
    if Path(directory).resolve() == store.EXPERIENCE_DIR.resolve():
        store.save_experience(payload, reason)
        return store.latest_backup()
    dest = seam_backup_dest(directory, backup_dest)
    # t19 修复：落点隔离了，源也必须隔离。
    # 此前只给 dest，导致备份的**内容**还是正式 PROJECT_ROOT 的文件——
    # 跑一次接缝测试就把用户的真实任务数据复制进了测试目录
    # （实测：_seam_privacy_run/state/backups/ 里躺着 3181 行真实任务）。
    # 接缝数据形如 <接缝根>/state/experience，故源根 = state/ 的上一级。
    seam_root = Path(directory).resolve().parent.parent \
        if Path(directory).resolve().parent.name == "state" \
        else Path(directory).resolve().parent
    backup = store.create_backup(reason, dest=dest, source_root=seam_root)
    store.write_json(Path(directory) / f"{payload['experience_id']}.json", payload)
    return backup


def cmd_add(args) -> int:
    directory, ref_state = resolve_context(args)
    payload = store.read_json(args.file)
    if not isinstance(payload, dict):
        print("错误：输入文件的顶层必须是 JSON 对象。", file=sys.stderr)
        return 2

    experience_id = payload.get("experience_id") or "（缺 experience_id）"
    print("=== 经验入库（带证据门禁）===")
    print(f"目标目录  : {directory}" + ("（测试接缝：不写真实 state/experience）" if directory.resolve() != store.EXPERIENCE_DIR.resolve() else ""))
    print(f"交叉引用  : 按 {ref_state} 校验")
    print(f"待写入    : {experience_id}")

    # 1) 不覆盖既有条目
    target = Path(directory) / f"{payload.get('experience_id')}.json"
    if payload.get("experience_id") and target.exists():
        print(f"拒绝写入  : {experience_id} 已存在（{target}）——写入不得覆盖既有经验，请改用 review 更新状态")
        return 1

    # 2) 规则门禁：复用 validate.py 的单条经验规则
    report, ctx = build_report_and_context(ref_state)
    validator.check_experience(payload, "待写入条目", ctx, report, filename=f"{payload.get('experience_id')}.json")
    if payload.get("experience_id") in ctx.experience_ids:
        report.error("E-ID-DUP", "待写入条目", f"experience_id {experience_id} 已存在，拒绝重复写入")

    if report.errors:
        print("拒绝写入  : 未通过校验规则（共 %d 条错误）：" % len(report.errors))
        for item in report.errors:
            print(f"  [错误] [{item['rule']}] {item['where']} → {item['message']}")
        print("说明      : 未执行就不要写成已验证；信息不全时先补齐证据或改为 to_verify（待验证假设）。")
        return 1
    for item in report.warnings:
        print(f"  [警告] [{item['rule']}] {item['where']} → {item['message']}")

    # 3) 隐私门禁（G4）：general 域命中高置信度机密特征时，必须显式确认才写入
    privacy_scope = payload.get("privacy_scope")
    hits = privacy_hits(payload) if privacy_scope == "general" else []
    if privacy_scope == "general" and hits:
        print(f"【隐私检查】privacy_scope=general，正文命中 {len(hits)} 处高置信度机密特征：")
        for rule, where in hits:
            print(f"  [警告] [{rule}] {where}")
        print("  检测边界  : 自动检测只能拦截明显情形，不能替代人工判断；")
        print("              命中不等于一定机密，未命中也不等于内容可以安全泛化。")
        if not args.privacy_ack:
            print("拒绝写入  : 需要人工确认后才能把上述内容写入 general（跨领域复用）经验库。")
            print("           确认与具体公司/客户无关、可泛化复用时，加 --privacy-ack 重试；")
            print("           若确实含机密：改写成去敏原则，或把 privacy_scope 设为 work/personal 留在原域。")
            return 1
        print("已确认    : 显式传入 --privacy-ack，按使用者的决定继续写入（工具不代替人做判断）。")
    elif privacy_scope == "general":
        print("隐私范围  : privacy_scope=general，未命中已知的高置信度机密特征；")
        print("            这不等于内容一定可以泛化——自动检测只能拦截明显情形，仍需人工判断。")
    else:
        print(f"隐私范围  : privacy_scope={privacy_scope}（非 general 域不做跨域泛化检查：机密内容留在原域是正确落点）")

    if args.dry_run:
        print("dry-run   : 校验通过，但按要求未写文件、未备份")
        print(f"将会写入  : {target}")
        return 0

    backup = write_entry(payload, directory, f"经验入库 {experience_id}", getattr(args, "backup_dir", None))
    if backup is not None:
        seam_mark = "" if str(backup).startswith(str(store.BACKUP_DIR)) else "（接缝自己的备份落点，未写正式 state/backups）"
        print(f"写前备份  : {display_path(backup)}{seam_mark}")
    print(f"已写入    : {target}")
    print(f"状态      : {payload.get('status')}（{EXP_STATUS_ZH.get(payload.get('status'), '?')}）；证据 {len(payload.get('evidence') or [])} 条")
    print("下一步    : 复核或条件变化时用 `python3 scripts/exp.py review --id ... --status ... --note \"...\"`")
    return 0


# ---------------------------------------------------------------- review

def find_entry_file(directory: Path, experience_id: str) -> Path | None:
    if not directory.exists():
        return None
    direct = directory / f"{experience_id}.json"
    if direct.exists():
        return direct
    for path in sorted(directory.glob("*.json")):
        try:
            data = store.read_json(path)
        except store.StoreError:
            continue
        if isinstance(data, dict) and data.get("experience_id") == experience_id:
            return path
    return None


def cmd_review(args) -> int:
    directory, ref_state = resolve_context(args)
    print("=== 经验复核（更新 last_reviewed_at/status，保留历史）===")
    print(f"经验目录  : {directory}" + ("（测试接缝：不写真实 state/experience）" if directory.resolve() != store.EXPERIENCE_DIR.resolve() else ""))

    entries, problems = load_entries(directory)
    for problem in problems:
        print(f"  ! 读取问题：{problem}")

    path = find_entry_file(directory, args.id)
    if path is None:
        known = "、".join(e.get("experience_id", "?") for e in entries) or "（无）"
        print(f"错误：经验目录中找不到 {args.id}。现有条目：{known}", file=sys.stderr)
        return 1

    entry = store.read_json(path)
    if not isinstance(entry, dict):
        print(f"错误：{path} 顶层不是 JSON 对象。", file=sys.stderr)
        return 2

    allowed = (validator.load_schema(ref_state, validator.Report()) or {}).get("enums", {}).get("experience_status", [])
    if args.status not in allowed:
        print(f"错误：status 必须是 {allowed} 之一。", file=sys.stderr)
        return 2
    if not args.note or not args.note.strip():
        print("错误：复核必须留下理由（--note）——无依据的状态变更不得写入。", file=sys.stderr)
        return 2

    outcome = entry.get("observed_outcome") or {}
    executed = outcome.get("executed") if isinstance(outcome, dict) else None
    evidence = entry.get("evidence") or []
    from_status = entry.get("status")

    # 门禁：未执行不得越级为「已观察/已验证」
    if args.status in ("single_observation", "repeatedly_supported"):
        if executed is not True:
            print(f"拒绝复核  : 目标是 {args.status}，但 observed_outcome.executed={executed!r}——未执行不得写成已验证，只能写 to_verify")
            return 1
        if not evidence:
            print(f"拒绝复核  : 目标是 {args.status}，但 evidence 为空——没有证据不得升级")
            return 1
    # 门禁：有未处理的反例时不得升级为「已观察/重复支持」——否则检索会把它当可用经验推荐
    counterexamples = entry.get("counterexamples") or []
    if args.status in ("single_observation", "repeatedly_supported") and counterexamples:
        if not args.counterexample_resolved:
            print(f"拒绝复核  : 该条目记录着 {len(counterexamples)} 条反例，不能直接升级为「已观察/重复支持」。")
            print(f"           反例：{counterexamples[0]}")
            print("           若反例已被新证据推翻或条件已变化，请用 --counterexample-resolved \"说明\" 记录处理依据（反例原文保留不删）。")
            return 1
        entry.setdefault("counterexample_resolutions", []).append({
            "at": store.now_iso(),
            "from_status": from_status,
            "resolution": args.counterexample_resolved,
        })
        print(f"反例处理  : 已记录处理依据（共 {len(entry['counterexample_resolutions'])} 条，反例原文保留）：{args.counterexample_resolved}")

    if args.status == "repeatedly_supported" and len(evidence) < 2:
        print(f"  警告    : 现有证据只有 {len(evidence)} 条；「重复支持」通常需要多次独立观察，请补充证据或改用 single_observation。")

    old_reviewed = entry.get("last_reviewed_at")
    now = store.now_iso()
    entry["status"] = args.status
    entry["last_reviewed_at"] = now
    if args.review_after:
        entry["review_after"] = args.review_after
    entry.setdefault("review_history", []).append({
        "at": now,
        "from_status": from_status,
        "to_status": args.status,
        "note": args.note,
        "evidence_count": len(evidence),
        "previous_last_reviewed_at": old_reviewed,
    })

    print(f"条目      : {args.id}《{entry.get('title')}》")
    print(f"状态变更  : {from_status} → {args.status}（{EXP_STATUS_ZH.get(args.status, '?')}）")
    print(f"复核时间  : {old_reviewed} → {now}")
    print(f"复核理由  : {args.note}")
    print(f"历史      : review_history 追加 1 条（共 {len(entry['review_history'])} 条，旧值保留不覆盖）")

    if args.dry_run:
        print("dry-run   : 按要求未写文件、未备份")
        return 0

    backup = write_entry(entry, directory, f"经验复核 {args.id}", getattr(args, "backup_dir", None))
    if backup is not None:
        seam_mark = "" if str(backup).startswith(str(store.BACKUP_DIR)) else "（接缝自己的备份落点，未写正式 state/backups）"
        print(f"写前备份  : {display_path(backup)}{seam_mark}")
    print(f"已写入    : {path}")
    return 0


# ---------------------------------------------------------------- 主流程

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="任务导航 经验库：检索 / 入库 / 复核")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="检索少量最相关经验并给出适用性判断")
    p_search.add_argument("--query", required=True, help="本次任务的检索线索（目标/问题/领域描述）")
    p_search.add_argument("--domain", help="本次任务的 domain")
    p_search.add_argument("--task-type", dest="task_type", help="本次任务的 task_type")
    p_search.add_argument("--tags", help="额外的关键词，逗号分隔")
    p_search.add_argument("--limit", type=int, default=3, help="最多列出几条适用经验（默认 3）")
    p_search.add_argument("--min-score", type=int, default=3, help="进入候选的最低相关度（默认 3）")
    p_search.add_argument("--experience-dir", type=Path, help="改用该经验目录（测试接缝，默认 state/experience）")
    p_search.set_defaults(func=cmd_search)

    p_add = sub.add_parser("add", help="写入一条经验（带证据门禁，拒绝未验证越级）")
    p_add.add_argument("--file", required=True, type=Path, help="经验条目 JSON 文件")
    p_add.add_argument("--dry-run", action="store_true", help="只校验，不写入")
    p_add.add_argument("--privacy-ack", dest="privacy_ack", action="store_true",
                       help="确认 privacy_scope=general 的条目已去敏、可以跨领域复用（命中机密特征时必须显式给出）")
    p_add.add_argument("--experience-dir", type=Path, help="改用该经验目录（测试接缝）")
    p_add.add_argument("--backup-dir", type=Path,
                       help="接缝模式的备份落点（默认：接缝自己的同级 backups/；不得指向正式 state/backups）")
    p_add.set_defaults(func=cmd_add)

    p_review = sub.add_parser("review", help="复核：更新 status/last_reviewed_at 并留历史")
    p_review.add_argument("--id", required=True, help="experience_id")
    p_review.add_argument("--status", required=True, help="新的 experience_status")
    p_review.add_argument("--note", required=True, help="复核理由（必填，无理由不得改状态）")
    p_review.add_argument("--review-after", dest="review_after", help="下次复核时间（iso8601）")
    p_review.add_argument("--counterexample-resolved", dest="counterexample_resolved",
                          help="该条目已有反例时，说明反例为何不再阻断本次升级（反例原文保留）")
    p_review.add_argument("--dry-run", action="store_true", help="只打印变更，不写入")
    p_review.add_argument("--experience-dir", type=Path, help="改用该经验目录（测试接缝）")
    p_review.add_argument("--backup-dir", type=Path,
                          help="接缝模式的备份落点（默认：接缝自己的同级 backups/；不得指向正式 state/backups）")
    p_review.set_defaults(func=cmd_review)

    args = parser.parse_args(argv[1:])
    store.find_project_root()
    return args.func(args)


if __name__ == "__main__":
    # 管道/重定向下强制 UTF-8：否则 Windows 中文环境打印 ✅ 会 UnicodeEncodeError
    import console  # noqa: E402

    console.setup()
    try:
        sys.exit(main(sys.argv))
    except store.StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(2)
