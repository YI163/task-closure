# 使用指南

> 面向使用者。想了解设计取舍，看 `README.md` 与 `skills/task-navigator/SKILL.md`。

---

## 一、心智模型：它是「带状态的工作台」，不是「聊天机器人」

普通 AI 对话是这样：

```
你说一件事 → AI 给建议 → 结束（状态丢失）
```

任务导航是这样：

```
你说一件事
  → 先问清目标与完成标准（信息不足不建档）
  → 写成结构化任务卡（存进 state/tasks.json）
  → 拆成步骤（每步写清执行者、交付物、完成标准、风险）
  → 你去做
你说「做完了第 2 步」/「卡住了」/「要求变了」
  → 读状态 → 更新 → 重新排下一步
你说「验收」
  → 三问（承诺做了吗 / 交付物合规吗 / 原目标实现了吗）→ 复盘 → 经验入库
```

**关键差别**：状态写在文件里，不在对话里。**所以换一个会话，它还记得。**

---

## 二、第一件事：确认它能不能跑

```bash
python3 nav.py init     # 建空 state/（不覆盖已有数据）
python3 nav.py test     # 数据校验 + 反例 + 场景 + 单测，期望「全部通过」
```

**如果 `test` 报错**，先看是哪一套失败：
- 数据校验 → 多半是 `state/schema.json` 被删了（那是数据契约，必须保留）
- 其余 → 把输出发出来

**Windows（PowerShell）**：把 `python3` 换成 `python`，其余相同。

```powershell
python nav.py init
python nav.py test
```

若 `test` 在 Windows 上报 `M-INDEX-HASH` / `M-INDEX-DRIFT` 而你又没改过数据，
那是**换行符**问题（Git 默认把检出转成 CRLF），不是数据坏了：

```powershell
git rm --cached -r .
git reset --hard
```

### 装好之后：告诉 AI 数据在哪

```powershell
# Windows（当前会话；长期生效请设系统环境变量）
$env:TASK_CLOSURE_HOME = "<仓库路径>"

# 装成用户级 Skill（让所有工作区都能加载）：目录联接，通常不需要管理员权限
New-Item -ItemType Junction -Path "$HOME\.agents\skills\task-closure" `
  -Target "<仓库路径>\skills\task-navigator"

# 自检：打印实际使用的项目根目录 / 数据目录 / Python
python nav.py env
```

`macOS / Linux` 对应写法：

```bash
export TASK_CLOSURE_HOME="<仓库路径>"
ln -s "$TASK_CLOSURE_HOME/skills/task-navigator" ~/.agents/skills/task-closure
python nav.py env
```

**看到 `状态：不一致` 就停下来**：说明环境变量指向的仓库和本次执行的仓库不是同一个，
nav.py 会返回退出码 5 拒绝执行——这是为了防止把状态写进第二套 `state/`。

> **安装 ≠ 生效**：本仓库已验证 Windows 上的 Python 脚本与测试；
> 但 **Windows + DSH 的 Skill 自动加载链路尚未实测**，且「AI 读到规则」也不等于
> 「AI 会遵守规则」。证据边界见 README「证据边界」一节，不要把测试通过当成行为可靠。

路径类命令的两种写法：

| 用途 | macOS / Linux | Windows PowerShell |
|---|---|---|
| 指定浏览器 | `export CHROME_PATH="/Applications/…/Google Chrome"` | `$env:CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"` |
| 改交付目录 | `export NAV_DELIVERY_DIR=~/Documents/交付` | `$env:NAV_DELIVERY_DIR="$HOME\Documents\交付"` |

---

## 三、日常用法

### 场景 1：提一件新事

**你直接说人话就行**：

> 帮我研究一下家里买什么净水器比较好，最好这个月装好。

AI 应该做的事（这是契约规定的）：
1. 先问清**目标、完成标准、期限、谁用结果**——信息不够就不建档
2. 再写成任务卡，拆出步骤
3. 每步写明：**谁做**（你 / AI / 一起）、**交付什么**、**怎么算完成**

**如果它没这么做**，你可以直接说：「按 SKILL.md 的 §A 接收与理解来做」。

### 场景 2：回来更新进度

> 净水器那事，我昨天量了水槽尺寸。

> 卡住了，安装师傅说我家管道不兼容。

> 老板改要求了，只要三家竞品，不要五家。

**每次它都应该先读状态再回答**，而不是凭对话印象猜。你可以检查它有没有跑：

```bash
python3 scripts/task_show.py
```

### 场景 3：问「下一步做什么」

> 我那个净水器，下一步该干嘛？

它应该给你**当前最值得做的一件事 + 理由**，而不是把所有没做的事列一遍。

### 场景 4：验收

> 净水器装好了，这事结了吧。

它会强制回答三个问题（脚本会拒绝只答一部分）：
1. 承诺的行动是否完成？
2. 交付物是否符合标准？
3. **原始目标是否真正实现？**

第 3 问答「部分实现」时，结论必须是「**我方工作已完成，但最终目标尚待确认**」，
**不许把"勾完了步骤"说成"目标达成"**——这是契约里明确禁止的。

---

## 四、它输出的东西长什么样

一次交付通常包括：

| 文件 | 作用 |
|---|---|
| `0-从这里开始（行动清单）` | **你照着做的那份**，步骤可勾选，标明每步谁做 |
| `0-流程图` | 节奏/依赖可视化（渲染成图，不是字符拼的） |
| `1-主交付物` | 实际内容（方案、报告、脚本…） |

**放在哪**：默认 `~/Desktop/任务交付/<任务分组>/`，可配置。

---

## 五、常用命令

```bash
# 总览（每次开工先跑这个）
python3 scripts/task_show.py
python3 scripts/task_show.py --all                # 含已完成
python3 scripts/task_show.py --task <ID>          # 单个任务完整现场

# 建档
python3 scripts/task_new.py --input 任务.json

# 更新（子命令：step / evidence / decision / blocker / change / next / status / unknown / skillgap / close）
python3 scripts/task_update.py step --task <ID> --file 变更.json

# 校验数据完整性（改过 state/ 之后跑）
python3 scripts/validate.py --all

# 经验库检索（动手前先搜）
python3 scripts/exp.py search --query "交付 格式 命名"

# 交付前检查（不通过不许交付）
python3 scripts/deliver.py check --task <ID>

# 出图（流程/架构图，渲染成 HTML+PNG+PDF）
python3 scripts/flowchart.py --init my_flow.json      # 生成模板
python3 scripts/flowchart.py --spec my_flow.json --out <目录>
```

---

## 六、怎么和 AI 配合（这一节最重要）

### 契约里给你的三个抓手

AI 有可能跑偏。契约里预留了三句话，**说出去就能把它拉回来**：

| 它跑偏的样子 | 你说 |
|---|---|
| 没问清就开始给方案 | 「**按 SKILL.md §A 来**，先问清目标与完成标准」 |
| 凭印象回答进度 | 「**先跑 `task_show.py` 再说话**」 |
| 自作主张扩大/缩小范围 | 「**规则里怎么写的？**」 |

**第三句特别有效**——它会把 AI 逼回去读原文，而不是继续凭记忆发挥。
（作者本机实测：多次靠这一句纠正了 AI 的越界行为。）

### 一个你该知道的机制

契约规定「**信息不足不得建档**」。所以如果你说的事太模糊，**AI 应该反问而不是硬做**。

**如果它不反问就开始干**，那是在违反契约——你有权打断。

---

## 七、常见问题

**Q：它会不会把我的数据传到网上？**
不会。全部是本地 JSON 文件。没有任何网络调用。

**Q：我能直接改 `state/` 里的文件吗？**
能，但**优先用脚本改**（`task_update.py`），因为脚本会做校验和写前备份。
手改之后跑一次 `validate.py --all`。

**Q：删了 `state/` 会怎样？**
任务记录全丢。但 `state/schema.json` **删不得**——脚本靠它做数据校验。
重新 `init.py` 可以重建空目录。

**Q：为什么交付前有一堆检查？**
因为作者本机实测：**没有检查点的规则会被反复违反**（见 README 里那张表）。
那些检查就是「检查点」。

**Q：`scripts/` 里有我不想用的脚本，能删吗？**
能，但注意依赖：`deliver.py` 会调用 `flowchart.py`、`coverage_check.py`、`self_review.py`；
`validate.py` 与 `retro.py` 会调用 `build_index.py`。删之前先确认没人依赖它。

**Q：它支持多个项目/工作区共用一份数据吗？**
支持。Skill 装到用户级（`~/.agents/skills/`）后所有工作区可见；
若用软链接指向同一个仓库，数据就是同一份。做法见 README「自动加载怎么配」。
