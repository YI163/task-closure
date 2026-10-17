# T03 判定要点：复杂工作任务产生可执行 SOP

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T03
- 输入：`tests/cases/T03/input.json`（「周五前研究三家竞品，给经理做汇报。」）
- 证据目录：`reports/evidence/T03/`

## 通过标准（spec/04 原文）
1. 明确任务目标、交付物、工作拆分、依赖和验收标准；
2. 标注至少一个有实际决策意义的阶段检查/汇报节点；
3. 对重要事实记录来源；
4. 给出时间安排时明确估算假设；
5. 提醒在开始大量调研前确认研究目标/范围。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 目标/交付物/拆分/依赖/验收 | goal 与 success_criteria 非空；plan ≥ 3 步且每步含 deliverable+completion_criteria；存在 inputs_or_dependencies 关系 | 拆分是否真的可执行 |
| 2 阶段检查节点 | 至少 1 步 communication 非空，且与决策相关（启动确认范围或汇报前确认口径） | 该节点是否真有决策意义 |
| 3 事实来源 | 至少 1 条 evidence 含非空 source | 来源是否权威可核实 |
| 4 估算假设 | standard/deep 每步 time_estimate 均有 estimate_basis | 估算是否现实 |
| 5 调研前确认范围 | S1 的 communication/purpose 明确「启动确认目标与范围」 | 是否在正文中真的提醒了 |
