# qtrader/tests/test_short_selling_accounting.py

import pytest
from qtrader.trading.matching_engine import MatchingEngine
from qtrader.trading.order import OrderType
from qtrader.trading.position import PositionDirection

def test_short_selling_and_covering_accounting(mock_context):
    """
    一个完整的单元测试，用于验证卖空和回补过程中的完整资金流和资产计算。
    """
    # 1. 初始状态设置
    # 配置一个支持多空交易的上下文，初始资金100万，保证金率50%
    ctx = mock_context({
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_short',
            'short_margin_rate': 0.5,
            'trading_rule': 'T+0'
        },
        'matching': {
            'commission': {
                'buy_commission': 0,
                'sell_commission': 0,
                'buy_tax': 0,
                'sell_tax': 0,
                'min_commission': 0
            },
            'slippage': {
                'rate': 0.0
            }
        }
    })
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    initial_net_worth = ctx.portfolio.initial_cash
    ctx.portfolio.net_worth = initial_net_worth

    # 2. 执行卖空操作 (Short Sell)
    # 卖空 100 股 @ $150/股
    short_price = 150.0
    short_amount = 100
    ctx.data_provider.set_price('STOCK_A', short_price)
    
    short_order_id = ctx.order_manager.submit_order(
        symbol='STOCK_A',
        amount=-short_amount, # 负数表示卖出
        order_type=OrderType.MARKET
    )
    me.match_orders(ctx.current_dt)

    # 3. 验证卖空后的账户状态
    print("\n--- 卖空后状态验证 ---")
    
    # a) 验证现金：现金应该增加卖空所得
    expected_cash_after_short = initial_net_worth + (short_price * short_amount)
    print(f"预期现金: {expected_cash_after_short:.2f}, 实际现金: {ctx.portfolio.cash:.2f}")
    assert ctx.portfolio.cash == pytest.approx(expected_cash_after_short)

    # b) 验证保证金：保证金应该被冻结
    expected_margin = short_price * short_amount * 0.5
    print(f"预期保证金: {expected_margin:.2f}, 实际保证金: {ctx.portfolio.margin:.2f}")
    assert ctx.portfolio.margin == pytest.approx(expected_margin)

    # c) 验证可用现金
    expected_available_cash = expected_cash_after_short - expected_margin
    print(f"预期可用现金: {expected_available_cash:.2f}, 实际可用现金: {ctx.portfolio.available_cash:.2f}")
    assert ctx.portfolio.available_cash == pytest.approx(expected_available_cash)

    # d) 验证净资产：净资产应该约等于初始资金（因为现金增加，但负债也等值增加）
    # 此时仓位已更新，直接检查 portfolio 的核心属性
    print(f"预期净资产: {initial_net_worth:.2f}, 实际净资产: {ctx.portfolio.net_worth:.2f}")
    assert ctx.portfolio.net_worth == pytest.approx(initial_net_worth)
    assert ctx.portfolio.long_positions_value == 0
    assert ctx.portfolio.short_positions_value == pytest.approx(short_price * short_amount)
    
    # 4. 执行买入回补操作 (Buy to Cover)
    # 以 $140/股 的价格买回 100 股
    cover_price = 140.0
    cover_amount = 100
    ctx.data_provider.set_price('STOCK_A', cover_price)

    cover_order_id = ctx.order_manager.submit_order(
        symbol='STOCK_A',
        amount=cover_amount, # 正数表示买入
        order_type=OrderType.MARKET
    )
    me.match_orders(ctx.current_dt)

    # 5. 验证回补后的账户状态
    print("\n--- 回补后状态验证 ---")

    # a) 验证现金：现金应该减少回补所需的支出
    expected_cash_after_cover = expected_cash_after_short - (cover_price * cover_amount)
    print(f"预期现金: {expected_cash_after_cover:.2f}, 实际现金: {ctx.portfolio.cash:.2f}")
    assert ctx.portfolio.cash == pytest.approx(expected_cash_after_cover)

    # b) 验证保证金：保证金应该被释放
    print(f"预期保证金: 0.00, 实际保证金: {ctx.portfolio.margin:.2f}")
    assert ctx.portfolio.margin == 0.0

    # c) 验证净资产：净资产应该反映这次交易的利润
    profit = (short_price - cover_price) * short_amount
    expected_final_net_worth = initial_net_worth + profit
    print(f"预期最终净资产: {expected_final_net_worth:.2f}, 实际净资产: {ctx.portfolio.net_worth:.2f}")
    assert ctx.portfolio.net_worth == pytest.approx(expected_final_net_worth)
    assert ctx.portfolio.short_positions_value == 0 # 空头仓位消失
