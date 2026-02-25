"""测试期权行权后的正股交易功能"""

from datetime import date

from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.trade_simulator import TradeSimulator, OrderSide
from src.data.models.account import AssetType
from src.data.models.option import OptionType


def test_short_put_assignment_creates_stock_position():
    """测试 Short Put ITM 到期，创建股票多头持仓"""
    # 1. 初始化账户
    account = AccountSimulator(initial_capital=100_000)

    # 2. 模拟开仓 Short Put（使用 SimulatedPosition）
    option_position_id = "AAPL-PUT-001"
    option_position = SimulatedPosition(
        position_id=option_position_id,
        symbol="AAPL 20240315 150P",
        asset_type=AssetType.OPTION,
        underlying="AAPL",
        option_type=OptionType.PUT,
        strike=150.0,
        expiration=date(2024, 3, 15),
        quantity=-1,
        entry_price=2.0,
        entry_date=date(2024, 3, 1),
        lot_size=100,
        current_price=2.0,
        market_value=-200.0,  # -1 * $2.00 * 100
        margin_required=100.0,
    )
    account.add_position(
        position=option_position,
        cash_change=200.0,  # 收取权利金（正数）
    )

    # 3. 模拟行权（按 $100 买入 100 股）
    account.add_stock_position(
        symbol="AAPL",
        quantity=100,
        entry_price=100.0,
        trade_date=date(2024, 3, 15),
        cash_change=-10000.0,  # 扣除 $10,000
    )

    # 验证结果
    stock_pos = account.get_stock_position("AAPL")
    assert stock_pos is not None
    assert stock_pos.quantity == 100
    assert stock_pos.entry_price == 100.0
    assert stock_pos.market_value == 10000.0
    assert stock_pos.margin_required == 0.0  # 股票不占用保证金

    # 验证账户状态（使用 get_account_state）
    state = account.get_account_state()
    assert state.stock_position_count == 1  # 正好有 1 个股票持仓
    assert state.cash_balance == 90200.0  # $100,000 + $200 - $10,000
    assert state.total_equity == 100000.0  # NLV = $90,200 + $10,000 (stock) - $200 (option)
    assert state.used_margin == 100.0  # 期权保证金占用

    print("✅ Short Put assignment test passed")


def test_short_call_assignment_with_sufficient_stock():
    """测试 Short Call ITM 到期，有足够股票，直接卖出"""
    # 1. 初始化账户
    account = AccountSimulator(initial_capital=100_000)

    # 2. 预先持有 100 股 @ $90
    account.add_stock_position(
        symbol="AAPL",
        quantity=100,
        entry_price=90.0,
        trade_date=date(2024, 3, 1),
        cash_change=-9000.0,
    )

    assert account.get_stock_quantity("AAPL") == 100

    # 3. 模拟 Short Call 到期行权
    # - 卖出 1 张合约，收取权利金 $300
    option_position = SimulatedPosition(
        position_id="AAPL-CALL-001",
        symbol="AAPL 20240315 100C",
        asset_type=AssetType.OPTION,
        underlying="AAPL",
        option_type=OptionType.CALL,
        strike=100.0,
        expiration=date(2024, 3, 15),
        quantity=-1,
        entry_price=3.0,
        entry_date=date(2024, 3, 1),
        lot_size=100,
        current_price=3.0,
        market_value=-300.0,  # -1 * $3.00 * 100
        margin_required=100.0,
    )
    account.add_position(
        position=option_position,
        cash_change=300.0,  # 收取权利金（正数）
    )

    # 4. 卖出股票
    account.update_stock_position(
        position_id="AAPL-STOCK",
        quantity_change=-100,  # 卖出 100 股
        new_price=100.0,
        cash_change=10000.0,  # 收入 $10,000
    )

    # 验证结果
    assert account.get_stock_quantity("AAPL") == 0  # 股票已卖完

    # 验证账户状态
    state = account.get_account_state()
    assert state.stock_position_count == 0  # 持仓被移除
    assert state.cash_balance == 101300.0  # $91,000 + $300 + $10,000
    assert state.total_equity == 101000.0  # NLV = $101,300 - $300 (option)
    assert state.used_margin == 100.0  # 期权保证金占用

    print("✅ Short Call assignment with sufficient stock test passed")


def test_short_call_assignment_insufficient_stock():
    """测试 Short Call ITM 到期，股票不足，先买后卖"""
    # 1. 初始化账户
    account = AccountSimulator(initial_capital=100_000)

    # 2. 当前无股票
    assert account.get_stock_quantity("AAPL") == 0
    assert account.cash == 100000.0

    # 3. 模拟 Short Call 到期行权
    # - 卖出 1 张合约，收取权利金 $300
    option_position = SimulatedPosition(
        position_id="AAPL-CALL-001",
        symbol="AAPL 20240315 100C",
        asset_type=AssetType.OPTION,
        underlying="AAPL",
        option_type=OptionType.CALL,
        strike=100.0,
        expiration=date(2024, 3, 15),
        quantity=-1,
        entry_price=3.0,
        entry_date=date(2024, 3, 1),
        lot_size=100,
        current_price=3.0,
        market_value=-300.0,  # -1 * $3.00 * 100
        margin_required=100.0,
    )
    account.add_position(
        position=option_position,
        cash_change=300.0,  # 收取权利金（正数）
    )

    # 4. 先买入股票（按市价 $105）
    buy_shares = 100  # 需要 100 股
    account.add_stock_position(
        symbol="AAPL",
        quantity=buy_shares,
        entry_price=105.0,
        trade_date=date(2024, 3, 15),
        cash_change=-10500.0,  # 扣除 $10,500
    )

    # 5. 再卖出股票（按行权价 $100）
    account.update_stock_position(
        position_id="AAPL-STOCK",
        quantity_change=-100,  # 卖出 100 股
        new_price=100.0,
        cash_change=10000.0,  # 收入 $10,000
    )

    # 验证结果
    assert account.get_stock_quantity("AAPL") == 0  # 股票已卖完

    # 验证账户状态
    state = account.get_account_state()
    assert state.stock_position_count == 0  # 持仓被移除
    assert state.cash_balance == 99800.0  # $100,000 + $300 - $10500 + $10000
    assert state.total_equity == 99500.0  # NLV = $99,800 - $300 (option)
    # 买入成本 $10500，卖出收入 $10000，净亏 $500，加上期权权利金 $300
    assert state.used_margin == 100.0  # 期权保证金占用

    print("✅ Short Call assignment with insufficient stock test passed")


def test_stock_position_update():
    """测试股票持仓的更新功能"""
    # 1. 初始化账户，持有 100 股 @ $90
    account = AccountSimulator(initial_capital=100_000)
    account.add_stock_position(
        symbol="AAPL",
        quantity=100,
        entry_price=90.0,
        trade_date=date(2024, 3, 1),
        cash_change=-9000.0,
    )

    # 2. 验证初始状态
    pos = account.get_stock_position("AAPL")
    assert pos.quantity == 100
    assert pos.market_value == 9000.0
    assert pos.unrealized_pnl == 0.0

    # 3. 股价上涨到 $95，更新持仓
    account.update_stock_position(
        position_id="AAPL-STOCK",
        quantity_change=0,  # 数量不变
        new_price=95.0,
        cash_change=0.0,
    )

    # 4. 验证更新后状态
    pos = account.get_stock_position("AAPL")
    assert pos.quantity == 100
    assert pos.current_price == 95.0
    assert pos.market_value == 9500.0  # 100 * $95
    assert pos.unrealized_pnl == 500.0  # ($95 - $90) * 100

    print("✅ Stock position update test passed")


def test_stock_greeks_and_margin():
    """测试股票持仓的希腊字母和保证金计算"""
    account = AccountSimulator(initial_capital=100_000)

    # 添加股票持仓
    account.add_stock_position(
        symbol="AAPL",
        quantity=100,
        entry_price=100.0,
        trade_date=date(2024, 3, 1),
        cash_change=-10000.0,
    )

    # 验证保证金：股票不占用保证金
    pos = account.get_stock_position("AAPL")
    assert pos.margin_required == 0.0

    # 验证 NLV 计算（股票市值计入 NLV）
    assert account.cash == 90000.0
    positions_value = sum(pos.market_value for pos in account.positions.values())
    assert positions_value == 10000.0  # 股票市值

    print("✅ Stock Greeks and margin test passed")


def test_trade_simulator_stock_commission():
    """测试 TradeSimulator 股票交易手续费计算"""
    simulator = TradeSimulator()

    # 测试买入手续费
    buy_execution = simulator.execute_stock_trade(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=100,
        price=100.0,
        trade_date=date(2024, 3, 1),
        reason="test_buy",
    )

    # 验证手续费：100 * $0.005 = $0.50，最低 $1.00
    assert buy_execution.commission == 1.0  # 最低 $1.00
    assert buy_execution.gross_amount == -10000.0  # 100 * $100（买入为负）
    assert buy_execution.net_amount == -10001.0  # -$10,000 - $1.00

    # 测试卖出手续费
    sell_execution = simulator.execute_stock_trade(
        symbol="AAPL",
        side=OrderSide.SELL,
        quantity=100,
        price=100.0,
        trade_date=date(2024, 3, 1),
        reason="test_sell",
    )

    assert sell_execution.commission == 1.0  # 最低 $1.00
    assert sell_execution.gross_amount == 10000.0  # 卖出为正
    assert sell_execution.net_amount == 9999.0  # $10,000 - $1.00

    # 测试大额交易（超过最低门槛）
    large_buy_execution = simulator.execute_stock_trade(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=1000,  # 1000 股
        price=10.0,
        trade_date=date(2024, 3, 1),
        reason="test_buy_large",
    )

    # 验证手续费：1000 * $0.005 = $5.00，最低 $1.00
    assert large_buy_execution.commission == 5.0  # 最低 $1.00
    assert large_buy_execution.gross_amount == -10000.0  # 负数 * 100（买入为负）
    assert large_buy_execution.net_amount == -10005.0  # -$10,000 - $5.00

    print("✅ TradeSimulator stock commission test passed")


def test_insufficient_cash_for_stock_buy():
    """测试现金不足时购买股票应该抛出异常"""
    account = AccountSimulator(initial_capital=10_000)

    # 尝试购买超出现金的股票数量
    # 需要 $50,000，但只有 $10,000
    try:
        account.add_stock_position(
            symbol="AAPL",
            quantity=500,  # 500 股 @ $100 = $50,000
            entry_price=100.0,
            trade_date=date(2024, 3, 1),
            cash_change=-50000.0,
        )
        assert False, "应该抛出 ValueError，但实际没有"
    except ValueError as e:
        # 验证错误消息包含必要信息
        assert "Insufficient cash" in str(e)
        assert "required=$50000.00" in str(e)
        assert "available=$10000.00" in str(e)
        print(f"✅ 正确捕获现金不足异常: {e}")

    # 验证账户状态未被修改
    assert account.get_stock_quantity("AAPL") == 0
    assert account.cash == 10000.0

    # 验证现金足够时可以正常购买
    account.add_stock_position(
        symbol="AAPL",
        quantity=50,  # 50 股 @ $100 = $5,000
        entry_price=100.0,
        trade_date=date(2024, 3, 1),
        cash_change=-5000.0,
    )
    assert account.get_stock_quantity("AAPL") == 50
    assert account.cash == 5000.0

    print("✅ Insufficient cash for stock buy test passed")


if __name__ == "__main__":
    print("Running stock assignment tests...\n")

    test_short_put_assignment_creates_stock_position()
    test_short_call_assignment_with_sufficient_stock()
    test_short_call_assignment_insufficient_stock()
    test_stock_position_update()
    test_stock_greeks_and_margin()
    test_trade_simulator_stock_commission()

    print("\n✅ All tests passed!")
