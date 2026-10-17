# T04 判定要点：识别技能缺口

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T04
- 前置条件：`state/user_skills.json` 存在（当前 8 条，含 SK-20261014-001「Excel 数据透视表：按部门统计离职数据」，status=can_with_checklist）
- 输入：`tests/cases/T04/input.json` + `tests/cases/T04/skillgap_S2.json`
- 证据目录：`reports/evidence/T04/`

## 通过标准（spec/04 原文）
1. 系统识别所需技能与档案中的缺口；
2. 给出替代方案、分步教学、检查表或求助/委派选项；
3. 根据期限和学习价值推荐适当路径；
4. 计划中明确每一步的验证方式；
5. 不默认用户已经会操作。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 识别缺口 | 步骤 required_skills 的 skill_id 存在于 user_skills.json；该技能 status ≠ can_independently 且 known_gaps 非空 | 缺口判断是否与任务实际所需能力吻合 |
| 2 给替代/分步/检查表 | `task_update.py skillgap` 记录 adaptation 非空，且含检查表/分步/求助之一 | 给出的方案是否真的能落地 |
| 3 按时限与学习价值推荐路径 | — | 是需审查员判定：路径选择理由是否成立 |
| 4 每步验证方式 | 每步均有 completion_criteria（可核对的验证方式） | 验证方式是否可独立核对 |
| 5 不默认会操作 | 步骤 status 非 done；无「用户已掌握」类记录 | 文本中是否默认用户会操作 |
