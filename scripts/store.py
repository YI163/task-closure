#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务导航 数据层（唯一权威读写模块）。

设计原则
--------
1. 单一入口：所有对 state/ 的读写都经过本模块，禁止其他脚本直接 open() 写入。
2. 原子写：先写临时文件并复验可解析，再 os.replace 覆盖目标。
3. 写前备份：任何写操作先做全量快照到 state/backups/<UTC时间戳>/，附 manifest（sha256 + 记录数）。
4. 只增不改：变更历史写入 task["history"] 与 append-only 的 tasks.jsonl，旧值不覆盖。
5. 诚实降级：数据缺失或损坏时明确报错（StoreError），绝不编造记录。

使用方式：作为库被其他脚本 import；也可直接运行做自检：
    python3 scripts/store.py selftest
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------- 路径

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "state"
BACKUP_DIR = STATE_DIR / "backups"
SCHEMA_PATH = STATE_DIR / "schema.json"
TASKS_PATH = STATE_DIR / "tasks.json"
EVENTS_PATH = STATE_DIR / "tasks.jsonl"
SKILLS_PATH = STATE_DIR / "user_skills.json"
EXPERIENCE_DIR = STATE_DIR / "experience"
# 流程类教训（跨任务的工作方式教训，与领域经验分开存放——
# 混进经验库会污染按 domain 的领域检索）
LESSONS_DIR = STATE_DIR / "lessons"
EXPERIENCE_INDEX = STATE_DIR / "experience_index.md"
DECISIONS_PATH = PROJECT_ROOT / "decisions.md"
METHODS_PATH = PROJECT_ROOT / "methods" / "index.json"


class StoreError(RuntimeError):
    """数据层可预期的错误：参数非法、数据缺失、数据损坏。"""


# ---------------------------------------------------------------- 时间

def now_iso() -> str:
    """带本地时区偏移的 ISO8601 时间戳，精确到秒。"""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def utc_stamp() -> str:
    """用于备份目录名的 UTC 紧凑时间戳（可排序、无本地时区歧义）。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def today_compact() -> str:
    return datetime.now().strftime("%Y%m%d")


def is_iso8601(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 基础 IO

def read_json(path: Path, default=None):
    """读取 JSON；文件不存在时返回 default；内容损坏时抛 StoreError（不静默）。"""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise StoreError(
            f"数据文件损坏，无法解析：{path}（{exc}）。"
            f"请从 {BACKUP_DIR} 中最近的备份恢复，不要手工猜测内容。"
        ) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=str(path.parent), prefix=".tmp-", delete=False
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, data) -> None:
    """原子写 JSON（带缩进，便于人阅读与 diff）。"""
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    _atomic_write_bytes(Path(path), payload.encode("utf-8"))


def append_line(path: Path, obj) -> None:
    """追加一行 JSON（append-only 事件流）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, sort_keys=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def find_project_root() -> Path:
    """返回项目根目录；附带健全性检查，避免把文件写到意外位置。"""
    if not SCHEMA_PATH.exists():
        raise StoreError(
            f"未找到数据契约 {SCHEMA_PATH}，当前目录不是 任务导航 项目根目录。"
        )
    return PROJECT_ROOT


# ---------------------------------------------------------------- 备份

def list_backupable_files() -> list[Path]:
    """列出需要纳入备份的文件（不含 backups 自身，避免递归）。"""
    files: list[Path] = []
    for candidate in (TASKS_PATH, SKILLS_PATH, SCHEMA_PATH, METHODS_PATH, DECISIONS_PATH, EVENTS_PATH):
        if candidate.exists():
            files.append(candidate)
    if EXPERIENCE_DIR.exists():
        files.extend(sorted(p for p in EXPERIENCE_DIR.glob("*.json")))
    return files


def count_records(path: Path) -> int:
    """记录数：数组按长度；对象含 tasks/skills/methods 键时取该数组；JSONL 按行数；其他为 1。"""
    path = Path(path)
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    try:
        data = read_json(path, default=None)
    except StoreError:
        return -1
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("tasks", "skills", "methods", "experiences"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return 1


def backup_dir(dest: "Path | str | None" = None) -> Path:
    """解析备份落点（t18）：显式参数优先，缺省仍是正式 state/backups。

    为什么落点要可注入、而不便硬编码：store.py 的 PROJECT_ROOT 由自身路径推导，但**接缝数据
    的归属只有调用方知道**——样本树可能在 tests/invalid/<样本>/state 下，也可能在临时副本
    （outputs/ 或 /tmp）里。测试接缝若仍把备份写进正式 state/backups/，「受测面不可变」就
    永远无法满足；而备份是恢复能力的唯一保证，不能为了整洁把它关掉——只能把落点移到
    该去的地方。默认值不变，因此正式路径的行为完全不受影响。

    为什么不做成环境变量：那样所有调用方（含正式路径）的落点都会被隐式改道，而
    `validate.py --backup-verify --all-backups` 是按常数 BACKUP_DIR 枚举备份的，
    会造成「写在这里、验在那里」的错位。落点只接受显式注入。
    """
    if dest is not None:
        return Path(dest).expanduser()
    return BACKUP_DIR


def create_backup(reason: str, dest: "Path | str | None" = None) -> Path:
    """创建全量快照 + manifest。返回备份目录。所有写操作前调用。

    dest（t18）：自定义落点（测试接缝用）；缺省仍是正式 state/backups。
    落点无法创建时**明确报错**，绝不静默回落到正式目录（宁可失败，不要污染冻结判据）。
    注意：快照的**内容**仍是 list_backupable_files() 定义的项目文件；本参数只改落点。
    """
    find_project_root()
    directory = backup_dir(dest)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(
            f"备份目录无法创建：{directory}（{exc}）。不会回落到正式 {BACKUP_DIR}；"
            "请给出可写的 --backup-dir（接缝）或检查磁盘权限。"
        ) from exc
    stamp = utc_stamp()
    target = directory / stamp
    suffix = 1
    while target.exists():
        suffix += 1
        target = directory / f"{stamp}-{suffix}"
    target.mkdir(parents=True, exist_ok=False)

    entries = []
    for source in list_backupable_files():
        relative = source.relative_to(PROJECT_ROOT)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        entries.append(
            {
                "path": str(relative),
                "sha256": sha256_file(destination),
                "records": count_records(destination),
            }
        )

    manifest = {
        "created_at": now_iso(),
        "reason": reason,
        "schema_version": (read_json(SCHEMA_PATH, default={}) or {}).get("schema_version"),
        "files": entries,
    }
    write_json(target / "manifest.json", manifest)
    return target


def latest_backup() -> Path | None:
    directory = backup_dir()
    if not directory.exists():
        return None
    candidates = sorted(p for p in directory.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def verify_backup(path: Path | None = None) -> dict:
    """逐文件比对 sha256 与记录数。返回报告字典；不静默通过。"""
    path = Path(path) if path else latest_backup()
    if path is None:
        raise StoreError("没有任何备份可供校验。")
    manifest = read_json(path / "manifest.json", default=None)
    if manifest is None:
        raise StoreError(f"备份缺少 manifest.json：{path}")

    problems: list[str] = []
    checked = 0
    for entry in manifest.get("files", []):
        stored = path / entry["path"]
        if not stored.exists():
            problems.append(f"备份内文件缺失：{entry['path']}")
            continue
        actual_hash = sha256_file(stored)
        if actual_hash != entry["sha256"]:
            problems.append(f"备份内文件哈希不符：{entry['path']}")
            continue
        actual_records = count_records(stored)
        if entry.get("records", -1) != actual_records:
            problems.append(
                f"记录数不符：{entry['path']} 期望 {entry.get('records')} 实际 {actual_records}"
            )
            continue
        checked += 1

    return {
        "backup": str(path),
        "checked_files": checked,
        "problems": problems,
        "ok": not problems,
    }


# ---------------------------------------------------------------- 任务

def load_tasks() -> dict:
    data = read_json(TASKS_PATH, default=None)
    if data is None:
        return {"tasks": [], "last_updated": None}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise StoreError(f"任务数据格式不符合契约：{TASKS_PATH}")
    return data


def save_tasks(data: dict, reason: str) -> Path:
    data["last_updated"] = now_iso()
    backup = create_backup(reason)
    write_json(TASKS_PATH, data)
    return backup


def next_task_id(existing: list[dict]) -> str:
    prefix = f"TN-{today_compact()}-"
    used = [
        int(t["task_id"].rsplit("-", 1)[1])
        for t in existing
        if isinstance(t.get("task_id"), str) and t["task_id"].startswith(prefix)
    ]
    return f"{prefix}{max(used) + 1 if used else 1:03d}"


def find_task(tasks: list[dict], task_id: str) -> dict:
    for task in tasks:
        if task.get("task_id") == task_id:
            return task
    raise StoreError(f"找不到任务 {task_id}。已存在的任务：{', '.join(t.get('task_id','?') for t in tasks) or '（无）'}")


def resolve_task(tasks: list[dict], hint: str | None) -> dict:
    """按 task_id 或标题/关键词定位任务；有歧义时明确列出候选而不猜。"""
    if hint:
        for task in tasks:
            if task.get("task_id") == hint:
                return task
        matches = [
            t for t in tasks
            if hint.lower() in str(t.get("title", "")).lower()
            or hint.lower() in str(t.get("original_request", "")).lower()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            listing = "; ".join(f"{t['task_id']}《{t['title']}》" for t in matches)
            raise StoreError(f"「{hint}」匹配到多个任务，请指明哪一个：{listing}")
        raise StoreError(f"「{hint}」没有匹配到任何任务。")

    active = [t for t in tasks if t.get("status") not in ("completed", "cancelled")]
    if len(active) == 1:
        return active[0]
    if not active:
        raise StoreError("当前没有进行中的任务。")
    listing = "; ".join(f"{t['task_id']}《{t['title']}》" for t in active)
    raise StoreError(f"有多个进行中的任务，请指明要操作哪一个：{listing}")


def append_history(task: dict, action: str, summary: str, extra: dict | None = None) -> None:
    entry = {"at": now_iso(), "action": action, "summary": summary}
    if extra:
        entry.update(extra)
    task.setdefault("history", []).append(entry)
    task["updated_at"] = entry["at"]


def append_event(task_id: str, action: str, detail: dict) -> None:
    append_line(EVENTS_PATH, {"at": now_iso(), "task_id": task_id, "action": action, "detail": detail})


# ---------------------------------------------------------------- 技能档案

def load_skills() -> dict:
    data = read_json(SKILLS_PATH, default=None)
    if data is None:
        return {"skills": [], "last_updated": None}
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise StoreError(f"技能档案格式不符合契约：{SKILLS_PATH}")
    return data


def save_skills(data: dict, reason: str) -> Path:
    data["last_updated"] = now_iso()
    backup = create_backup(reason)
    write_json(SKILLS_PATH, data)
    return backup


def next_skill_id(existing: list[dict]) -> str:
    prefix = f"SK-{today_compact()}-"
    used = [
        int(s["skill_id"].rsplit("-", 1)[1])
        for s in existing
        if isinstance(s.get("skill_id"), str) and s["skill_id"].startswith(prefix)
    ]
    return f"{prefix}{max(used) + 1 if used else 1:03d}"


# ---------------------------------------------------------------- 经验库

def load_experiences() -> list[dict]:
    if not EXPERIENCE_DIR.exists():
        return []
    items = []
    for path in sorted(EXPERIENCE_DIR.glob("*.json")):
        data = read_json(path, default=None)
        if data is None:
            raise StoreError(f"经验条目无法解析：{path}")
        data["_file"] = str(path.relative_to(PROJECT_ROOT))
        items.append(data)
    return items


def save_experience(experience: dict, reason: str) -> Path:
    experience_id = experience.get("experience_id")
    if not experience_id:
        raise StoreError("经验条目缺少 experience_id，拒绝写入。")
    EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
    create_backup(reason)
    payload = {k: v for k, v in experience.items() if k != "_file"}
    target = EXPERIENCE_DIR / f"{experience_id}.json"
    write_json(target, payload)
    return target


def next_experience_id(existing: list[dict]) -> str:
    prefix = f"EXP-{today_compact()}-"
    used = [
        int(e["experience_id"].rsplit("-", 1)[1])
        for e in existing
        if isinstance(e.get("experience_id"), str) and e["experience_id"].startswith(prefix)
    ]
    return f"{prefix}{max(used) + 1 if used else 1:03d}"


# ---------------------------------------------------------------- 决策记录

def append_decision(title: str, body: str) -> None:
    """向 decisions.md 追加一条决策（只增不改）。"""
    stamp = now_iso()
    block = f"\n## {stamp} — {title}\n\n{body.strip()}\n"
    with DECISIONS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(block)


# ---------------------------------------------------------------- 自检

def selftest() -> int:
    """对数据层自身做一次真实读写与备份校验，返回进程退出码。"""
    print(f"项目根目录      : {find_project_root()}")
    print(f"state 目录      : {STATE_DIR}")
    print(f"schema 版本     : {(read_json(SCHEMA_PATH, default={}) or {}).get('schema_version')}")
    tasks = load_tasks()
    skills = load_skills()
    experiences = load_experiences()
    print(f"任务数          : {len(tasks['tasks'])}")
    print(f"技能条目数      : {len(skills['skills'])}")
    print(f"经验条目数      : {len(experiences)}")

    backup = create_backup("selftest: 数据层自检")
    print(f"自检备份        : {backup.relative_to(PROJECT_ROOT)}")
    report = verify_backup(backup)
    print(f"备份校验        : {'通过' if report['ok'] else '失败'}")
    for problem in report["problems"]:
        print(f"  ! {problem}")

    # 往事件流写一条真实记录，证明 append-only 通路可用
    append_event("SELFTEST", "store_selftest", {"note": "数据层自检写入"})
    print(f"事件流行数      : {count_records(EVENTS_PATH)}")
    return 0 if report["ok"] else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "selftest":
        print(__doc__)
        print("可用命令：selftest")
        return 2
    return selftest()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except StoreError as error:
        print(f"[StoreError] {error}", file=sys.stderr)
        sys.exit(1)
