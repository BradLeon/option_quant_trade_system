#!/bin/bash

#=============================================================================
# Ensure TWS is Running with Correct Account
# 确保 TWS 以正确的账户类型运行
#
# 核心逻辑:
#   1. 目标端口已可连接 → 直接成功 (不杀不重启)
#   2. 对方端口在监听 (wrong account) → 停 TWS → 启动正确账户
#   3. TWS 未运行 → 启动
#   4. 启动失败 → 重试 1 次
#
# 用法:
#   ./scripts/ensure_tws.sh paper    # 确保 TWS 以 paper 账户运行
#   ./scripts/ensure_tws.sh live     # 确保 TWS 以 live 账户运行
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 颜色 (cron 日志中无害)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${YELLOW}[ensure_tws]${NC} $*"; }
ok()   { echo -e "${GREEN}[ensure_tws]${NC} $*"; }
fail() { echo -e "${RED}[ensure_tws]${NC} $*"; }

# ─── 配置 ─────────────────────────────────────────────────
PAPER_PORT=7497
LIVE_PORT=7496
STARTUP_WAIT=120      # TWS/IBC 冷启动可能需要 90-120s
CONNECT_TIMEOUT=2     # TCP 连接探测超时

# ─── 参数解析 ─────────────────────────────────────────────
REQUIRED_ACCOUNT="${1:-}"

if [[ -z "$REQUIRED_ACCOUNT" || ! "$REQUIRED_ACCOUNT" =~ ^(paper|live)$ ]]; then
    echo "Usage: $0 <paper|live>"
    exit 1
fi

if [[ "$REQUIRED_ACCOUNT" == "paper" ]]; then
    TARGET_PORT=$PAPER_PORT
    OTHER_PORT=$LIVE_PORT
else
    TARGET_PORT=$LIVE_PORT
    OTHER_PORT=$PAPER_PORT
fi

log "Required: ${REQUIRED_ACCOUNT} (port ${TARGET_PORT})"

# ─── 工具函数 ─────────────────────────────────────────────

# 真正的连接测试 (不只是 LISTEN, 而是 TCP 握手)
port_reachable() {
    local port=$1
    # macOS: 用 nc 做 TCP 探测
    nc -z -w "$CONNECT_TIMEOUT" 127.0.0.1 "$port" >/dev/null 2>&1
}

# 检查 TWS 相关 Java 进程 (IBC 启动或直接启动都能匹配)
is_tws_running() {
    pgrep -f "java.*(IBC|tws|jts)" >/dev/null 2>&1
}

stop_tws() {
    log "Stopping TWS..."

    # 1) 优雅关闭: 匹配 IBC 和 TWS/JTS 进程
    pkill -f "java.*(IBC|tws|jts)" 2>/dev/null || true

    local i=0
    while is_tws_running && [[ $i -lt 30 ]]; do
        sleep 1
        ((i++))
    done

    # 2) 强制杀
    if is_tws_running; then
        log "Force killing TWS..."
        pkill -9 -f "java.*(IBC|tws|jts)" 2>/dev/null || true
        sleep 3
    fi

    if is_tws_running; then
        fail "Failed to stop TWS"
        return 1
    fi

    ok "TWS stopped"
    # 等端口完全释放
    sleep 2
    return 0
}

start_tws() {
    log "Starting TWS (${REQUIRED_ACCOUNT})..."
    "${SCRIPT_DIR}/start_tws.sh" "$REQUIRED_ACCOUNT"

    log "Waiting for port ${TARGET_PORT} (max ${STARTUP_WAIT}s)..."
    local i=0
    while [[ $i -lt $STARTUP_WAIT ]]; do
        if port_reachable "$TARGET_PORT"; then
            ok "TWS ready on port ${TARGET_PORT} (${i}s)"
            return 0
        fi
        sleep 3
        ((i+=3))
        # 每 15s 打一次进度
        if (( i % 15 == 0 )); then
            log "Still waiting... ${i}s / ${STARTUP_WAIT}s"
        fi
    done

    fail "TWS failed to start within ${STARTUP_WAIT}s"
    return 1
}

# ─── 主逻辑 ──────────────────────────────────────────────

# Case 1: 目标端口已经可达 → 直接成功
if port_reachable "$TARGET_PORT"; then
    ok "Port ${TARGET_PORT} reachable — TWS already running with ${REQUIRED_ACCOUNT}"
    exit 0
fi

# Case 2: 对方端口可达 → wrong account, 需要切换
if port_reachable "$OTHER_PORT"; then
    log "Wrong account detected (port ${OTHER_PORT} is up, need ${TARGET_PORT})"
    stop_tws || { fail "Cannot stop TWS, aborting"; exit 1; }
fi

# Case 3: 启动 TWS (含 1 次重试)
MAX_ATTEMPTS=2
for attempt in $(seq 1 $MAX_ATTEMPTS); do
    log "Start attempt ${attempt}/${MAX_ATTEMPTS}"

    if start_tws; then
        exit 0
    fi

    if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
        log "Retrying in 10s..."
        # 确保残留进程清理干净
        stop_tws 2>/dev/null || true
        sleep 10
    fi
done

fail "All ${MAX_ATTEMPTS} attempts failed"
exit 1
