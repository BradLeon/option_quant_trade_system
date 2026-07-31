#!/bin/bash

#=============================================================================
# Ensure TWS is Running with Correct Account
# 确保 TWS 以正确的账户类型运行
#
# 核心逻辑 (保守策略 — 不轻易杀 TWS):
#   1. 目标端口可达 + API 握手成功 → 成功
#   2. 目标端口可达但 API 未就绪 → 等待 API 初始化
#   3. 对方端口在监听 (wrong account) → 停 TWS → 启动正确账户
#   4. TWS 未运行 → 启动 (含重试)
#
# 用法:
#   ./scripts/ensure_tws.sh paper    # 确保 TWS 以 paper 账户运行
#   ./scripts/ensure_tws.sh live     # 确保 TWS 以 live 账户运行
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色
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
STARTUP_WAIT=150      # TWS/IBC 冷启动可能需要 90-120s + API 初始化
API_READY_WAIT=60     # TCP 端口可达后，等 API 握手就绪的额外时间
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

# TCP 端口探测
port_reachable() {
    local port=$1
    nc -z -w "$CONNECT_TIMEOUT" 127.0.0.1 "$port" >/dev/null 2>&1
}

# IBKR API 握手验证 (非破坏性 — 只测连接，不杀进程)
# 使用 ib_async 尝试连接，成功后立即断开
api_ready() {
    local port=$1
    cd "$PROJECT_DIR"
    uv run python -c "
import asyncio, sys
async def check():
    try:
        from ib_async import IB
        ib = IB()
        await asyncio.wait_for(
            ib.connectAsync('127.0.0.1', $port, clientId=99, readonly=True),
            timeout=8,
        )
        ib.disconnect()
        sys.exit(0)
    except Exception:
        sys.exit(1)
asyncio.run(check())
" 2>/dev/null
}

# 检查 TWS 相关进程 (IBC 启动 = java, 手动启动 = JavaApplicationStub)
is_tws_running() {
    pgrep -f "java.*(IBC|tws|jts)" >/dev/null 2>&1 ||
    pgrep -f "JavaApplicationStub" >/dev/null 2>&1
}

# 获取 TWS 进程 PID (用于 stop)
get_tws_pids() {
    { pgrep -f "java.*(IBC|tws|jts)" 2>/dev/null || true; }
    { pgrep -f "JavaApplicationStub" 2>/dev/null || true; }
}

stop_tws() {
    log "Stopping TWS..."

    # 1) 优雅关闭: 同时匹配 IBC 和手动启动的 TWS
    pkill -f "java.*(IBC|tws|jts)" 2>/dev/null || true
    pkill -f "JavaApplicationStub" 2>/dev/null || true

    local i=0
    while is_tws_running && [[ $i -lt 30 ]]; do
        sleep 1
        ((i++))
    done

    # 2) 强制杀
    if is_tws_running; then
        log "Force killing TWS..."
        pkill -9 -f "java.*(IBC|tws|jts)" 2>/dev/null || true
        pkill -9 -f "JavaApplicationStub" 2>/dev/null || true
        sleep 3
    fi

    if is_tws_running; then
        fail "Failed to stop TWS"
        return 1
    fi

    ok "TWS stopped"
    sleep 2
    return 0
}

# 等待 API 完全就绪 (TCP 端口已可达后调用)
wait_for_api() {
    log "Verifying IBKR API readiness on port ${TARGET_PORT}..."
    local i=0
    while [[ $i -lt $API_READY_WAIT ]]; do
        if api_ready "$TARGET_PORT"; then
            ok "IBKR API ready on port ${TARGET_PORT} (${i}s)"
            return 0
        fi
        sleep 5
        ((i+=5))
        if (( i % 15 == 0 )); then
            log "API not ready yet... ${i}s / ${API_READY_WAIT}s"
        fi
    done

    # API 未就绪但端口可达 — 警告但不失败 (可能是 clientId 冲突等)
    log "WARNING: API handshake failed after ${API_READY_WAIT}s, but port is open. Proceeding anyway."
    return 0
}

start_tws() {
    log "Starting TWS (${REQUIRED_ACCOUNT})..."
    "${SCRIPT_DIR}/start_tws.sh" "$REQUIRED_ACCOUNT"

    log "Waiting for port ${TARGET_PORT} (max ${STARTUP_WAIT}s)..."
    local i=0
    while [[ $i -lt $STARTUP_WAIT ]]; do
        if port_reachable "$TARGET_PORT"; then
            ok "TWS port ${TARGET_PORT} ready (${i}s)"
            wait_for_api
            return $?
        fi
        sleep 3
        ((i+=3))
        if (( i % 15 == 0 )); then
            log "Still waiting... ${i}s / ${STARTUP_WAIT}s"
        fi
    done

    fail "TWS failed to start within ${STARTUP_WAIT}s"
    return 1
}

# ─── 主逻辑 ──────────────────────────────────────────────

# Case 1: 目标端口可达 → 验证 API 就绪后成功
if port_reachable "$TARGET_PORT"; then
    ok "Port ${TARGET_PORT} reachable"
    if api_ready "$TARGET_PORT"; then
        ok "IBKR API ready — TWS running with ${REQUIRED_ACCOUNT}"
        exit 0
    fi
    # 端口可达但 API 未就绪 — 等待 (TWS 可能刚启动)
    log "Port reachable but API not ready, waiting..."
    wait_for_api
    exit 0
fi

# Case 2: 对方端口可达 → wrong account, 需要切换
if port_reachable "$OTHER_PORT"; then
    log "Wrong account detected (port ${OTHER_PORT} is up, need ${TARGET_PORT})"
    stop_tws || { fail "Cannot stop TWS, aborting"; exit 1; }
fi

# Case 3: TWS 未运行 → 启动 (含 1 次重试)
MAX_ATTEMPTS=2
for attempt in $(seq 1 $MAX_ATTEMPTS); do
    log "Start attempt ${attempt}/${MAX_ATTEMPTS}"

    if start_tws; then
        exit 0
    fi

    if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
        log "Retrying in 10s..."
        stop_tws 2>/dev/null || true
        sleep 10
    fi
done

fail "All ${MAX_ATTEMPTS} attempts failed"
exit 1
