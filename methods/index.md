<!-- AUTO-GENERATED — 自动生成，请勿手工编辑（DO NOT EDIT BY HAND） -->
# AI 方法/Skill 库索引（自动生成，请勿手工编辑）

> ⚠️ **本文件是派生产物，不是权威数据。** 方法条目的唯一权威来源是 `methods/index.json`。
> 若本文件与 `methods/index.json` 不一致，**以 JSON 为准**，并重新运行生成命令（见 `reports/METHOD_RESEARCH.md` §9.2）。
> 手工编辑本文件会在下次生成时被覆盖，并造成与权威数据的漂移。

## 元信息（由生成器写入）

- 生成来源（authoritative source）：`methods/index.json`
- 生成来源 SHA256：`670d82b6d1341546edaf89220d2b4070eb35cb113e600f62961696bd319c6a22`
- 生成时间（UTC）：`2026-10-14T16:21:47Z`
- 方法条目数：8
- 生成器：python3 标准库内联脚本（仅读 JSON、只写本文件；命令见报告 §9.2）
- 权威性说明：机器（Skill/脚本）应读 `methods/index.json`；本文件只供人阅读与快速浏览
- 目录
  1. [结构化问题解决与问题树（Issue Tree / MECE）](#1-structured-problem-solving-issue-tree)
  2. [工作分解结构（WBS, Work Breakdown Structure）](#2-wbs)
  3. [阶段门与里程碑审查（Phase-Gate / Milestone Review）](#3-phase-gate-milestone)
  4. [责任与决策角色分配（RACI / DACI）](#4-raci-daci)
  5. [计划-执行-检查-处理循环（PDCA；Deming 变体 PDSA）](#5-pdca)
  6. [风险矩阵（Risk Matrix：可能性 × 影响）](#6-risk-matrix)
  7. [预演失败（Pre-mortem，事前验尸）](#7-premortem)
  8. [完成定义与验收检查表（Definition of Done / Checklist）](#8-definition-of-done-checklist)

## 1. 结构化问题解决与问题树（Issue Tree / MECE）

- `method_id`: `structured-problem-solving-issue-tree`
- **名称**：结构化问题解决与问题树（Issue Tree / MECE）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：research、decision、other
- **解决的问题**：面对笼统、结论不明的难题（如「竞品研究从哪下手」「业绩为什么没达标」），不知道该先查什么、问题到底出在哪一层。
- **预期结果**：一棵层级化问题树：主问题→子问题→可查证的末级问题；互斥且合起来覆盖主要可能（MECE），并标出关键假设与查证优先级。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/structured-problem-solving-issue-tree.md`](structured-problem-solving-issue-tree.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "structured-problem-solving-issue-tree"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 目标清楚、步骤已知（如「按清单把行李装好」）——直接给行动清单成本更低
- 问题本质是执行遗漏而非判断困难（如「忘了提交表格」）——补一个动作即可，不需要问题树
- 没有任何可获取的信息源，拆分出的叶节点无法被核验——应先取得信息或降低目标
- 时限极短（例如 15 分钟内要答复）——拆分的时间成本超过收益
- 用户已明确指定了方法与答案，只需要执行与确认——再拆树属于机械套框架

### 来源

- `source.kind`：`public_framework`
- `source.citation`：Barbara Minto《The Pyramid Principle: Logic in Writing and Thinking》（Pearson；ISBN 978-1-292-76325-5，书目信息来自公开书商/检索结果）——MECE 与金字塔结构化分析的公开出版物来源；公开术语解释页 https://untools.co/issue-tree/（2026-10-14 实取，HTTP 200，含 issue tree）。本条目使用公开通用方法，不声称问题树/MECE 是任何咨询公司的内部专有 SOP。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- Minto 一书为纸本出版物，本次网络受限，未能打开出版方页面完成在线核验，ISBN 来自第三方书目检索结果
- 「MECE」一词的原始出处未追溯核验
- 常见归属「McKinsey 内部标准做法」未获任何官方文件核实，本条目不作此声称
- 本条目步骤为研究者依据公开描述改写，尚未在 Task Navigator 的真实任务中执行验证（无 single_use 证据）

### 相关方法与验收测试

- `related_method_ids`：`wbs`、`premortem`、`definition-of-done-checklist`
- `related_test_ids`：`T02`、`T03`
- `tool_requirements`：无外部依赖；结果写回 state/tasks.json 的 assumptions/unknowns/plan 与 evidence 字段

## 2. 工作分解结构（WBS, Work Breakdown Structure）

- `method_id`: `wbs`
- **名称**：工作分解结构（WBS, Work Breakdown Structure）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：execution、writing、coordination、other
- **解决的问题**：交付物大而模糊（如「做一份季度汇报」「办一次家庭聚会」），不清楚要分成哪些工作包、依赖是什么、做到什么算完成。
- **预期结果**：一份以交付物（而非动作）为节点、逐层拆到可估算可验收的工作包清单；每个工作包有编号、负责人、完成标准，可直接对接计划、责任与验收。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/wbs.md`](wbs.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "wbs"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 任务只有 1–2 个动作、不需要协调（如「把文件发过去」）——直接做
- 交付物尚未定型、还在确认用户到底要什么——先做问题树/研究，之后再来分解
- 高度不确定、边做边学的任务——用 PDCA 小步试验比一次性分解更合适
- 分解结果没有任何人会用来排期、分工或验收——纯形式化的分解是成本
- 截止时间在前而分解需要数小时——用行动清单替代，事后再补结构

### 来源

- `source.kind`：`official_doc`
- `source.citation`：ISO 21511:2018 Work breakdown structures for project and programme management——ISO/TC 258 官方项目页 https://committee.iso.org/sites/tc258/home/projects/published/iso-21511-ed1.html（2026-10-14 实取，HTTP 200，页面含 work breakdown 9 处、21511 5 处；官方项目详情页 https://www.iso.org/standard/69702.html）。补充书目（本次未能打开，pmi.org 返回 403）：PMI《Practice Standard for Work Breakdown Structures》Third Edition。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- ISO 21511 是付费标准，本次只核验了 ISO/TC 258 官方页面上的范围描述，未读取标准正文
- PMI 的 WBS 实践标准本次无法访问（HTTP 403），仅作为书目补充，未核验内容
- 本条目中的「100% 规则」「可估算粒度」等操作细节是依据公开描述改写的做法，未逐条与标准原文比对
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`phase-gate-milestone`、`raci-daci`、`definition-of-done-checklist`
- `related_test_ids`：`T03`、`T04`
- `tool_requirements`：无外部依赖；工作包可写入 state/tasks.json 的 plan[].name 与 completion_criteria

## 3. 阶段门与里程碑审查（Phase-Gate / Milestone Review）

- `method_id`: `phase-gate-milestone`
- **名称**：阶段门与里程碑审查（Phase-Gate / Milestone Review）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：execution、coordination、research、other
- **解决的问题**：跨多天/多方的任务容易一路做到底才发现方向错了；缺少「该不该继续投入」的强制停下判断点。
- **预期结果**：任务被划分为若干阶段，阶段之间设可判断的进入/退出准则（门）；每个门只产生「通过 / 带条件通过 / 暂停 / 终止」四种结果，并留下依据记录。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/phase-gate-milestone.md`](phase-gate-milestone.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "phase-gate-milestone"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 单步、短时即可完成的任务——设门变成纯仪式
- 阶段之间没有真实依赖、可以并行推进——用并行清单而非串行门
- 决策权不在场（无人能批准继续）——门会空转，应先确认谁有权决定
- 期限极紧且不存在值得中途放弃的情形——用轻量检查点替代否决门
- 用户只需要一份清单而不需要汇报节点——不要为了规范而加门

### 来源

- `source.kind`：`official_doc`
- `source.citation`：NASA NPR 7120.5F《NASA Space Flight Program and Project Management Requirements》Chapter 2（官方指令，2026-10-14 实取，HTTP 200；该页原文：Life cycles include life-cycle phases, gates, and major events; performing KDPs and major life-cycle reviews (LCRs)；页面中 KDP 82 处、life-cycle review 4 处）。另：Stage-Gate® 是 Stage-Gate International / Robert G. Cooper 的公开商标框架，其官方公开说明 https://www.stage-gate.com/blog/industry-standard-stage-gate-innovation-process-for-new-products-and-technologies/（2026-10-14 实取，HTTP 200）。本条目使用的是通用「阶段门/里程碑审查」概念，不声称其为任何机构内部专有流程。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- 本次只读取了 NASA NPR 7120.5F 的 Chapter 2 网页版，未通读全篇要求（PDF 下载超时/限流 429）
- Stage-Gate® 的商业实现细节需付费培训或出版物，本条目未使用其专有模板，只采用公开的通用阶段门概念
- 「阶段门是否真的能减少返工」在本项目中尚无实测数据
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`definition-of-done-checklist`、`risk-matrix`、`wbs`
- `related_test_ids`：`T03`、`T07`、`T13`
- `tool_requirements`：无外部依赖；门的结论写入 state/tasks.json 的 plan 步骤状态、decisions 与 changes

## 4. 责任与决策角色分配（RACI / DACI）

- `method_id`: `raci-daci`
- **名称**：责任与决策角色分配（RACI / DACI）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：coordination、decision、execution
- **解决的问题**：多方参与时「谁做、谁批、谁必须被咨询、谁只需知情」含混，导致重复劳动、越权拍板或事后互相推责。
- **预期结果**：一张可执行的角色/决策表：每个关键活动恰好一个最终负责人（A），每项决策有明确的批准者、依据与时间。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/raci-daci.md`](raci-daci.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "raci-daci"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 只有用户一个人执行与决策——写出责任人是自己的表没有使用价值
- 分工已清楚且被各方确认——重复制表只会增加沟通成本
- 无法识别决策者或组织不允许明确责任——先解决授权问题，否则表格是空文
- 被用作事后追责工具而不是协作工具——会把责任表变成政治工具
- 小任务且外部协作只涉及一次性交付——用一句「谁在何时交什么」即可

### 来源

- `source.kind`：`official_doc`
- `source.citation`：美国 GSA Section508.gov《RACI Matrix for Section 508 Accessibility Integration in the Software Development Lifecycle》https://www.section508.gov/develop/raci-matrix-for-section-508-in-sdlc/（2026-10-14 实取，HTTP 200，含 RACI 6 处与 R/A/C/I 定义）；Atlassian Team Playbook《DACI: A Decision-Making Framework》https://www.atlassian.com/team-playbook/plays/daci（2026-10-14 实取，HTTP 200，DACI 28 处、Approver 7 处）。两者均为公开文档，非任何机构内部专有 SOP。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- section508.gov 页面给出的是 RACI 在特定场景（无障碍合规）下的应用，未覆盖所有组织变体（如 RASCI、CAIRO）
- Atlassian 的 DACI 是其公开玩法说明，不是行业标准组织发布的规范
- 「一线一个 A」等规则来自公开描述与常见实践，本次未逐条比对 ISO/PMI 正式文本
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`wbs`、`phase-gate-milestone`
- `related_test_ids`：`T03`、`T07`、`T11`
- `tool_requirements`：无外部依赖；角色/决策信息写入 state/tasks.json 的 decisions 与 plan[].communication

## 5. 计划-执行-检查-处理循环（PDCA；Deming 变体 PDSA）

- `method_id`: `pdca`
- **名称**：计划-执行-检查-处理循环（PDCA；Deming 变体 PDSA）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：execution、learning、other
- **解决的问题**：面对「怎么做才有效还不知道」的任务（如调整作息、试新工作流程、改进写作方法），一次性大计划容易方向错误且无法从结果学习。
- **预期结果**：一个短试验循环：小范围试一次 → 用事先定好的指标看结果 → 保留有效部分、修正或放弃无效部分，并把结论写回计划或经验库（未验证的只能记为待验证假设）。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/pdca.md`](pdca.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "pdca"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 不可逆或高风险的一次性动作（提交申请、发布公告、医疗决策）——不能试错，应用检查表/阶段门
- 没有第二次机会的一次性事件（婚礼当天、只此一次的考试）——应做预案与彩排
- 反馈周期远长于任务期限（例如三个月才知道效果）——先做研究与决策，并明确说明本任务内无法验证
- 步骤已知的纯执行任务——按清单执行更省成本
- 指标完全无法观察（无数据、无人记录）——此时 PDCA 会退化为「凭感觉打勾」

### 来源

- `source.kind`：`official_doc`
- `source.citation`：美国 EPA《Develop an EMS》中的 Overview of the Plan-Do-Check-Act Cycle https://www.epa.gov/ems/develop-ems（2026-10-14 实取，HTTP 200，Plan-Do-Check-Act 2 处、PDCA 2 处）。标准背景：ISO 9001 家族以 PDCA 为组织框架；ISO 9001:2015 已于 2026-09-16 撤销，现行版为 ISO 9001:2026（https://www.iso.org/standard/9001，2026-10-14 实取 HTTP 200）。Deming 本人偏好的表述为 PDSA(Plan-Do-Study-Act)，本次未能核实（deming.org 返回 403），故仅在报告中列为待确认。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- EPA 页面是环境管理体系（EMS）语境下的 PDCA 应用，不等于通用任务管理规范
- 本次未读取 ISO 9001:2026 正文（付费标准），只核验了官方页面与版本状态
- PDCA 与 PDSA 的命名差异及其重要性未获一手来源核实（deming.org 403）
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`structured-problem-solving-issue-tree`、`phase-gate-milestone`
- `related_test_ids`：`T09`、`T07`
- `tool_requirements`：无外部依赖；每轮结果写入 state/tasks.json 的 completed_steps/evidence 或 state/experience/（需证据门槛）

## 6. 风险矩阵（Risk Matrix：可能性 × 影响）

- `method_id`: `risk-matrix`
- **名称**：风险矩阵（Risk Matrix：可能性 × 影响）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：decision、execution、coordination、other
- **解决的问题**：多条风险混在一起，无法决定先防哪一条、哪些可以接受、哪些必须升级或修改计划。
- **预期结果**：一份带等级、责任人、应对方式与复查时间的风险清单，并明确哪些是必须升级的高风险、哪些残余风险被谁接受。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/risk-matrix.md`](risk-matrix.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "risk-matrix"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 风险只有 1–2 条且显然——直接写明并处理即可
- 没有任何信息可用于判断可能性与影响——应先生成信息，否则矩阵是拍脑袋填充
- 风险已被法规/合同强制处理、没有选择余地——按既有规则执行即可
- 用矩阵制造虚假精确（无数据却把等级写成 3.7 分）——应退回高/中/低三档
- 风险清单会包含不愿被记录的敏感信息（如工作机密）——先确认存储范围与隐私边界

### 来源

- `source.kind`：`official_doc`
- `source.citation`：NIST SP 800-30 Rev. 1《Guide for Conducting Risk Assessments》(2012-09)，DOI 10.6028/NIST.SP.800-30r1；页面 https://csrc.nist.gov/pubs/sp/800/30/r1/final（2026-10-14 实取，HTTP 200，risk assessment 11 处）；PDF https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-30r1.pdf（2026-10-14 实取，HTTP 200，PDF 书签含 likelihood of occurrence 与 impact）。补充：ISO 31000:2018 Risk management — Guidelines（https://www.iso.org/standard/65694.html；2026-10-14 曾读取到 HTTP 200 与识别/分析/评价/处置内容，同日稍后再取返回 403 属访问限制）。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- NIST SP 800-30 面向信息系统安全风险评估，本次只核验了页面与 PDF 书签结构，未通读全文，也未采用其完整评估流程
- ISO 31000:2018 为付费标准，本次只读到公开页面描述；同一 URL 的重复访问出现 403，稳定性有限
- 风险矩阵的「等级 = 可能性 × 影响」为常见实践；其对具体任务决策的预测效度在本项目中无实测数据
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`premortem`、`phase-gate-milestone`
- `related_test_ids`：`T07`、`T10`、`T11`
- `tool_requirements`：无外部依赖；风险写入 state/tasks.json 的 risks 字段（含复查时间），敏感内容按 privacy_scope 控制

## 7. 预演失败（Pre-mortem，事前验尸）

- `method_id`: `premortem`
- **名称**：预演失败（Pre-mortem，事前验尸）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：decision、execution、coordination
- **解决的问题**：计划阶段容易过度乐观，参与者不愿（或不敢）公开质疑，失败原因往往在失败之后才被发现。
- **预期结果**：在计划定稿前得到一份「失败已经发生」的反向原因清单，并据此补充预案、早期信号、检查点，或直接修改计划。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/premortem.md`](premortem.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "premortem"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 任务简单、失败后果轻微（如打印一页文档）——成本大于收益
- 可逆的小决定且试错成本极低——直接试比讨论更省
- 计划尚未成型（还在收集需求阶段）——会退化为空泛担忧
- 环境不允许质疑且无法改变——先解决心理安全，否则只会得到沉默
- 已明确要求「就按这个方案做」，预演结论不会被采用——此时改为记录风险清单即可

### 来源

- `source.kind`：`public_framework`
- `source.citation`：Gary Klein, Performing a Project Premortem, Harvard Business Review, September 2007（reprint F0709A）https://hbr.org/2007/09/performing-a-project-premortem（2026-10-14 实取，HTTP 200，premortem 41 处、Klein 11 处；文中描述：团队假设计划中的项目刚刚失败，然后给出可能的失败原因）。研究基础常引 Mitchell, Russo & Pennington (1989), Journal of Behavioral Decision Making 2(1)，DOI 10.1002/bdm.3960020103——本次仅确认 DOI 可解析并重定向至 Wiley，全文页返回 403，未读取原文，因此不引用其具体百分比结论。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- HBR 正文为付费墙后的摘要页，本次核验到作者、期号、重印号与核心方法描述，未读取完整正文
- 「前瞻性后见之明（prospective hindsight）提升原因识别率 30%」一类数字为二手常见引用，本次未验证原论文，故本条目不写该数字
- 方法在单用户 + AI 场景下的有效性（缺少多人独立视角）未经实测
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`risk-matrix`、`structured-problem-solving-issue-tree`
- `related_test_ids`：`T02`、`T07`、`T13`
- `tool_requirements`：无外部依赖；失败原因与预案写入 state/tasks.json 的 risks 与 plan[].risks_and_fallbacks

## 8. 完成定义与验收检查表（Definition of Done / Checklist）

- `method_id`: `definition-of-done-checklist`
- **名称**：完成定义与验收检查表（Definition of Done / Checklist）
- **适用任务类型**（`state/schema.json` 的 task_type 枚举）：execution、writing、research、decision、other
- **解决的问题**：「做完了」没有共同标准：步骤全部勾选但交付物不达标，或关键决策人尚未确认就被当成任务完成。
- **预期结果**：事先写好的完成定义与可勾选检查表；结束时能明确区分「交付物达标」「目标已实现」「仍依赖他人确认」三种状态，并有证据位置。
- **verification_status**：`unverified`（枚举值 `method_verification`；含义见 `state/schema.json`）
- **正文（步骤/检查表/模板/失败处理）**：[`methods/definition-of-done-checklist.md`](definition-of-done-checklist.md)
- **本节数据的权威位置**：`methods/index.json` → `methods[?].method_id == "definition-of-done-checklist"`

### 不适用情况（`not_applicable_when`：命中任意一条就不要用这个方法）

- 结果完全由外部决定、无法预先定义标准（如等待抽签结果）——只能写清我方完成范围，不能写成果标准
- 目标本身尚未确定（还在探索要什么）——先确认目标，否则标准会写空
- 检查表被当成形式（全部打勾却无人看内容）——会制造虚假安全感，应先修复验收角色
- 救急任务且时间极紧——可以事后补检查，但必须标注标准是事后补写的
- 一次性小事（如「明早带伞」）——一句完成标准已足够，不需要表

### 来源

- `source.kind`：`official_doc`
- `source.citation`：Ken Schwaber & Jeff Sutherland《The Scrum Guide》(2020 年 11 月版，CC BY-SA 4.0)——Definition of Done 的正式定义：a formal description of the state of the Increment when it meets the quality measures required for the product. https://scrumguides.org/scrum-guide.html（2026-10-14 实取，HTTP 200，Definition of Done 16 处）；官方 PDF https://scrumguides.org/docs/scrumguide/v2020/2020-Scrum-Guide-US.pdf（2026-10-14 实取，HTTP 200）。本项目验收清单本身的依据：spec/04_ACCEPTANCE_TESTS.md §4 Definition of Done。
- `source.retrieved_at`：`2026-10-14`

### 未验证范围（`limitations`；`verification_status=unverified` 时必须存在）

- Scrum Guide 的 Definition of Done 面向软件产品增量，本条目把它扩展为通用交付物检查表，属研究者改写，未逐条与原文对应
- spec/04 §4 的 DoD 是针对本项目 MVP 的验收清单，不是通用任务方法
- 检查表能否真正阻止「勾选即完成」的误判，需在真实任务中验证
- 尚未在 Task Navigator 的真实任务中执行验证

### 相关方法与验收测试

- `related_method_ids`：`phase-gate-milestone`、`wbs`
- `related_test_ids`：`T01`、`T03`、`T11`、`T13`
- `tool_requirements`：无外部依赖；验收结论写入 state/tasks.json 的 success_criteria、completed_steps[].evidence 与 status

---

## 生成与一致性校验

生成命令（在项目根目录执行）：

```bash
python3 - <<'PY'   # 读取 methods/index.json，重写本文件；脚本见 reports/METHOD_RESEARCH.md §9.2
PY
```

一致性校验命令与原始输出见 `reports/METHOD_RESEARCH.md` §9.3（比对 `method_id` 集合、缺失/多余条目、重复条目与可重现性）。
