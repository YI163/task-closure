# T14 判定要点：数据更新具备恢复手段

- 来源：spec/04_ACCEPTANCE_TESTS.md §2 T14
- 输入：`tests/cases/T14/scenario.json`
- 证据目录：`reports/evidence/T14/`

## 通过标准（spec/04 原文）
1. 修改前具备备份或其他可恢复机制；
2. 对记录数量、必填字段和数据完整性做检查；
3. 迁移失败时不会静默丢失原始数据；
4. 报告实际迁移和验证结果。

## 判定方式
| 要点 | 自动化断言 | 需独立审查员判定 |
|---|---|---|
| 1 修改前有备份 | 每次写入后 `state/backups/<UTC时间戳>/` 新增，且含 manifest.json | 备份是否覆盖了被改动的文件 |
| 2 记录数与完整性检查 | `validate.py --backup-verify` 通过（B-MANIFEST/B-HASH/B-RECORDS），manifest 含 sha256 与 records | 检查项是否足够 |
| 3 不静默丢数据（负向） | 把 tasks.json 写成非法 JSON → `validate.py --all` 必须非零退出并报 JSON-BROKEN（不静默通过） | — |
| 4 报告迁移与验证结果 | 用备份文件恢复后 sha256 与改写前一致（真实恢复动作） | 报告是否与实际一致 |
