#!/bin/bash
# ==============================================================================
# Crontab 环境包装脚本
#
# 解决 crontab 环境变量不完整的问题：
# 1. 加载用户 shell 环境
# 2. 设置代理
# 3. 运行命令
# ==============================================================================

# 项目目录
PROJECT_DIR="/Users/liuchao/Code/Quant/option_quant_trade_system"

# 加载用户环境（包含 PATH、代理等）
if [ -f "$HOME/.zshrc" ]; then
    source "$HOME/.zshrc" 2>/dev/null || true
fi

# 确保代理设置（如果 .zshrc 没有设置）
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:33210}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:33210}"
export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:33210}"

# 确保 uv 在 PATH 中
export PATH="$HOME/.local/bin:$PATH"

# 切换到项目目录
cd "$PROJECT_DIR" || exit 1

# 可选：检查 IBKR Gateway 是否可用（端口 4001）
check_ibkr() {
    if ! nc -z localhost 4001 2>/dev/null; then
        echo "[$(date)] WARNING: IBKR Gateway not available on port 4001" >&2
        # 可以选择退出或继续
        # exit 1
    fi
}

# 如果命令包含 dashboard 或需要 IBKR，则检查
case "$*" in
    *dashboard*|*monitor*)
        check_ibkr
        ;;
esac

# 执行传入的命令
exec "$@"
