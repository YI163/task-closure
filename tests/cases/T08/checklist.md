# T08 判定要点：经验能够影响下一次任务

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T08
- 输入：`tests/cases/T08/input_similar.json`、`input_dissimilar.json`、`experience_seed.json`（`{TASK_ID}` 由运行器替换为真实 task_id）
- 证据目录：`reports/evidence/T08/`
- **依赖说明**：经验检索/写入由 `scripts/exp.py`（t2 交付物，已交付）承担；本场景通过 `exp.py add` 入库，再用 `exp.py search` 分别在相似/不相似任务上真实检索验证。

## 通过标准（spec/04 原文）
1. 相似任务能够检索并考虑该经验；
2. 不相似任务不会仅因字面相似而盲目应用；
3. 使用时说明适用原因和边界；
4. 保留源任务、结果和经验状态。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1/2 检索与不盲目套用 | 依赖 exp.py 检索路径 → 未交付则记「未执行」；可自动部分：`validate.py --all` 必须接受经验数据且 source_task_id 指向真实任务 | 是否说明适用原因与边界 |
| 3 适用原因与边界 | 经验条目 trigger_conditions / limitations 非空 | 边界描述是否真实 |
| 4 保留源任务与状态 | experience.source_task_id 存在；status 在枚举内；confidence 有 basis | 状态是否被夸大 |
