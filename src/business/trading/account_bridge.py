"""
Account Bridge - 账户数据转换

将 AccountAggregator 的 ConsolidatedPortfolio 转换为 Trading 模块需要的 AccountState。
"""

from datetime import datetime

from src.data.models.account import AccountType, AssetType, ConsolidatedPortfolio
from src.business.trading.models.decision import AccountState


def portfolio_to_account_state(
    portfolio: ConsolidatedPortfolio,
    broker: str = "ibkr",
    account_type: str = "paper",
) -> AccountState:
    """将 ConsolidatedPortfolio 转换为 AccountState

    映射关系:
    - total_equity = portfolio.total_value_usd (NLV)
    - cash_balance = sum of cash_balances in USD
    - used_margin = from AccountSummary.margin_used
    - available_margin = from AccountSummary.margin_available
    - margin_utilization = used_margin / total_equity
    - cash_ratio = cash_balance / total_equity
    - gross_leverage = total_notional / total_equity
    - exposure_by_underlying = 聚合各标的的 market_value

    Args:
        portfolio: 合并后的组合数据
        broker: 券商名称
        account_type: 账户类型 (必须是 "paper")

    Returns:
        AccountState 用于决策引擎
    """
    # 1. 基础数据
    total_equity = portfolio.total_value_usd

    # 2. 计算现金余额 (转换为 USD)
    cash_balance = 0.0
    for cash in portfolio.cash_balances:
        if cash.currency == "USD":
            cash_balance += cash.balance
        else:
            # 使用汇率转换
            rate = portfolio.exchange_rates.get(cash.currency, 1.0)
            cash_balance += cash.balance * rate

    # 3. 获取保证金数据 (从指定 broker 的 summary)
    used_margin = 0.0
    available_margin = 0.0
    buying_power = 0.0
    if broker in portfolio.by_broker:
        summary = portfolio.by_broker[broker]
        used_margin = summary.margin_used or 0.0
        available_margin = summary.margin_available or 0.0
        buying_power = summary.buying_power or 0.0

    # 如果 available_margin 未提供，进行估算
    # 对于 Portfolio Margin 账户: available = NLV - used_margin
    # 对于 Reg T 账户: available ≈ min(cash, buying_power, NLV * 0.5)
    if available_margin == 0 and total_equity > 0:
        if buying_power > 0:
            # 使用 buying_power 作为估算
            available_margin = buying_power
        else:
            # 保守估算: min(现金, NLV - 已用保证金)
            available_margin = min(cash_balance, total_equity - used_margin)

    # 4. 计算风控指标
    margin_utilization = used_margin / total_equity if total_equity > 0 else 0.0
    cash_ratio = cash_balance / total_equity if total_equity > 0 else 0.0

    # 5. 计算杠杆 (Total Notional / NLV)
    #    - 期权: strike * multiplier * |quantity|
    #    - 股票: market_value
    total_notional = 0.0
    for pos in portfolio.positions:
        if pos.asset_type == AssetType.OPTION:
            if pos.strike and pos.contract_multiplier:
                notional = pos.strike * pos.contract_multiplier * abs(pos.quantity)
                # 转换为 USD
                if pos.currency != "USD":
                    rate = portfolio.exchange_rates.get(pos.currency, 1.0)
                    notional *= rate
                total_notional += notional
        else:
            # 股票: 使用 market_value
            market_val = abs(pos.market_value)
            if pos.currency != "USD":
                rate = portfolio.exchange_rates.get(pos.currency, 1.0)
                market_val *= rate
            total_notional += market_val

    gross_leverage = total_notional / total_equity if total_equity > 0 else 0.0

    # 6. 统计持仓数量
    option_count = 0
    stock_count = 0
    for pos in portfolio.positions:
        if pos.asset_type == AssetType.OPTION:
            option_count += 1
        elif pos.asset_type == AssetType.STOCK:
            stock_count += 1

    # 7. 计算标的暴露
    exposure_by_underlying: dict[str, float] = {}
    for pos in portfolio.positions:
        underlying = pos.underlying or pos.symbol
        # 使用 market_value 作为暴露值
        exposure = abs(pos.market_value)
        if pos.currency != "USD":
            rate = portfolio.exchange_rates.get(pos.currency, 1.0)
            exposure *= rate

        if underlying in exposure_by_underlying:
            exposure_by_underlying[underlying] += exposure
        else:
            exposure_by_underlying[underlying] = exposure

    return AccountState(
        broker=broker,
        account_type=account_type,
        total_equity=total_equity,
        cash_balance=cash_balance,
        available_margin=available_margin,
        used_margin=used_margin,
        margin_utilization=margin_utilization,
        cash_ratio=cash_ratio,
        gross_leverage=gross_leverage,
        total_position_count=len(portfolio.positions),
        option_position_count=option_count,
        stock_position_count=stock_count,
        exposure_by_underlying=exposure_by_underlying,
        timestamp=portfolio.timestamp or datetime.now(),
    )
