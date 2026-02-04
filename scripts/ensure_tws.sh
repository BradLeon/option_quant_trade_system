#!/bin/bash

#=============================================================================
# Ensure TWS is Running with Correct Account
# 确保 TWS 以正确的账户类型运行
#
# 用法:
#   ./scripts/ensure_tws.sh paper    # 确保 TWS 以 paper 账户运行
#   ./scripts/ensure_tws.sh live     # 确保 TWS 以 live 账户运行
#
# 在定时任务中使用:
#   ./scripts/ensure_tws.sh paper && uv run optrade trade monitor -a paper --execute
#=============================================================================

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置
PAPER_CONFIG=~/IBC/config.ini
LIVE_CONFIG=~/IBC/config-live.ini
PAPER_PORT=7497
LIVE_PORT=7496
STARTUP_WAIT=60  # 等待 TWS 启动的最长时间 (秒)

# 检查参数
REQUIRED_ACCOUNT="${1:-}"

if [[ -z "$REQUIRED_ACCOUNT" ]]; then
    echo "Usage: $0 <paper|live>"
    echo ""
    echo "Examples:"
    echo "  $0 paper    # Ensure TWS runs with paper account"
    echo "  $0 live     # Ensure TWS runs with live account"
    echo ""
    echo "In cron jobs:"
    echo "  $0 paper && uv run optrade trade monitor -a paper --execute"
    exit 1
fi

if [[ "$REQUIRED_ACCOUNT" != "paper" && "$REQUIRED_ACCOUNT" != "live" ]]; then
    echo -e "${RED}Error: Invalid account type '$REQUIRED_ACCOUNT'. Use 'paper' or 'live'.${NC}"
    exit 1
fi

# 设置目标端口和配置
if [[ "$REQUIRED_ACCOUNT" == "paper" ]]; then
    TARGET_PORT=$PAPER_PORT
    TARGET_CONFIG=$PAPER_CONFIG
else
    TARGET_PORT=$LIVE_PORT
    TARGET_CONFIG=$LIVE_CONFIG
fi

echo -e "${YELLOW}[ensure_tws]${NC} Required account: ${REQUIRED_ACCOUNT} (port ${TARGET_PORT})"

# 检测当前运行的 TWS 账户类型
detect_current_account() {
    # 方法1: 通过检查哪个端口在监听
    if lsof -i :$PAPER_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "paper"
        return 0
    elif lsof -i :$LIVE_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "live"
        return 0
    fi

    # 方法2: 检查进程参数中的配置文件
    local ibc_pid=$(pgrep -f "java.*IBC" 2>/dev/null | head -1)
    if [[ -n "$ibc_pid" ]]; then
        local cmdline=$(ps -p "$ibc_pid" -o args= 2>/dev/null)
        if echo "$cmdline" | grep -q "config-live.ini"; then
            echo "live"
            return 0
        elif echo "$cmdline" | grep -q "config.ini"; then
            echo "paper"
            return 0
        fi
    fi

    echo "unknown"
    return 1
}

# 检查 TWS 是否正在运行
is_tws_running() {
    pgrep -f "java.*IBC" >/dev/null 2>&1
}

# 停止当前 TWS
stop_tws() {
    echo -e "${YELLOW}[ensure_tws]${NC} Stopping current TWS..."

    # 先尝试优雅关闭
    pkill -f "java.*IBC" 2>/dev/null || true

    # 等待进程退出
    local wait_count=0
    while is_tws_running && [[ $wait_count -lt 30 ]]; do
        sleep 1
        ((wait_count++))
    done

    # 如果还在运行，强制杀死
    if is_tws_running; then
        echo -e "${YELLOW}[ensure_tws]${NC} Force killing TWS..."
        pkill -9 -f "java.*IBC" 2>/dev/null || true
        sleep 2
    fi

    if is_tws_running; then
        echo -e "${RED}[ensure_tws]${NC} Failed to stop TWS"
        return 1
    fi

    echo -e "${GREEN}[ensure_tws]${NC} TWS stopped"
    return 0
}

# 启动 TWS
start_tws() {
    local account_type=$1
    echo -e "${YELLOW}[ensure_tws]${NC} Starting TWS with ${account_type} account..."

    # 使用 start_tws.sh 启动 (后台运行)
    "${SCRIPT_DIR}/start_tws.sh" "$account_type"

    # 等待 TWS 启动并监听端口
    echo -e "${YELLOW}[ensure_tws]${NC} Waiting for TWS to start (max ${STARTUP_WAIT}s)..."
    local wait_count=0
    while [[ $wait_count -lt $STARTUP_WAIT ]]; do
        if lsof -i :$TARGET_PORT -sTCP:LISTEN >/dev/null 2>&1; then
            echo -e "${GREEN}[ensure_tws]${NC} TWS is now listening on port ${TARGET_PORT}"
            return 0
        fi
        sleep 2
        ((wait_count+=2))
        echo -ne "\r${YELLOW}[ensure_tws]${NC} Waiting... ${wait_count}s / ${STARTUP_WAIT}s"
    done
    echo ""

    echo -e "${RED}[ensure_tws]${NC} TWS failed to start within ${STARTUP_WAIT} seconds"
    return 1
}

# 主逻辑
main() {
    if is_tws_running; then
        CURRENT_ACCOUNT=$(detect_current_account)
        echo -e "${YELLOW}[ensure_tws]${NC} TWS is running with account: ${CURRENT_ACCOUNT}"

        if [[ "$CURRENT_ACCOUNT" == "$REQUIRED_ACCOUNT" ]]; then
            echo -e "${GREEN}[ensure_tws]${NC} TWS is already running with correct account (${REQUIRED_ACCOUNT})"
            exit 0
        else
            echo -e "${YELLOW}[ensure_tws]${NC} Account mismatch: need ${REQUIRED_ACCOUNT}, have ${CURRENT_ACCOUNT}"
            stop_tws
            start_tws "$REQUIRED_ACCOUNT"
        fi
    else
        echo -e "${YELLOW}[ensure_tws]${NC} TWS is not running"
        start_tws "$REQUIRED_ACCOUNT"
    fi
}

main
