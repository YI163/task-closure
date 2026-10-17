# tests/invalid/ —— 反例样本与回归

**目的**：证明 `scripts/validate.py` 真的会失败，而不是只对合法数据静默通过。
对应 `spec/02 §7`「优先把验证放进工具/脚本，而不是完全依赖模型口头自检」与 `spec/04 T14`。

## 为什么样本放在这里

`state/` 是用户真实数据，任何测试样本都不得写进去。本目录下所有样本都是**独立的最小数据树**，
通过 `validate.py --state-dir <样本>/state` 指向它们校验，真实 `state/` 全程只读
（`run_rules.py` 会在回归前后比对 `state/` 数据文件的 sha256，发生变化就判失败）。

## 目录

| 路径 | 内容 | 期望结果 |
|---|---|---|
| `baseline/state/` | 一份字段完整的合法数据树（含 1 条经验） | `validate.py --all` **exit 0** |
| `baseline/methods/`（以及每个样本的 `<样本>/methods/`） | 方法库 `methods/index.json`。**位置遵循 `schema.methods.file`：相对项目根，不在 `state/` 下**；真实项目里就是 `<项目根>/methods/index.json`（`store.METHODS_PATH`） | 与 `validate.py --all` 读的是同一个相对位置 |
| `rules/R01..R30/` | 每个目录 = 基线 + **恰好一处**改动；`expect.json` 写明期望类型与规则 id | 见下表三种期望：`fail` 必失败 / `pass` 必通过 / `pass_with_warning` 通过但警告必须可见 |
| `backups/hash_mismatch/` | manifest 记录的 sha256 与备份内文件不符（模拟备份损坏） | `--backup-verify` **非零退出**（`B-HASH`） |
| `backups/records_mismatch/` | sha256 正确、manifest 记录的记录数是错的 | `--backup-verify` **非零退出**（`B-RECORDS`） |
| `exp_seam/state/` | 合法数据 + 6 条经验样本（含已失效/被反例挑战/条件不匹配/未执行假设） | 供 `exp.py search` 验证**排除逻辑**；`validate.py --all` exit 0 |
| `exp_conflict/` | 合法数据 + 7 条经验：**三对互相冲突**（建议相反 / 条件互斥 / 反例指向对方结论）+ 1 条干净经验 | 供 `exp.py search` 验证 **G3 冲突提示**；`validate.py --all` exit 0 |
| `exp_privacy/` | 合法基线（含 1 条 general 经验，正文无机密特征） | 供 `exp.py add` 验证 **G4 隐私门禁** 的三个分支 |
| `exp_payloads/` | `exp.py add` 的输入样本（越级写入、结果性结论、合法写入） | 见下表 |
| `_seam_run/` | `exp_seam/` 的副本，**运行产物**：`exp.py add/review` 的写入目标（避免碰真实 `state/experience`） | 可随时删除并重建：`cp -R exp_seam _seam_run` |

## 反例清单（每条规则一个样本）

| 目录 | 注入的违规 | 预期规则 |
|---|---|---|
| R01_missing_required_field | 删掉 `next_best_action` | `T-REQ` |
| R02_task_id_format | `task_id = TN-2026-001` | `T-ID-FMT` |
| R03_task_id_duplicate | 复制出两个相同 task_id | `T-ID-DUP` |
| R04_completed_step_without_evidence | `completed_steps[0].evidence = ""` | `T-EVIDENCE-EMPTY` |
| R05_completed_step_unknown | 完成记录指向不存在的步骤 `S9` | `T-XREF-STEP` |
| R06_step_missing_completion_criteria | standard 深度步骤缺 `completion_criteria` | `T-STEP-REQ` |
| R07_skill_false_upgrade | 只有 `guided_practice` 却写 `can_independently` | `S-UPGRADE` |
| R08_skill_weak_name | `skill_name = "沟通能力很好"` | `S-WEAK-NAME` |
| R09_skill_evidence_dangling_task | 技能证据指向不存在的任务 | `S-XREF-TASK` |
| R10_plan_skill_id_dangling | 计划技能需求指向不存在的 skill_id | `T-XREF-SKILL` |
| R11_exp_unexecuted_as_single_observation | `executed=false` 却写 `single_observation` | `E-STATUS-CTX` |
| R12_exp_claim_without_execution | `executed=false` 却写「显著提升效率」 | `E-CLAIM` |
| R13_exp_dangling_source_task | `source_task_id` 悬空 | `E-SOURCE` |
| R14_exp_empty_trigger_conditions | `trigger_conditions = []` | `E-TRIGGER` |
| R15_exp_challenged_without_counterexample | 标为被反例挑战但 `counterexamples = []` | `E-COUNTEREXAMPLE` |
| R16_method_unverified_without_limitation | 方法 `unverified` 却没有未验证范围说明 | `M-UNVERIFIED` |
| R17_task_completed_without_closed_at | `status=completed` 但缺 `closed_at` | `T-CLOSED-AT` |
| R18_next_best_action_empty | `action`/`reason` 为空 | `T-NBA` |
| R19_history_missing_summary | `history[0]` 缺 `summary` | `T-HISTORY` |
| R20_experience_filename_mismatch | 文件名与 `experience_id` 不一致 | `E-FILENAME` |
| R21_skill_ref_dangling_id | `skill_ref = "SK-20260101-999"`（形如 id 但档案中不存在） | `T-XREF-SKILL`（**必须硬失败**，规则不得弱化） |
| R22_skill_ref_free_text_ok | `skill_ref` 为自由文本（schema 1.1 合法） | **必须 exit 0**，且不得出现 `T-XREF-SKILL`（误报检查） |
| R23_legacy_missing_skill_ref_warn | 仅 `free_text`、缺 `skill_ref`（1.0 旧写法） | **必须 exit 0**，且必须出现警告 `T-STEP-SKILL-LEGACY` 与迁移清单 |
| R24_acceptance_missing_basis | `acceptance.actions_completed.basis` 为空 | `T-ACCEPTANCE` |
| R25_acceptance_verdict_invalid | `acceptance.verdict = "maybe"` | `T-VERDICT` |
| R26_task_verdict_invalid | `tasks[].verdict = "随便写的一句话结论"` | `T-VERDICT-TEXT` |
| R27_plan_history_missing_plan | `plan_history[0]` 缺 `plan` | `T-PLAN-HISTORY` |
| R28_review_history_missing_note | `review_history[0]` 缺 `note`（复核无理由） | `E-REVIEW-HISTORY` |
| R29_counterexample_resolution_missing_resolution | `counterexample_resolutions[0]` 缺 `resolution` | `E-COUNTEREXAMPLE-RES` |
| R30_new_fields_valid_shape | 1.1 新字段全部用**合法形态**填好 | **必须 exit 0**，且六个新规则都不得出现（误报检查） |
| R31_missing_methods_file | 样本树里**不写** `methods/index.json`（必需数据域缺失） | **必须非零退出**，报 `M-FILE` 并指明缺哪个文件（不得记作「未执行=通过」） |
| R32_method_unverified_with_limitation_ok | `verification_status=unverified` 但写明未验证范围 | **必须 exit 0**，且不得出现 `M-UNVERIFIED` / `M-FILE` |
| backups/hash_mismatch | 备份内文件被改动 | `B-HASH` |
| backups/records_mismatch | manifest 记录数写错 | `B-RECORDS` |

## `expect.json` 的三种期望（t6 起）

| kind | 断言 |
|---|---|
| `fail` | `validate.py` 必须**非零退出**，且 stdout 必须出现 `rule` 指定的规则 id |
| `pass` | 必须 **exit 0**；`absent` 列出的规则 id 一律**不得**出现（防「收紧规则后误报合法数据」） |
| `pass_with_warning` | 必须 **exit 0**（警告不得导致失败），且必须出现 `rule`（例：legacy 迁移提醒） |

## 怎么跑

```bash
PY=python3

$PY tests/invalid/make_samples.py     # 重新生成全部样本（只写 tests/invalid/ 内部，有越界断言）
$PY tests/invalid/run_rules.py        # 回归：断言每个反例都失败、基线通过、备份反例失败
$PY tests/invalid/run_rules.py --only R05   # 只跑单个案例
```

单个案例也可以直接手跑，便于看完整输出：

```bash
$PY scripts/validate.py --all --state-dir tests/invalid/rules/R07_skill_false_upgrade/state
$PY scripts/validate.py --backup-verify --backup tests/invalid/backups/hash_mismatch/backups/20260101T000000Z
```

## 经验检索 / 写入 / 复核的样本用法

```bash
# 检索：有适用经验，并显式列出被排除的条目与原因
$PY scripts/exp.py search --query "对比三家竞品并给出汇报用的结论" \
    --domain work --task-type research --experience-dir tests/invalid/exp_seam/state/experience

# 检索：不相关任务 → 空结果（exit 0，且说明「空是合法结果」）
$PY scripts/exp.py search --query "安排线下读书会的场地与签到流程，找同事帮忙" \
    --domain life --task-type coordination --experience-dir tests/invalid/exp_seam/state/experience

# 写入门禁：未执行写成 single_observation → 拒绝
$PY scripts/exp.py add --file tests/invalid/exp_payloads/add_unverified_upgrade.json \
    --experience-dir tests/invalid/_seam_run/state/experience

# 写入门禁：未执行却写结果性结论 → 拒绝
$PY scripts/exp.py add --file tests/invalid/exp_payloads/add_fake_result.json \
    --experience-dir tests/invalid/_seam_run/state/experience

# 合法路径：证据齐全 → 写入（先备份）；未执行 → 只能 to_verify
$PY scripts/exp.py add --file tests/invalid/exp_payloads/add_valid.json \
    --experience-dir tests/invalid/_seam_run/state/experience
$PY scripts/exp.py add --file tests/invalid/exp_payloads/add_hypothesis_ok.json --dry-run \
    --experience-dir tests/invalid/_seam_run/state/experience

# 复核：留历史；未执行条目不得升级
$PY scripts/exp.py review --id EXP-20260201-001 --status repeatedly_supported \
    --note "第二次在同类竞品对比任务中复现同一做法" --experience-dir tests/invalid/_seam_run/state/experience
$PY scripts/exp.py review --id EXP-20260201-005 --status single_observation \
    --note "试图直接升级" --experience-dir tests/invalid/_seam_run/state/experience
```

## 已发现的真实缺陷（保留在案）

* **E-TRIGGER 空数组漏检**：`trigger_conditions: []` 最初被放行（`all()` 对空列表返回 True）。
  由 R14 反例在回归中曝出，已修复为「必须非空数组」。这条正说明反例回归不是形式主义。
* **`last_verified_at: null` 误报**：schema 明确允许 null，首版必填检查误判为「字段为空」，
  已按 schema 的「iso8601 或 null」修正。

## CLI 场景断言（t6 修订轮新增）

`run_rules.py` 除逐样本回归外，还跑两个命令级场景，专门防止「未执行被算成通过」：

| 场景 | 命令 | 断言 |
|---|---|---|
| SC01_显式只选部分域 | `validate.py --tasks --skills` | exit 0；输出必须含「未选择域」「未执行」「部分校验」「不宣称整体通过」；**不得**出现 `结论         : 通过` |
| SC02_完整校验 | `validate.py --all` | exit 0；必须出现方法域记录行 `方法 methods/index.json  记录 N 条` 且结论为 `通过`；**不得**出现 `未执行       :` |

## 语义说明：什么算「未执行」，什么算失败

* **必需数据域文件缺失**（`state/tasks.json`、`state/user_skills.json`、`methods/index.json`）→ **错误 + 非零退出**，并指明缺哪个文件（`T-FILE` / `S-FILE` / `M-FILE`）。
* **显式只选择部分域**（例如 `--tasks --skills`）→ 未选中的域记为「未执行」，允许 exit 0，但结论必须是「部分校验（存在未执行域，不宣称整体通过）」，**不得**显示「通过」。
* **空经验库**（`state/experience/` 不存在或 0 条）→ 记为「0 条」而不是缺失：`store.load_experiences` 对不存在的目录返回空列表，且 `spec/03 §8` 明确「无新经验也是合法结果」。这与 `methods/index.json`（单文件、缺失即缺域）不同。

## G3 / G4 规则与样本（t8 追加）

| 规则 id | 位置 | 内容 | 对应样本 |
|---|---|---|---|
| `G3-CONFLICT-ACTION` | `exp.py search` | recommended_action 语义相反（一侧带否定词 / 相反措辞） | `exp_conflict` EXP-20260401-001 ↔ -002 |
| `G3-CONFLICT-TRIGGER` | `exp.py search` | trigger_conditions 互斥（一侧被否定 / 含互斥词对） | `exp_conflict` EXP-20260401-003 ↔ -004（齐全 / 缺失） |
| `G3-CONFLICT-COUNTEREXAMPLE` | `exp.py search` | 一条的 counterexamples 指向另一条的结论（≥8 字连续相同片段，或直接引用 id） | `exp_conflict` EXP-20260401-005 → -006 |
| `G4-PRIVACY-MARKER` | `exp.py add` | `privacy_scope=general` 且正文命中机密标记 | `exp_payloads/add_general_confidential.json` |
| `G4-PRIVACY-CUSTOMER` | `exp.py add` | 同上，命中客户名称或其占位符（`客户名称：`、`XX 集团`…） | 同上 |
| `G4-PRIVACY-METRIC` | `exp.py add` | 同上，同一字段内同时出现经营指标词与具体数值（如「毛利率 42.3%」） | 同上 |

`run_rules.py` 新增 5 个命令级场景（含"必须拒绝"与"确认后必须能写入"两个方向）：

| 场景 | 命令要点 | 期望 |
|---|---|---|
| SC03 | `exp.py search` on `exp_conflict` | exit 0；含【冲突提示】与三类规则；**恰好 3 对冲突**；冲突条目不得出现在「✓ 可采用」行内（行级断言） |
| SC04 | `exp.py add` on `exp_privacy`（general + 机密，无 ack） | exit 1；列出 14 处命中位置；含「不能替代人工判断」；不得出现「已写入」 |
| SC05 | 先重建 `_seam_privacy_run` 副本，再 `exp.py add --privacy-ack` | exit 0；**文件确实生成**（`expect_file` 断言）；含「已确认…按使用者的决定继续写入」 |
| SC06 | `exp.py add` 同样内容但 `privacy_scope=work` | exit 0；不得出现 `【隐私检查】`/拒绝（跨域检查只针对 general） |
| SC07 | `exp.py add` 未执行写成 single_observation | exit 1 `E-STATUS-CTX`（证明既有门禁未弱化） |

`_seam_privacy_run/` 是 SC05 的运行产物目录，每次回归自动重建，已从「样本未被改动」指纹比对中排除。
