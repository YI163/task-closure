# T07 判定要点：新情况触发重规划

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T07
- 输入：`tests/cases/T07/input.json`、`change_urgent.json`（期限周五→周三 + 资料未到位）、`bad_change_no_impact.json`、`bypass_plan_missing_criteria.json`
- 证据目录：`reports/evidence/T07/`
- 模式：状态变化可自动断言；「沟通建议是否到位」属模型判断，交审查员判定。

## 通过标准（spec/04 原文）
1. 识别期限与依赖变化；
2. 评估影响并调整范围/优先级/时间；
3. 标明哪些质量标准不可随意牺牲；
4. 建议及时沟通风险与可选方案，而不是静默继续旧计划。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 识别期限与依赖变化 | `changes[]` 新增 1 条，含 changed_at/what/why/impact；deadline 已更新为「本周三」 | 是否识别出「资料未到位」这一依赖变化 |
| 2 评估影响并调整范围 | 新计划步骤数少于旧计划；impact 非空；plan_history 归档了旧计划 | 调整是否合理、是否只是砍掉必要工作 |
| 3 质量标准不可牺牲 | quality_floor 非空且明确（不得编造数据） | 声明的质量底线是否真的守住 |
| 4 及时沟通风险（非静默） | 新计划含 communication「立即升级」节点 | 沟通建议是否具体可执行（这是模型判断） |

## 负向断言
- `change` 缺 impact → 必须被拒（exit 2）；
- 旧计划必须归档（plan_history），不得静默覆盖。
