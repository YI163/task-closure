# 更新记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

**关于版本号的诚实说明**：当前是 `0.x`，意思是**接口与数据契约仍可能变**。
没有升到 1.0 的原因不是谦虚——是它还没有在足够多的真实任务上验证过
（见下方「已知限制」）。

---

## [0.1.1] — 2026-10-17

### 修复：Windows 上跑不起来（补测时 5 套测试全挂）

作者本机是 macOS，Windows 从未跑过。补测一次跑出 5 套全挂，根因分四类：

| 症状 | 根因 | 修复 |
|---|---|---|
| 打印 `UnicodeEncodeError: 'gbk' codec can't encode '\u2705'` | stdout 被管道/文件接管时用系统区域编码 cp936，输出里的 ✅ ❌ ▶ 编不出来 | 新增 `scripts/console.py`：非控制台流统一 UTF-8；所有脚本入口调用 `console.setup()` |
| 5 套测试「全部失败、输出为空」 | 父进程按 cp936 解码 UTF-8 子进程输出 → `UnicodeDecodeError` | 测试运行器显式 `encoding="utf-8"`（`run_all.py` / `run_rules.py` / `validate.py` / 单测） |
| 场景测试 `FileNotFoundError: [WinError 2]` | `make_test_workspace.sh` 依赖 bash + rsync，Windows 都没有 | 新增 `scripts/make_test_workspace.py`（纯标准库）；`.sh` 保留为薄包装 |
| `validate.py` 报 `M-INDEX-HASH` / `M-INDEX-DRIFT` | Git for Windows 默认 `core.autocrlf=true`，检出转成 CRLF，方法库 sha256 因此对不上 | 新增 `.gitattributes`（`* text=auto eol=lf`），固定 LF |

### 修复：审计器与 SKILL.md 不同步

`scripts/audit.py` 每次运行都报「文档 13 条 / 审计表 12 条」并 exit 1：
审计表漏了文档第 11、12 条，还把「10-2」编成了 102。已按 SKILL.md 对齐
（13 条：7 机械 / 3 半机械 / 3 纯自觉），并把「交付物过多时软删」如实标为纯自觉。

### 新增测试（防止再退化）

- `tests/unit/test_console_encoding.py`：用真管道捕获子进程，要求 ✅ 能输出成 UTF-8
- `tests/unit/test_line_endings.py`：被跟踪的文本文件必须 LF（CRLF 会让哈希校验失效）
- 测试总数：5 套 → 7 套

### CI

- matrix 增加 `windows-latest`：Ubuntu + Windows × Python 3.9 / 3.11 / 3.12
- 增加一步显示 `git ls-files --eol`，换行符问题能直接定位
- 此前 CI 只跑 Ubuntu，「Windows 没跑过」没有任何机制能发现——现在能了

### 文档

- README：Windows 三处环境差异、旧副本重新检出的方法；修正「交付包不含测试」等过期表述
- USER_GUIDE：Windows 首次运行与换行符排障
- DEVELOPMENT：测试命令与提交前清单（7 套、`console.setup()`、LF）

### 实测范围（如实说明）

- Windows 11 + Python 3.12：`python nav.py test` **7/7 通过**（含 157 条场景断言 + 50 条反例）
- Chrome / Edge 无头出图：PNG + PDF 生成成功
- `nav.py init / show / new / export / status / validate`、`exp search`、`audit` 均实跑通过
- **Linux 未在本机实测**；CI 的 Ubuntu 任务是其第一道真实验证

---

## [0.1.0] — 2026-10-17

首次公开发布。

### 包含什么

- **行为契约** `skills/task-navigator/SKILL.md`：12 条硬前置 + A–J 生命周期 + 5 份 reference
- **17 个脚本**：建档 / 更新 / 展示 / 校验 / 复盘 / 交付检查 / 出图 / 经验检索 / 导出
- **数据契约** `state/schema.json`：字段、枚举、必填项——所有校验的依据
- **8 类公开方法论** `methods/`：WBS、PDCA、风险矩阵、预演失败法等，含 16 条选择规则
- **完整测试**：157 条场景断言 + 50 条反例，`python3 tests/run_all.py` 一条命令跑完
- **CI**：每次 push/PR 在 Python 3.9 / 3.11 / 3.12 上自动跑全部测试

### 核心设计

- **状态写在文件里，不在对话里。** 所以换个会话它还记得进度。
- **能机械化的规则一律机械化。** 12 条硬前置里 7 条由脚本强制（不满足直接拒绝），
  而不是靠 AI 自觉。实测数据：机械强制的那 7 条从未被违反；纯自觉的 2 条反复被违反。
- **零第三方依赖**（纯标准库）、**数据全在本地**（纯文本 JSON）、**无任何网络调用**。
- **刻意不做**：自动发消息、控制浏览器、上传数据。

### 发布前修掉的问题

| 问题 | 症状 | 根因 |
|---|---|---|
| 备份半隔离 | 跑一次接缝测试，用户真实任务数据就被复制进测试目录（实测 3181 行） | `create_backup(dest=...)` 只改**落点**，源仍是正式目录 |
| 干净克隆必崩 | `FileNotFoundError: reports/evidence/...` | 测试直接写生成物目录，从不创建它——本地一直有，所以从没暴露 |
| 仓库体积噪音 | 2.8 MB / 521 个测试证据文件入库，每次跑测试都产生 diff | 生成物误入版本库 |
| Python 版本声明不准 | README 写 3.10+，实测 3.9.6 全部通过 | 声明没有实测依据 |

> **「干净克隆必崩」这条是加 CI 之后立刻发现的。** 本地永远跑不出来——
> 因为本地那个目录一直都在。这是本项目主张「能机械化的别靠自觉」的又一个实例。

### 已知限制（不粉饰）

1. **加载 ≠ 执行。** DSH 能自动发现这个 Skill 了（已实测），但这只说明 AI 有机会读到规则，
   **不说明它每次都会照做**。可靠性来自检查点，不来自加载。
2. **规则仍有 2 条纯自觉**（不假装、写计划前读规则）——这类最容易被违反。
3. **仅 macOS + DSH 实测。** Windows / Linux 未经完整验证：
   Chrome 路径写死 3 处、安装命令是 Bash 风格、交付目录写死 `~/Desktop/任务交付`。
4. **语义层面无法机械验证。** 脚本能检查「有没有行动清单」，不能检查「建议是否真的有价值」。
   验收三问要求 AI 自答，仍存在自我确认的可能。
5. **未在大量真实任务上验证。** 作者手上的真实任务大部分还没走完，
   所以「它是否真的帮人把事办成」尚无结论。

---

## 后续计划（不承诺时间）

- **Linux 实测**：CI 跑 Ubuntu，但作者本机没有 Linux 环境；有真实反馈再补
- **任务价值判定**：把「这个任务值不值得进入闭环」做成第一个判断，而不是默认全导入
  （目前 `deliver.py` 不看 `planning_depth`，所以 light 档也要交行动清单，过重）
- **外部证据机制**：验收时若 AI 自己编证据、自己评估，需要引入外部来源或用户确认
- **废弃脚本清理**：`make_flowchart.py` 已被 `flowchart.py` 取代，缺废弃标记
