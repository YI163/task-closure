# 开发者说明

> 面向想改代码或扩展这套系统的人。使用者只需看 `README.md` 与 `USER_GUIDE.md`。

---

## 架构一览

```
state/schema.json         数据契约（字段、枚举、必填项）——所有校验的依据
        ↑
scripts/store.py          唯一的数据读写入口（原子写：tmp → fsync → os.replace）
        ↑
scripts/*.py              各功能脚本，全部通过 store.py 读写
        ↑
skills/task-navigator/SKILL.md    行为契约（AI 该怎么做，不是代码）
spec/*.md                 需求与验收依据（脚本会读它判断"做到了没有"）
```

**两条硬规矩**：

1. **任何脚本都不得绕过 `store.py` 直接写 `state/`。** 直接 `write_json` 会跳过校验与写前备份——本项目为此栽过跟头（见下）。
2. **改数据契约（`schema.json`）时必须同步迁移既有数据**，否则校验会全线飘红。

---

## 目录职责

| 目录 | 职责 | 能不能删 |
|---|---|---|
| `nav.py` | 统一入口（只转发，不实现逻辑） | 否 |
| `scripts/` | 全部可执行逻辑 | 否 |
| `skills/task-navigator/` | 给 AI 的行为契约 | 否（删了这套东西就退化成脚本集合） |
| `spec/` | 需求与验收依据 | **否**——8 个脚本会读它 |
| `methods/` | 公开方法论库 | 可（但会失去方法检索） |
| `tests/` | 回归测试（反例 + 场景 + 单测） | **否**——它是「规则不是摆设」的证据 |
| `state/` | 你的数据 | `schema.json` 不可删，其余可重建 |

**`scripts/deprecated/` 不在公开包里**——那是开发仓库的考古区（被取代的旧脚本，
保留只为可追溯）。公开包由 `scripts/build_public_package.py` 按白名单从开发仓库生成。

---

## 脚本依赖关系

改动前先看这张图，避免删掉别人依赖的东西：

```
deliver.py ──→ flowchart.py, coverage_check.py, self_review.py
validate.py ─→ build_index.py
retro.py ────→ build_index.py
export.py ───→ md2html.py
task_update.py ─→ deliver.py
```

**全部脚本**共用 `store.py`。

---

## 加一条新的「检查规则」时必须做的事

这是本项目**用两次事故换来的规矩**：

> **规则写完不算完成，必须当场做反向测试**——造一个违规样本，证明它真的会失败。

原因（两次实测）：

| 事故 | 表面 | 实际 |
|---|---|---|
| 规则只注册了名字 | 看起来有护栏 | 检查代码根本没实现 |
| 检查里有 `except Exception: pass` | 每次校验都"通过" | 一个 `NameError`（缺 `import json`）被静默吞掉，规则从未执行 |

**所以：新规则必须双向测试**——合法样本通过、违规样本失败。只测前者等于没测。

---

## 判据设计的三条经验

同样来自事故：

1. **判据选错了，调阈值救不回来。**
   例：用「一级标题数量」判断"文件是不是多份文档拼接的"——调了三次阈值都误报，
   因为一份长文档内部有 5 个标题完全正常。**最后改用标记法**（合并工具自己写标记）才解决。

2. **判据过宽造成的假阳性，与过窄一样有害，而且更隐蔽。**
   假阳性会训练人忽略警告，最终让真阳性也失效。
   例：判据 `re.compile(r"\d")` 只查"有没有数字"，
   于是 `spec/00`、`EXP-20261015-003`、`2026-06` 都被当成"经营指标的具体数值"。
   **修法：数字必须带度量信号（单位/百分号/小数/≥3位纯数字串）才算。**

3. **不要用配置状态代替运行时证据。**
   例：某插件在配置接口里显示 `inactive`，据此判定"未加载"——随后发现另一个
   同样显示 `inactive` 的插件其实运行正常。**该字段不能作为根因证据。**

---

## 一条铁律：绕过校验器的写入路径 = 假护栏

**任何写入 `state/` 的路径，都必须走「会校验 schema 的入口」。**

事故经过：某脚本用 `f"{entry.get('id', 'TEMP')}.json"` 兜底文件名 + 直接 `write_json`，
于是「忘记给 ID」变成了静默写坏一个文件（`TEMP.json`），校验器随即报 15 个错误。

**判断方法**：如果一条写入路径在数据不合规时**不会报错**，那它就不是护栏。

---

## 测试

测试套件就在 `tests/` 里（不另发「开发仓库」）。四条命令：

```
python nav.py test            一条跑完 7 套（数据校验 + 反例 + 场景 + 4 套单测）
tests/run_tests.py --all      场景测试（端到端，断言驱动；在隔离副本里跑）
tests/invalid/run_rules.py    反例测试（每条校验规则配一个必失败样本）
scripts/validate.py --all     数据完整性校验
```

**改代码后至少跑这三条。** 反例测试是重点——它保证校验规则不是摆设。

**跨平台注意**（v0.1.1 起）：

- 测试运行器用**管道**捕获子进程输出，Windows 的默认文本模式是 cp936，
  所以子进程一律由 `scripts/console.py` 切到 UTF-8，父进程显式按 UTF-8 解码。
  新加的脚本入口必须调用 `console.setup()`，否则「多套测试全部失败、输出为空」。
- 隔离副本由 `scripts/make_test_workspace.py` 建立（纯标准库）。
  旧版 `.sh` 依赖 bash + rsync，Windows 上根本跑不起来。
- 仓库文本文件必须是 **LF**（`.gitattributes` 已固定）；`tests/unit/test_line_endings.py` 守着它。

---

## 提交前自检清单

```
□ python3 nav.py test                      7 套全过（Windows 用 python）
□ 没有任何硬编码绝对路径（grep "/Users/"）
□ 新脚本入口调用了 scripts/console.py 的 setup()（否则管道捕获会崩）
□ 文本文件是 LF（.gitattributes 已固定，不要提交 CRLF）
□ 新脚本不绕过 store.py
□ 新的检查规则做了双向测试（造一个必失败样本证明它会失败）
□ 若改了 schema.json，既有数据已迁移
□ 若加了新脚本，加进 nav.py 的 COMMANDS 表
```

**CI 会自动跑这件事**（`.github/workflows/tests.yml`，Ubuntu + Windows × Python 3.9 / 3.11 / 3.12），
所以本地漏跑也会在 push 时暴露——但别依赖它，等 CI 红一遍再改更慢。

---

## 许可

MIT。改动与再分发请保留 `LICENSE`。
