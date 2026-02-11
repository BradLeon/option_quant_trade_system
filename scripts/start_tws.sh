#!/bin/bash

#=============================================================================
# TWS Startup Script using IBC
# 用于期权量化交易系统的 TWS 自动化启动脚本
#
# 用法:
#   ./scripts/start_tws.sh          # 默认启动 paper 账户
#   ./scripts/start_tws.sh paper    # 启动 paper 账户
#   ./scripts/start_tws.sh live     # 启动 live 账户
#=============================================================================

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# TWS 主版本号 (从 ~/Applications/Trader Workstation 获取)
TWS_MAJOR_VRSN=10.38

# 解析账户类型参数
ACCOUNT_TYPE="${1:-paper}"

# 处理 -inline 参数 (内部使用)
if [[ "$1" == "-inline" ]]; then
    ACCOUNT_TYPE="${2:-paper}"
fi

# 根据账户类型设置配置
case "$ACCOUNT_TYPE" in
    paper)
        IBC_INI=~/IBC/config.ini
        TRADING_MODE=paper
        ;;
    live)
        IBC_INI=~/IBC/config-live.ini
        TRADING_MODE=live
        ;;
    *)
        echo "Usage: $0 [paper|live]"
        echo "  paper - Start with paper trading account (default)"
        echo "  live  - Start with live trading account"
        exit 1
        ;;
esac

echo "Starting TWS with ${ACCOUNT_TYPE} account..."
echo "Config: ${IBC_INI}"

# 2FA 超时后的操作: restart 或 exit
TWOFA_TIMEOUT_ACTION=restart

# IBC 安装路径 (指向 resources 目录)
IBC_PATH=~/IBC/resources

# TWS 安装路径 (macOS 上通常是 ~/Applications 或 /Applications)
TWS_PATH=~/Applications

# TWS 设置存储路径 (留空则使用默认)
TWS_SETTINGS_PATH=

# 日志路径
LOG_PATH=~/IBC/logs

# 用户凭据 (在 config.ini 中设置)
TWSUSERID=
TWSPASSWORD=

# Java 路径 (通常不需要设置)
JAVA_PATH=

#==============================================================================
#              以下内容请勿修改
#==============================================================================

# 确保脚本有执行权限
chmod +x "${IBC_PATH}/scripts/displaybannerandlaunch.sh" 2>/dev/null
chmod +x "${IBC_PATH}/scripts/ibcstart.sh" 2>/dev/null

if [[ -x "${IBC_PATH}/scripts/displaybannerandlaunch.sh" ]]; then
	:
elif [[ -x "${IBC_PATH}/scripts/ibcstart.sh" ]]; then
	:
else
	>&2 echo -e "Error: no execute permission for scripts in ${IBC_PATH}/scripts"
	>&2 exit 1
fi

# 检查是否已有 TWS 实例运行 (任何配置)
if [[ -n $(/usr/bin/pgrep -f "java.*IBC") ]]; then
	>&2 echo -e "Error: TWS/IBC process is already running"
	>&2 echo -e "Use ${SCRIPT_DIR}/ensure_tws.sh ${ACCOUNT_TYPE} to switch accounts"
	>&2 exit 1
fi

APP=TWS

export TWS_MAJOR_VRSN
export IBC_INI
export TRADING_MODE
export TWOFA_TIMEOUT_ACTION
export IBC_PATH
export TWS_PATH
export TWS_SETTINGS_PATH
export LOG_PATH
export TWSUSERID
export TWSPASSWORD
export JAVA_PATH
export APP

# 创建日志目录
mkdir -p "${LOG_PATH}"

if [[ "$1" == "-inline" ]]; then
    exec "${IBC_PATH}/scripts/displaybannerandlaunch.sh"
else
    # 在新终端窗口中运行，传递账户类型
    osascript -e "tell app \"Terminal\"
        do script \"${SCRIPT_DIR}/start_tws.sh -inline ${ACCOUNT_TYPE}\"
    end tell"
fi
