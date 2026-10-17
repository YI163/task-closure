# T10 判定要点：冲突/过时经验得到处理

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T10
- 输入：`tests/cases/T10/experience_conflict_a.json` 与 `experience_conflict_b.json`（互相矛盾）、`experience_stale.json`（review_after 已过期）
- 证据目录：`reports/evidence/T10/`
- **依赖说明**：入库、检索与复核路径由 `scripts/exp.py`（t2 交付物，已交付）承担并真实执行；冲突「如何裁决」的表述仍属模型判断，交审查员判定。

## 通过标准（spec/04 原文）
1. 识别冲突/过时风险；
2. 不随机挑一条当作事实；
3. 比较上下文与证据，必要时重新研究或标记未知；
4. 在任务决策中保留不确定性。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 识别过时风险 | `validate.py` 必须对 review_after 已过期的条目给出 E-STALE 警告（文本含 E-STALE） | 是否把过期当作事实使用 |
| 1b 冲突样本可被识别 | 两条矛盾经验同时存在于 state/experience/ 且校验通过（数据层可见其上下文与证据） | 是否识别出二者适用条件不同（30 人 vs 5 人） |
| 2 不随机挑一条当事实 | — | 是：输出中是否只挑一条并当事实 |
| 3/4 保留不确定性 | — | 是：是否比较上下文、是否标记未知 |
