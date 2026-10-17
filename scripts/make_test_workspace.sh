#!/usr/bin/env bash
# make_test_workspace.sh —— 兼容入口（旧命令仍可用）
#
# 实际实现已改为 scripts/make_test_workspace.py：
#   Windows 默认没有 bash，也没有 rsync，旧版脚本在上面第一行就 FileNotFoundError。
#   Python 版三平台一致，且不再依赖外部命令。
#
# 用法（两种等价）：
#   bash scripts/make_test_workspace.sh <副本名>
#   python scripts/make_test_workspace.py <副本名>

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "$PYTHON_BIN" "$HERE/make_test_workspace.py" "$@"
