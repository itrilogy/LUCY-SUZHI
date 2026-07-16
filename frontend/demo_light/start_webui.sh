#!/usr/bin/env bash
# STORM WebUI 启动脚本
# 使用前确保已通过 cli/config_manager.py 配置了 LLM 和检索引擎
# 或 ~/.storm/config.toml 已正确填写

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="/tmp/storm_venv/bin/python3"

echo "🚀 启动 STORM WebUI..."
echo "   配置: ~/.storm/config.toml"
echo "   端口: http://localhost:8501"
echo ""

# 优先使用虚拟环境的 streamlit，否则回退系统
if [ -f "$VENV_PYTHON" ]; then
    cd "$SCRIPT_DIR"
    exec "$VENV_PYTHON" -m streamlit run storm.py -- "$@"
else
    cd "$SCRIPT_DIR"
    exec python3 -m streamlit run storm.py -- "$@"
fi
