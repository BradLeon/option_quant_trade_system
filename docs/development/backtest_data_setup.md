# Backtest Data 环境配置指南

本文档说明回测数据模块所需的依赖配置。

> **完整文档**: 详细的用户手册请参考 [src/backtest/README.md](../../src/backtest/README.md)

## 依赖分类

### Python 依赖 (通过 uv 管理)

已在 `pyproject.toml` 中声明，运行 `uv sync` 自动安装：

```toml
# pyproject.toml
dependencies = [
    "ib_async>=2.0.0",      # IBKR API 客户端
    "yfinance>=0.2.28",     # Yahoo Finance 宏观数据
    # ...
]
```

### 外部服务依赖 (需单独安装)

| 服务 | 用途 | 安装方式 |
|------|------|---------|
| ThetaData Terminal | 期权历史数据 | Java 应用，需 Java 21+ |
| IBKR TWS/Gateway | 基本面数据 | IBKR 官方客户端 |

### 系统依赖

```bash
# Java 21+ (ThetaData Terminal 需要)
brew install openjdk@21
```

## 数据源概览

| 数据源 | 用途 | 依赖 |
|--------|------|------|
| ThetaData | 期权历史数据 + Greeks | ThetaData Terminal + 订阅 |
| yfinance | 宏观指数 (VIX/TNX) | Python 包 (已安装) |
| IBKR | 基本面数据 (EPS/Revenue) | TWS 或 IB Gateway |

---

## 1. ThetaData Terminal 配置

### 前置条件

- **Java 21+** (推荐)
- **ThetaData 账号** (Free tier 可用，有 rate limit)

### 安装 Java 21 (macOS)

```bash
brew install openjdk@21

# 设置环境变量
echo 'export PATH="/opt/homebrew/opt/openjdk@21/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 验证
java -version
```

### ThetaData Terminal 文件位置

```
/Users/liuchao/ThetaTerminal/
├── ThetaTerminalv3.jar    # 主程序
├── creds.txt              # 账号密码
└── start.sh               # 启动脚本
```

### 启动 ThetaData Terminal

```bash
# 方式 1: 自动启动脚本 (推荐)
./scripts/ensure_thetadata.sh

# 方式 2: 检查状态
./scripts/ensure_thetadata.sh --check

# 方式 3: 手动启动
cd /Users/liuchao/ThetaTerminal
/opt/homebrew/opt/openjdk@21/bin/java -Xms2G -Xmx4G -jar ThetaTerminalv3.jar --creds-file=creds.txt
```

### 验证运行状态

```bash
curl http://127.0.0.1:25503/v3/status
```

### 账号信息

- Email: `bradleon91@gmail.com`
- 配置文件: `/Users/liuchao/ThetaTerminal/creds.txt`

---

## 2. IBKR TWS / IB Gateway 配置

### 前置条件

- IBKR 账户 (Paper 或 Live)
- TWS 或 IB Gateway 安装并运行

### 端口配置

| 账户类型 | 默认端口 | 环境变量 |
|---------|---------|---------|
| Paper | 7497 | `IBKR_PORT=7497` |
| Live | 7496 | `IBKR_PORT=7496` |

### 启动 TWS/Gateway

1. 打开 TWS 或 IB Gateway
2. 登录账户
3. 确认 API 设置:
   - `Edit > Global Configuration > API > Settings`
   - 勾选 `Enable ActiveX and Socket Clients`
   - 确认端口号

### 验证连接

```bash
# 设置端口
export IBKR_PORT=7497

# 运行测试
python tests/verification/verify_backtest_data.py --source ibkr
```

---

## 3. yfinance 配置

### 安装

```bash
uv pip install yfinance
```

已在 `pyproject.toml` 中声明，无需额外配置。

### 注意事项

- 可能受网络代理影响
- Yahoo Finance 有 rate limit，建议使用 `MacroDownloader` 批量下载后查询

---

## 4. 验证测试脚本

### 运行所有数据源测试

```bash
# 测试所有数据源
python tests/verification/verify_backtest_data.py

# 测试特定数据源
python tests/verification/verify_backtest_data.py --source thetadata
python tests/verification/verify_backtest_data.py --source yfinance
python tests/verification/verify_backtest_data.py --source ibkr

# 指定测试天数
python tests/verification/verify_backtest_data.py --days 30
```

### 预期输出

```
============================================================
Backtest Data Verification Report
============================================================
Date: 2025-02-02
Test Period: 2025-01-03 ~ 2025-02-02
Symbols: GOOG, SPY

1. ThetaData (Options + Stocks)
   ✅ Connection: Connected to 127.0.0.1:25503
   ✅ GOOG Stock EOD: 22 days
   ✅ GOOG Options: 1,234 contracts
   ...

2. yfinance (Macro Data)
   ✅ ^VIX: 22 days
   ✅ ^TNX: 22 days
   ...

3. IBKR (Fundamental Data)
   ✅ GOOG: EPS=28, Revenue=28
   ...

Summary: 15/16 tests passed
```

---

## 5. 快速启动检查清单

运行回测前确认：

```bash
# 一键启动 ThetaData Terminal
./scripts/ensure_thetadata.sh

# 验证所有数据源
uv run python tests/verification/verify_backtest_data.py
```

- [ ] ThetaData Terminal 运行中 (`./scripts/ensure_thetadata.sh --check`)
- [ ] IBKR TWS/Gateway 运行中 (端口 7497 或 7496)
- [ ] 网络连接正常 (yfinance 需要)

---

## 6. 故障排查

### ThetaData 502 Bad Gateway

```bash
# 原因: Terminal 未运行
# 解决: 启动 Terminal
./scripts/ensure_thetadata.sh
```

### ThetaData 403 Forbidden (Greeks/IV)

```bash
# 原因: Greeks/IV 需要 STANDARD 订阅 ($80/月)
# 解决: 使用 GreeksCalculator 自行计算 (FREE)
```

```python
from src.backtest.data import GreeksCalculator, ThetaDataClient

client = ThetaDataClient()
calc = GreeksCalculator()

options = client.get_option_eod("GOOG", start, end)
stocks = client.get_stock_eod("GOOG", start, end)
stock_prices = {d.date: d.close for d in stocks}

# 自行计算 IV + Greeks (无需订阅)
enriched = calc.enrich_options_batch(options, stock_prices, rate=0.045)
```

### IBKR 连接失败

```bash
# 检查端口
lsof -i :7497

# 确认 TWS API 设置已启用
```

### yfinance 超时

```bash
# 可能是代理问题，尝试:
unset http_proxy https_proxy
```
