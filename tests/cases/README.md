# tests/cases —— T01–T14 固定用例

- 判定标准来源：`spec/04_ACCEPTANCE_TESTS.md` §2（逐条抄录到各 `Txx/checklist.md`，不自行改写）。
- 固定输入：每个 `Txx/` 目录内的 `*.json` 即该场景的固定输入文件。
- 运行方式：在正式项目根目录执行

  ```bash
  python3 tests/run_tests.py --all
  ```

  运行器会先按 `docs/TEST_ISOLATION.md` 建立**新的隔离副本**，全部场景都在副本内执行；
  原始输出写回 `reports/evidence/<测试号>/`，汇总报告写回 `reports/TEST_RUN_REPORT.md`。

- 固定输入中的 `{TASK_ID}` 占位符由运行器替换为本次实际创建的 task_id（用于经验的 `source_task_id` 跨引用）。
- 用例不得为了让结果好看而删除或弱化；失败如实记录（见 `tests/run_tests.py` 的结果分类）。
