# Task Navigator — DSH 项目启动包

这是一个交给 DSH Agent Team 的项目说明与实施约束包。

## 文件

- `00_START_HERE.md`：主入口，告诉 Agent 应按什么顺序阅读并怎样推进。
- `01_PRODUCT_SPEC.md`：完整产品需求、核心流程、范围与原则。
- `02_AGENT_TEAM_PLAYBOOK.md`：队长/队员角色、并行边界、交接、阶段门、可靠性与安全规则。
- `03_SKILLS_AND_EXPERIENCE_MEMORY.md`：任务状态、个人技能、AI 方法库、领域经验库的概念和数据规则。
- `04_ACCEPTANCE_TESTS.md`：可重复的验收场景与完成标准。

## 交给 DSH 时建议怎么做

1. 把整个文件夹交给 DSH，确保 Agent 可以读取全部文件。
2. 对队长说：`请先完整阅读 00_START_HERE.md，并按它的顺序阅读其余文件。先做只读环境审计，随后自主形成 IMPLEMENTATION_PLAN.md 并按阶段推进。不要只给建议或停在计划阶段；除非遇到需要我授权的高风险/不可逆操作，否则自行选择合理且可逆的技术方案，实施、测试、修复并提供证据。Agent Team 的使用遵守 02_AGENT_TEAM_PLAYBOOK.md。`
3. 让队长自主决定实际需要几个队员，不要预先强制每一步都由独立 Agent 实施。
4. 首先检查输出的 `IMPLEMENTATION_PLAN.md` 是否忠于核心目标；队长若没有证据，不得将阶段标记为完成。

## 建议

这是一份产品与执行规格，不意味着文件本身就已实现功能。应由 DSH 根据实际环境完成审计、实施、测试与验收。若现有仓库已有类似能力，应优先评估复用，不要重复造轮子。
