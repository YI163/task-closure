# T09 判定要点：经验库拒绝未经验证的成功经验

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T09 + state/schema.json experiences.field_rules
- 输入：`tests/cases/T09/bad_experience.json`（executed=false 却写「显著提升效率」+ status=single_observation）、`good_experience.json`（executed=false + status=to_verify，合法落点）
- 证据目录：`reports/evidence/T09/`

## 通过标准（spec/04 原文）
1. 不保存为已验证经验；
2. 可以保存为待验证假设，或要求提供实际结果证据；
3. 不虚构结果或证据。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 不写成已验证（负向） | 反例 state → `validate.py --state-dir` 必须报 E-STATUS-CTX（executed=false 不得 single_observation/repeatedly_supported）且非零退出 | — |
| 1b 结果性结论（负向） | 同一反例必须同时报 E-CLAIM（executed=false 不得写「显著提升」类结论） | — |
| 2 待验证假设可保存 | 阳性样本 status=to_verify + executed=false → 校验必须通过（exit 0） | — |
| 3 不虚构结果 | 反例的 evidence 为空数组（若被接受即为虚构） | 输出文本是否编造了结果 |

## 负向断言（必须真检查）
- 未执行的方法不得落为 single_observation/repeatedly_supported；
- 不得写「显著提升效率」「实测有效」类结果性结论。
