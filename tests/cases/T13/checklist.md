# T13 判定要点：完成验收不等同于勾选完步骤

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T13
- 输入：`tests/cases/T13/input.json`、`close_partial.json`、`bad_close_unfinished_yes.json`、`bad_status_completed.json`
- 证据目录：`reports/evidence/T13/`

## 通过标准（spec/04 原文）
1. 区分「工作/交付物完成」与「最终目标已实现」；
2. 明确尚待确认事项；
3. 不夸大任务结果。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 区分工作完成与目标实现 | `close` 三问（actions_completed / deliverables_ok / goal_achieved）；goal=partial → status=awaiting_acceptance（**不得为 completed**），verdict 文本为「我方工作已完成，最终目标尚待确认」 | 结论表述是否诚实 |
| 2 明确尚待确认事项 | `pending_external` 非空且出现在输出；next_best_action 指向「等待并跟催外部确认」 | 是否列出了真正的待确认方 |
| 3 不夸大结果（负向） | `status --file {"status":"completed"}` 必须被拒（exit 2）；步骤未完成却声称 actions_completed=yes 必须被拒 | 输出是否夸大了结果 |

## 负向断言（必须真检查）
- 不得用 status 直接置 completed；
- 不得把「勾完步骤」当作「目标达成」。
