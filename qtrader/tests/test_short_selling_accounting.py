# qtrader/tests/test_short_selling_accounting.py

import pytest
from qtrader.trading.matching_engine import MatchingEngine
from qtrader.trading.order import OrderType, OrderStatus
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


def test_short_selling_is_rejected_in_long_only_mode(mock_context, caplog):
    """
    测试在 'long_only' 模式下，任何试图开空仓的行为都会被系统正确拒绝。
    """
    # 1. 初始状态设置
    # 配置一个只允许做多的上下文
    ctx = mock_context({
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_only', # 只做多模式
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
    
    # 2. 尝试执行卖空操作
    ctx.data_provider.set_price('STOCK_B', 200.0)
    
    order_id = ctx.order_manager.submit_order(
        symbol='STOCK_B',
        amount=-100, # 尝试卖空100股
        order_type=OrderType.MARKET
    )
    order = ctx.order_manager.orders[order_id]

    # 3. 执行撮合
    me.match_orders(ctx.current_dt)

    # 4. 验证订单是否被正确拒绝
    assert order.status == OrderStatus.REJECTED
    # 验证日志中是否包含了正确的拒绝原因
    assert "被拒绝: 持仓不足 (欲卖: 100, 可用: 0)" in caplog.text

    # 5. 验证没有创建任何仓位，且账户资金未变
    assert not ctx.position_manager.get_all_positions()
    assert ctx.portfolio.net_worth == 1000000


def test_flip_from_long_to_short_in_long_short_mode(mock_context):
    """
    测试在 long_short 模式下，从多头反手开空仓的行为。
    """
    # 1. 设置场景: long_short 模式，持有100股多仓
    ctx = mock_context({
        'account': {
            'initial_cash': 100000,
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
            'slippage': {'rate': 0}
        }
    })
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    pm = ctx.position_manager
    
    # 先买入100股 @ $10
    buy_price = 10.0
    ctx.data_provider.set_price('FLIP', buy_price)
    buy_order_id = ctx.order_manager.submit_order('FLIP', 100, OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    assert pm.get_position('FLIP', 'long').total_amount == 100
    cash_after_buy = 100000 - (100 * 10.0)
    assert ctx.portfolio.cash == pytest.approx(cash_after_buy)

    # 2. 执行反手操作: 卖出150股 @ $12
    flip_price = 12.0
    ctx.data_provider.set_price('FLIP', flip_price)
    flip_order_id = ctx.order_manager.submit_order('FLIP', -150, OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    # 3. 验证结果
    # a) 多头仓位消失
    assert pm.get_position('FLIP', 'long') is None
    # b) 空头仓位建立
    short_pos = pm.get_position('FLIP', 'short')
    assert short_pos is not None
    assert short_pos.total_amount == 50
    assert short_pos.avg_cost == pytest.approx(flip_price)

    # c) 验证现金变化
    # 现金 = 买入后现金 + 卖出150股所得
    cash_after_flip = cash_after_buy + (150 * flip_price)
    assert ctx.portfolio.cash == pytest.approx(cash_after_flip)

    # d) 验证已实现盈亏 (平掉100股多仓的利润)
    realized_pnl = (flip_price - buy_price) * 100
    # 验证净资产 = 初始资金 + 已实现盈亏 + 未实现盈亏
    unrealized_pnl = (flip_price - short_pos.avg_cost) * 50 # 应该是0
    expected_net_worth = 100000 + realized_pnl + unrealized_pnl
    assert ctx.portfolio.net_worth == pytest.approx(expected_net_worth)

    # e) 验证保证金
    expected_margin = (50 * flip_price) * 0.5
    assert ctx.portfolio.margin == pytest.approx(expected_margin)


def test_flip_from_long_to_short_is_rejected_in_long_only_mode(mock_context, caplog):
    """
    测试在 long_only 模式下，任何试图反手开空仓的行为都会被正确拒绝。
    """
    # 1. 设置场景: long_only 模式，持有100股多仓
    ctx = mock_context({
        'account': {
            'initial_cash': 100000,
            'trading_mode': 'long_only',
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
            'slippage': {'rate': 0}
        }
    })
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    pm = ctx.position_manager

    # 先买入100股 @ $10
    buy_price = 10.0
    ctx.data_provider.set_price('FLIP', buy_price)
    buy_order_id = ctx.order_manager.submit_order('FLIP', 100, OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    
    original_position = pm.get_position('FLIP', 'long')
    assert original_position.total_amount == 100
    cash_after_buy = ctx.portfolio.cash

    # 2. 尝试执行反手操作: 卖出150股
    flip_price = 12.0
    ctx.data_provider.set_price('FLIP', flip_price)
    flip_order_id = ctx.order_manager.submit_order('FLIP', -150, OrderType.MARKET)
    flip_order = ctx.order_manager.orders[flip_order_id]
    me.match_orders(ctx.current_dt)

    # 3. 验证订单被拒绝
    assert flip_order.status == OrderStatus.REJECTED
    # 验证日志中是否包含了正确的拒绝原因
    assert "被拒绝: 持仓不足 (欲卖: 150, 可用: 100)" in caplog.text

    # 4. 验证原有仓位和资金未受影响
    assert pm.get_position('FLIP', 'long') is original_position
    assert pm.get_position('FLIP', 'long').total_amount == 100
    assert ctx.portfolio.cash == cash_after_buy
