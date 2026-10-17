# T05 判定要点：技能状态不会虚假升级

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T05
- 前置条件：`state/user_skills.json` 存在真实档案（SK-20261014-001 仅有 self_report 证据）
- 输入：`tests/cases/T05/mutation_upgrade.json`（反例：仅有 self_report 却置 can_independently）、`tests/cases/T05/positive_control.json`（阳性对照：有 independent_operation 证据保持 can_independently）
- 证据目录：`reports/evidence/T05/`

## 通过标准（spec/04 原文）
1. 记录「在指导下完成」的证据；
2. 不自动把技能状态提升到「可独立完成」；
3. 说明若要验证独立掌握，需要何种表现或小测试。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 记录指导证据 | 完成步骤后可写入 guided_practice/self_report 类证据（`task_update.py step` 的 verification 字段） | 证据描述是否真实可核对 |
| 2 不得虚假升级（负向） | 反例 state 目录 → `validate.py --state-dir` 必须非零退出且报 S-UPGRADE；阳性对照必须通过 | — |
| 3 说明如何验证独立掌握 | 档案 known_gaps 中写明「需要一个具体实例来支持升级」 | 给出的验证方式是否可执行 |

## 负向断言（必须真检查）
- 仅有 guided_practice/self_report 的技能**不得**被接受为 can_independently。
