# 更新记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

**关于版本号的诚实说明**：当前是 `0.x`，意思是**接口与数据契约仍可能变**。
没有升到 1.0 的原因不是谦虚——是它还没有在足够多的真实任务上验证过
（见下方「已知限制」）。

---

## [0.1.3] — 2026-10-17

按《改进建议（交接用）》（生成于开发仓库 HEAD `10c8651`）处理。**基准不同要说明**：
那份报告针对开发仓库，本仓库是公开包，逐项映射如下。

### 第 1 项（报告称 dev 仓库已完成）：经验冲突误报修复——**移植到本仓库**

- 报告说 dev 仓库 `10c8651` 已修 `_action_conflict`；但**该修复不在本仓库历史里**，
  本仓库仍是旧判据（共享 ≥2 片段 + 否定不对称），仍然会误报。
- 已移植：否定分支额外要求至少一个 **4 字中文共享片段**——真冲突（同一做法一侧被否定）
  会出现长片段重合（实测 8 个），词表碰撞不会（0 个）。
- 回归测试 `tests/unit/test_conflict_detection.py`：4 对「共享 2 字片段、无 4 字重合、
  否定不对称」的互补表述必须不报冲突；真冲突对必须仍检出。
  报告未提供原始 4 对经验内容，测试用**同等结构**的句子复现同类误报；测试注释已说明，
  不冒充原始样本。

### 第 2 项（P1）：SKILL.md 摘要补「经验」触发词

- `description` 增加「或要把经验/教训/结论沉淀下来时」；
- 新增 `tests/unit/test_skill_description.py`：守护摘要含 经验 / 复盘 / 验收 / 下一步
  等入口触发词；
- 开发规范新增强制动作：新增任何入口行为必须同步更新 `description`
  （`skills/task-navigator/reference/dev_rules.md`），并写进 DEVELOPMENT 提交前清单。
- 本机没有 `~/.agents/skills/task-closure` 第二份副本，无需同步；若用户机器存在该副本，
  必须逐字同步（报告指出故障正出在全局副本）。
- **「模型是否会因此选中技能」无法由测试证明。**

### 第 3 项（P2，待决策）：`state/tasks.json` 含个人事务

- 对**本仓库**：`state/tasks.json` 早已被 `.gitignore` 排除、未被跟踪；
  `state/user_skills.json` 是脱敏占位（实测 9 条均为「公开版占位：真实档案里的用户原话已移除」）。
  这一项在本仓库**不适用**。
- 报告针对的是**开发仓库**（tasks.json 被跟踪且已进入历史）。本仓库无法访问那份历史，
  未做任何历史清理。开发仓库按报告 A/B/C 方案处理；C（filter-repo 清历史）破坏性大，
  需要单独决策并在所有机器上重新 clone。

### 第 4 项（P3）：`_trigger_conflict` 只加回归，不改逻辑

- 新增 3 条构造样例回归：互斥词对（齐全/缺失）应检出、无关条件不应误报、
  真否定（定价核对 vs 不要定价核对）应检出；
- 另加一条假线索排除：`_negated("判断值不值得做") is False`；
- 与报告一致：没有复现误报就不动检测逻辑。

### 体验：`nav.py env` 显示经验/教训目录（含链接目标）

两台电脑用目录链接共用经验库时，`python nav.py env` 会显示
`经验目录 : …（链接 → …）`，用于确认经验写到哪份数据里。

### 文档：两台电脑共用经验库

README 新增「两台电脑共用经验库」：方案 A（**私有工作仓库：代码+数据**，推荐）
与方案 B（私有数据仓库 + 把整个 `state/` 链接过去），含命令、同步节奏、冲突处理、隐私边界。

**同日修正**：初稿写「数据仓库只放 `experience/` + `lessons/`」是错的——经验条目里的
`source_task_id` / `related_skill_ids` 会被 `validate.py` 交叉核对，只同步经验会导致
另一台机器报 `E-SOURCE` / `T-XREF-*`。正确做法是同步**自洽的整个 `state/`**（任务+经验+
教训+技能档案），或直接用一个私有工作仓库装下代码与数据。

本轮**没有**实现一键 `data link` 命令——跨平台链接创建与安全回退需要单独设计。

### 测试

- 13 → **15 套**（新增冲突判定、技能摘要）；反例 53 不变，场景断言 157 不变；
- 本机 Windows 11 / Python 3.12：15/15 通过（约 30 秒）；`audit.py` exit 0；
- CI：Ubuntu + Windows × Python 3.9 / 3.11 / 3.12。

### 已知限制

- 「摘要含触发词」≠「模型会选中技能」，后者没有脚本能测；
- dev 仓库的任务历史与 `user_skills.json` 清理未处理（不在本仓库范围）；
- 两台电脑同步方案是文档，不是自动化命令；冲突仍需人工按 JSON 文件处理。

---

## [0.1.2] — 2026-10-17

按外部审查报告《Task Closure 最新版本审查与修改意见报告》逐项修复。
基准提交 `06a2a29`。

### P1-1 任务依赖判断：从「字符串包含」改为「精确 step_id」

**问题**：`recompute_next_action()` 用 `str(d) in str(c)` 判断依赖是否完成，
依赖 `S1` 会被已完成的 `S10` 错误满足；`inputs_or_dependencies` 里的自然语言
（如「依赖 S1 的核对结果」）又被当成 ID 做包含比较，导致任务永久阻塞。

**修复**：

- schema `1.7 → 1.8`，新增可选字段 `plan[].depends_on_step_ids`（结构化依赖）；
- `inputs_or_dependencies` 明确为**自然语言说明**，不参与阻塞判断；
- 旧数据无损兼容：旧字段里**整串恰好等于某个真实 step_id** 的条目仍按旧语义参与判断，
  `validate.py` 报 `T-STEP-DEP-LEGACY` 提示迁移；不改写旧数据、不需要迁移脚本；
- 未知依赖 / 自依赖 / 重复依赖：写入侧 `task_new.py` 直接拒绝，读侧 `validate.py` 报
  `T-STEP-DEP-UNKNOWN` / `T-STEP-DEP-SELF` / `T-STEP-DEP-DUP`；
- `task_show.py` 分开显示「依赖」（带完成状态）与「前置条件」。

数据安全：无字段删除、无旧数据改写；升级后第一次写操作仍按 `store.py` 规则自动备份到
`state/backups/<UTC>/`。回滚只需把 schema 与代码退回 v0.1.1——新字段是可选的，
旧代码会把它当作未知字段登记（`T-EXTRA` 说明），不影响读取。

### P1-2 移除 SKILL.md 里作者机器的硬编码路径

删掉 `$HOME/Documents/...` 与作者私有 Python runtime 路径。项目根目录改为：

1. 环境变量 `TASK_CLOSURE_HOME`（装了多份仓库时必须设置）；
2. 未设置时 = Skill 所在仓库根目录。

新增 `python nav.py env`：打印实际使用的项目根目录 / 数据目录 / Python。
`TASK_CLOSURE_HOME` 与实际目录不一致时 **nav.py 拒绝执行（exit 5）**；
直接调脚本时 `store.find_project_root()` 打可见警告。README / USER_GUIDE 补了
PowerShell 联接（Junction）与含中文/空格路径的写法。

### P1-3 流程图渲染：旧产物不能再冒充本次成功

`render()` 原来只看 `png_path.is_file()`。现在：

- 渲染前删除同名旧产物；
- 每次先写 `<name>.part`，**检查退出码 + 文件非空**后才原子替换；
- PNG / PDF 都必须成功，失败信息明确指出格式并带 Chrome 输出尾部；
- `main()` 在失败时返回非零退出码。

### P1-4 审计器：区分「源码线索」与「行为测试证实」

`audit.py` 原来以「源码里出现某个字符串」判定「机械」，注释里写个词也算。
现在每条声称「机械」的规则都必须关联 `tests/unit/test_skill_guards.py` 里的
可复跑行为探针；探针失败 → 审计非零退出。输出分四档：
机械/半机械（行为测试证实）、静态线索（未行为验证）、纯自觉。
当前：7 机械 + 2 半机械（行为测试）、1 静态线索、3 纯自觉。
审计表与 SKILL.md 的条数/编号由 `tests/unit/test_audit_consistency.py` 守着
（SKILL.md 标题也同步改成「十三条硬前置」）。

### P2-5 清理 deliver.py 重复检查区块

删掉第二份「桌面同一内容多格式」扫描与多余注释/赋值，只保留一处权威实现。
行为探针 `deliver-dedup` 断言：无冲突报 0 次、有冲突只报 1 次。

### P2-6 Windows + DSH 安装说明与证据边界

README 增加「证据边界」表，把四件事分开：Windows Python 测试 /
Windows 浏览器出图 / Windows 下 DSH 自动加载 / AI 是否遵守。
**Windows + DSH 自动加载仍是未验证状态**（只验证了配置语法），文档里明确写「未验证」，
不再用「重启后能加载」这类未验证断言。USER_GUIDE 补 PowerShell 安装链路。

### 隐私：补齐会泄露个人内容的忽略规则

用户问「push 之后经验会不会暴露」。检查发现三项**没有**被 `.gitignore` 覆盖：

- `state/experience_index.md`（经验索引：标题/结论/适用条件）
- `STATUS.md`（全部任务状态总览）
- `decisions.md`（决策记录）

已补进 `.gitignore`，并由 `tests/unit/test_privacy_gitignore.py` 守护。
仍存在的一个限制如实说明：`state/user_skills.json` 是**有意跟踪**的脱敏示例，
如果你把真实技能档案写进去，它仍会被提交（README「隐私」一节给了三种处理办法）。

### 附带修复：反例样本生成器与 committed 样本脱节

`tests/invalid/make_samples.py` 的硬编码模板早已过期（缺 risks/communication/time_estimate），
直接运行会把所有样本**降级**，还会删掉手工补的 R37–R39。现在生成器优先从现有
`baseline/` 派生；并补进 R37–R39 与新增 R40–R42；`write_json` 固定 LF（Windows 上
否则会产生 CRLF 样本，`test_line_endings` 会失败）。

### 测试与验证

- 测试套件：7 → **13 套**（3 核心 + 10 单测），反例 50 → **53 个**；
- 新增单测：依赖判断、项目根定位（中文+空格路径全流程）、渲染成功判定、
  SKILL 行为探针、审计一致性、隐私忽略；
- 本机（Windows 11 / Python 3.12）：`python nav.py test` 13/13 通过（约 27 秒）；
  `python scripts/audit.py` exit 0（7 机械行为证实 / 2 半机械 / 1 静态线索 / 3 纯自觉）；
- CI：Ubuntu + Windows × Python 3.9 / 3.11 / 3.12（结果见对应提交的 Actions）。

### 已知限制（本轮未解决）

- **Windows + DSH 的 Skill 自动加载未实测**；作者本机 macOS 侧的「重启后加载」也未复测。
- **AI 是否遵守 Skill 无法由测试证明**：CI 全绿只说明代码与测试在该环境通过。
- `state/user_skills.json` 仍是跟踪文件（见上）。
- Linux 无本机环境，仅 CI 覆盖。
- 审计里第 2 条（状态变更走脚本）仍只是静态线索，没有可靠的行为探针。

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
