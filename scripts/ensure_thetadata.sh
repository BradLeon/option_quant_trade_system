#!/bin/bash
# ==============================================================================
# ThetaData Terminal 自动启动脚本
#
# 功能：
# 1. 检查 ThetaData Terminal 是否已运行 (端口 25503)
# 2. 如果未运行，自动启动
# 3. 等待服务就绪
#
# 使用方式：
#   ./scripts/ensure_thetadata.sh           # 确保 Terminal 运行
#   ./scripts/ensure_thetadata.sh --check   # 仅检查状态
#   ./scripts/ensure_thetadata.sh --stop    # 停止 Terminal
#
# 配置：
#   THETADATA_HOME: Terminal 安装目录 (默认 ~/ThetaTerminal)
#   THETADATA_PORT: 服务端口 (默认 25503)
#   JAVA_HOME: Java 21+ 路径 (可选)
# ==============================================================================

set -e

# 配置
THETADATA_HOME="${THETADATA_HOME:-$HOME/ThetaTerminal}"
THETADATA_PORT="${THETADATA_PORT:-25503}"
THETADATA_JAR="ThetaTerminalv3.jar"
THETADATA_CREDS="creds.txt"
THETADATA_LOG="$THETADATA_HOME/terminal.log"
THETADATA_PID_FILE="$THETADATA_HOME/.terminal.pid"

# Java 配置 (优先使用 Java 21)
if [ -d "/opt/homebrew/opt/openjdk@21" ]; then
    JAVA_CMD="/opt/homebrew/opt/openjdk@21/bin/java"
elif [ -n "$JAVA_HOME" ]; then
    JAVA_CMD="$JAVA_HOME/bin/java"
else
    JAVA_CMD="java"
fi

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查端口是否被占用
check_port() {
    nc -z localhost "$THETADATA_PORT" 2>/dev/null
}

# 检查 Terminal 是否响应
check_health() {
    curl -s --max-time 5 "http://127.0.0.1:$THETADATA_PORT/v3/stock/list/symbols?format=json" >/dev/null 2>&1
}

# 获取运行中的 Terminal PID
get_terminal_pid() {
    lsof -ti:"$THETADATA_PORT" 2>/dev/null | head -1
}

# 检查 Java 版本
check_java() {
    if ! command -v "$JAVA_CMD" &>/dev/null; then
        log_error "Java not found. Please install Java 21+:"
        echo "  brew install openjdk@21"
        return 1
    fi

    local java_version
    java_version=$("$JAVA_CMD" -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)

    if [ "$java_version" -lt 21 ] 2>/dev/null; then
        log_error "Java 21+ required, found version $java_version"
        echo "  Install: brew install openjdk@21"
        return 1
    fi

    return 0
}

# 检查必要文件
check_files() {
    if [ ! -f "$THETADATA_HOME/$THETADATA_JAR" ]; then
        log_error "ThetaData Terminal JAR not found: $THETADATA_HOME/$THETADATA_JAR"
        echo "  Download from: https://www.thetadata.net/terminal"
        return 1
    fi

    if [ ! -f "$THETADATA_HOME/$THETADATA_CREDS" ]; then
        log_error "Credentials file not found: $THETADATA_HOME/$THETADATA_CREDS"
        echo "  Create file with format:"
        echo "    your_email@example.com"
        echo "    your_password"
        return 1
    fi

    return 0
}

# 启动 Terminal
start_terminal() {
    log_info "Starting ThetaData Terminal..."

    cd "$THETADATA_HOME" || exit 1

    # 启动进程 (后台运行)
    nohup "$JAVA_CMD" -Xms2G -Xmx4G \
        -jar "$THETADATA_JAR" \
        --creds-file="$THETADATA_CREDS" \
        > "$THETADATA_LOG" 2>&1 &

    local pid=$!
    echo "$pid" > "$THETADATA_PID_FILE"

    log_info "Terminal started with PID $pid"
    log_info "Log file: $THETADATA_LOG"

    # 等待服务就绪
    log_info "Waiting for service to be ready..."
    local max_wait=60
    local waited=0

    while [ $waited -lt $max_wait ]; do
        if check_health; then
            log_info "ThetaData Terminal is ready on port $THETADATA_PORT"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
    echo

    log_warn "Terminal started but health check timed out"
    log_warn "Check log: tail -f $THETADATA_LOG"
    return 1
}

# 停止 Terminal
stop_terminal() {
    local pid
    pid=$(get_terminal_pid)

    if [ -n "$pid" ]; then
        log_info "Stopping ThetaData Terminal (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        sleep 2

        # 强制终止如果还在运行
        if check_port; then
            log_warn "Force killing..."
            kill -9 "$pid" 2>/dev/null || true
        fi

        rm -f "$THETADATA_PID_FILE"
        log_info "Terminal stopped"
    else
        log_info "No running Terminal found"
    fi
}

# 显示状态
show_status() {
    echo "ThetaData Terminal Status"
    echo "========================="
    echo "Home:     $THETADATA_HOME"
    echo "Port:     $THETADATA_PORT"
    echo "Java:     $JAVA_CMD"

    if check_port; then
        local pid
        pid=$(get_terminal_pid)
        echo -e "Status:   ${GREEN}Running${NC} (PID: $pid)"

        if check_health; then
            echo -e "Health:   ${GREEN}Healthy${NC}"
        else
            echo -e "Health:   ${YELLOW}Not responding${NC}"
        fi
    else
        echo -e "Status:   ${RED}Not running${NC}"
    fi
}

# 确保 Terminal 运行
ensure_running() {
    if check_port; then
        if check_health; then
            log_info "ThetaData Terminal is already running and healthy"
            return 0
        else
            log_warn "Terminal is running but not responding, restarting..."
            stop_terminal
        fi
    fi

    # 检查依赖
    check_java || exit 1
    check_files || exit 1

    # 启动
    start_terminal
}

# 主程序
main() {
    case "${1:-}" in
        --check|--status)
            show_status
            ;;
        --stop)
            stop_terminal
            ;;
        --start)
            check_java || exit 1
            check_files || exit 1
            start_terminal
            ;;
        --restart)
            stop_terminal
            sleep 2
            check_java || exit 1
            check_files || exit 1
            start_terminal
            ;;
        --help|-h)
            echo "Usage: $0 [--check|--start|--stop|--restart|--help]"
            echo ""
            echo "Options:"
            echo "  (none)     Ensure Terminal is running (start if needed)"
            echo "  --check    Show status only"
            echo "  --start    Force start Terminal"
            echo "  --stop     Stop Terminal"
            echo "  --restart  Restart Terminal"
            echo "  --help     Show this help"
            echo ""
            echo "Environment variables:"
            echo "  THETADATA_HOME  Terminal directory (default: ~/ThetaTerminal)"
            echo "  THETADATA_PORT  Service port (default: 25503)"
            ;;
        *)
            ensure_running
            ;;
    esac
}

main "$@"
