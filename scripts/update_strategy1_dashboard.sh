#!/usr/bin/env bash
# 一键：强制刷新 yfinance 最新日线，并重写策略一看板 HTML（桌面 + Downloads）
# 用法：
#   ./scripts/update_strategy1_dashboard.sh
#   ./scripts/update_strategy1_dashboard.sh --no-refresh   # 仅重绘，不拉网
#
# 实时模式（浏览器刷新即更新）：双击桌面「指定红看板-实时.command」
#   或: .venv/bin/python scripts/serve_zhidhong_dashboard.py --open
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
exec "$PY" scripts/strategy1.py dashboard "$@"
