#!/usr/bin/env bash
# make_test_workspace.sh —— 建立隔离的测试副本（见 docs/TEST_ISOLATION.md）
#
# 用法：bash scripts/make_test_workspace.sh <副本名>
#   例：bash scripts/make_test_workspace.sh t4-run1
#
# 作用：把正式项目复制到 outputs/test-workspaces/<副本名>/，让测试在副本里真实执行，
#       从而不必也不得写入正式 state/。脚本只读取正式项目，唯一的写入目标是副本目录。
#
# 退出码：0 成功；1 参数错误；2 目标已存在（不覆盖已有副本）；3 缺少必要文件

set -euo pipefail

NAME="${1:-}"
if [[ -z "$NAME" ]]; then
  echo "用法：bash scripts/make_test_workspace.sh <副本名>" >&2
  exit 1
fi
if [[ ! "$NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "副本名只能包含字母、数字、点、下划线、连字符：$NAME" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PROJECT_ROOT/outputs/test-workspaces/$NAME"

# 安全检查：目标必须落在正式项目的 outputs/test-workspaces 之内
case "$DEST" in
  "$PROJECT_ROOT"/outputs/test-workspaces/*) ;;
  *) echo "拒绝写入意外路径：$DEST" >&2; exit 1 ;;
esac

if [[ -e "$DEST" ]]; then
  echo "副本已存在，不覆盖（每次验证应建新副本）：$DEST" >&2
  exit 2
fi

for required in state/schema.json scripts/store.py skills/task-navigator/SKILL.md; do
  if [[ ! -e "$PROJECT_ROOT/$required" ]]; then
    echo "正式项目缺少必要文件：$required" >&2
    exit 3
  fi
done

mkdir -p "$DEST"

# 用 rsync 精确排除：备份、git、历史副本
rsync -a \
  --exclude 'state/backups/' \
  --exclude '.git/' \
  --exclude 'outputs/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$PROJECT_ROOT"/ "$DEST"/

mkdir -p "$DEST/state/backups"

COMMIT="$(cd "$PROJECT_ROOT" && git rev-parse HEAD 2>/dev/null || echo '（非 git 仓库或无提交）')"
cat > "$DEST/TEST_WORKSPACE_ORIGIN.txt" <<EOF
隔离测试副本
副本名        : $NAME
建立时间      : $(date '+%Y-%m-%d %H:%M:%S %z')
来源项目      : $PROJECT_ROOT
来源提交      : $COMMIT
用途          : T01–T14 真实执行；本副本内的所有改动都不影响正式项目
EOF

echo "隔离副本已建立：$DEST"
echo "来源提交：$COMMIT"
echo
echo "下一步："
echo "  cd $DEST"
echo "  然后按 tests/cases/ 里的场景执行；原始输出请写回正式项目的 reports/evidence/"
