# qtrader/tests/test_matching_engine.py

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from qtrader.trading.matching_engine import MatchingEngine
from qtrader.trading.order import OrderType, OrderStatus
from qtrader.trading.position import PositionDirection

# Test Suite for Long-Only Mode
# ==============================

def test_long_buy_sufficient_cash(mock_context):
    """测试 T+1 多头模式：资金充足时买入成功。"""
    ctx = mock_context({'account': {'initial_cash': 100000, 'trading_rule': 'T+1'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('000001', 10.0)

    # amount > 0 for BUY
    order_id = ctx.order_manager.submit_order(symbol='000001', amount=1000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    order = ctx.order_manager.orders[order_id]

    assert order.status == OrderStatus.FILLED
    assert ctx.portfolio.cash == 100000 - (1000 * order.filled_price) - order.commission
    pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert pos is not None
    assert pos.total_amount == 1000
    assert pos.available_amount == 0  # T+1 rule

def test_long_buy_insufficient_cash(mock_context):
    """测试 T+1 多头模式：资金不足时买入失败。"""
    ctx = mock_context({'account': {'initial_cash': 5000, 'trading_rule': 'T+1'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('000001', 10.0)

    # amount > 0 for BUY
    order_id = ctx.order_manager.submit_order(symbol='000001', amount=1000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    order = ctx.order_manager.orders[order_id]

    assert order.status == OrderStatus.REJECTED
    assert ctx.portfolio.cash == 5000
    assert ctx.position_manager.get_position('000001', PositionDirection.LONG) is None

def test_long_sell_t1_rule_fail(mock_context):
    """测试 T+1 多头模式：卖出当日买入的仓位失败。"""
    ctx = mock_context({'account': {'initial_cash': 100000, 'trading_rule': 'T+1'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('000001', 10.0)

    # First, buy the stock
    buy_order_id = ctx.order_manager.submit_order(symbol='000001', amount=1000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    buy_order = ctx.order_manager.orders[buy_order_id]
    assert buy_order.status == OrderStatus.FILLED

    # Then, try to sell it on the same day (amount < 0 for SELL)
    sell_order_id = ctx.order_manager.submit_order(symbol='000001', amount=-500, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    sell_order = ctx.order_manager.orders[sell_order_id]

    assert sell_order.status == OrderStatus.REJECTED
    pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert pos.total_amount == 1000

def test_long_sell_t0_rule_success(mock_context):
    """测试 T+0 多头模式：卖出当日买入的仓位成功。"""
    ctx = mock_context({'account': {'initial_cash': 100000, 'trading_rule': 'T+0', 'trading_mode': 'long_short'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('000001', 10.0)

    # First, buy the stock
    buy_order_id = ctx.order_manager.submit_order(symbol='000001', amount=1000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    buy_order = ctx.order_manager.orders[buy_order_id]
    assert buy_order.status == OrderStatus.FILLED

    # Then, sell it on the same day (amount < 0 for SELL)
    ctx.data_provider.set_price('000001', 11.0)
    sell_order_id = ctx.order_manager.submit_order(symbol='000001', amount=-500, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    sell_order = ctx.order_manager.orders[sell_order_id]

    assert sell_order.status == OrderStatus.FILLED
    pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert pos.total_amount == 500

# Test Suite for Long-Short Mode
# ================================

def test_short_sell_sufficient_margin(mock_context):
    """测试多空模式：保证金充足时开空仓成功。"""
    ctx = mock_context({'account': {'initial_cash': 100000, 'trading_mode': 'long_short', 'short_margin_rate': 0.5}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('600519', 1500.0)

    # amount < 0 for SELL
    order_id = ctx.order_manager.submit_order(symbol='600519', amount=-100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    order = ctx.order_manager.orders[order_id]

    assert order.status == OrderStatus.FILLED
    pos = ctx.position_manager.get_position('600519', PositionDirection.SHORT)
    assert pos is not None
    assert pos.total_amount == 100
    
    assert ctx.portfolio.margin == pytest.approx(order.filled_price * 100 * 0.5)
    assert ctx.portfolio.cash == 100000 + (order.filled_price * 100) - order.commission
    assert ctx.portfolio.available_cash == ctx.portfolio.cash - ctx.portfolio.margin

def test_short_sell_insufficient_margin(mock_context):
    """测试多空模式：保证金不足时开空仓失败。"""
    ctx = mock_context({'account': {'initial_cash': 10000, 'trading_mode': 'long_short', 'short_margin_rate': 0.5}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('600519', 1500.0)

    # amount < 0 for SELL
    order_id = ctx.order_manager.submit_order(symbol='600519', amount=-100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    order = ctx.order_manager.orders[order_id]

    assert order.status == OrderStatus.REJECTED
    assert ctx.position_manager.get_position('600519', PositionDirection.SHORT) is None
    assert ctx.position_manager.get_position('600519', PositionDirection.SHORT) is None
    assert ctx.portfolio.cash == 10000

def test_buy_to_cover_short_position_t1(mock_context):
    """测试T+1规则下，空头仓位在次日能被成功平仓。"""
    ctx = mock_context({'account': {'initial_cash': 200000, 'trading_rule': 'T+1', 'trading_mode': 'long_short'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    
    # T日，开空仓
    ctx.data_provider.set_price('600519', 1500.0)
    short_order_id = ctx.order_manager.submit_order(symbol='600519', amount=-100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    short_order = ctx.order_manager.orders[short_order_id]
    assert short_order.status == OrderStatus.FILLED
    short_pos = ctx.position_manager.get_position('600519', PositionDirection.SHORT)
    assert short_pos.available_amount == 0 # 当日开仓，可用为0

    # 模拟T日日终结算
    short_pos.settle_t1()
    assert short_pos.available_amount == 100 # 结算后，可用数量变为100

    # T+1日，买入平仓
    ctx.current_dt += timedelta(days=1)
    ctx.data_provider.set_price('600519', 1400.0)
    cover_order_id = ctx.order_manager.submit_order(symbol='600519', amount=100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    cover_order = ctx.order_manager.orders[cover_order_id]

    assert cover_order.status == OrderStatus.FILLED
    assert ctx.position_manager.get_position('600519', PositionDirection.SHORT) is None


def test_short_sell_t1_rule_fail(mock_context):
    """测试T+1规则下，当日开的空仓在当日无法平仓。"""
    ctx = mock_context({'account': {'initial_cash': 200000, 'trading_rule': 'T+1', 'trading_mode': 'long_short'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    
    # T日，开空仓
    ctx.data_provider.set_price('600519', 1500.0)
    short_order_id = ctx.order_manager.submit_order(symbol='600519', amount=-100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    assert ctx.order_manager.orders[short_order_id].status == OrderStatus.FILLED

    # T日，尝试买入平仓
    ctx.data_provider.set_price('600519', 1400.0)
    cover_order_id = ctx.order_manager.submit_order(symbol='600519', amount=100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    cover_order = ctx.order_manager.orders[cover_order_id]

    assert cover_order.status == OrderStatus.REJECTED
    short_pos = ctx.position_manager.get_position('600519', PositionDirection.SHORT)
    assert short_pos is not None
    assert short_pos.total_amount == 100

def test_flip_from_short_to_long_insufficient_cash(mock_context):
    """测试当资金不足以完成“平空转多”时，订单会被正确拒绝。"""
    # 初始资金10万，开100股的空仓（价值15万，保证金7.5万）
    # 剩余可用资金 100000 - 75000 = 25000
    ctx = mock_context({'account': {'initial_cash': 100000, 'trading_rule': 'T+0', 'trading_mode': 'long_short', 'short_margin_rate': 0.5}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('600519', 1500.0)

    # 1. 开空仓
    short_order_id = ctx.order_manager.submit_order(symbol='600519', amount=-100, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    assert ctx.order_manager.orders[short_order_id].status == OrderStatus.FILLED
    # 确认可用资金计算正确：cash增加了卖券所得，但减去了保证金占用
    assert ctx.portfolio.available_cash > 150000 

    # 2. 提交一个大额买单 (200股)，平掉100股空仓后，还需新开100股多仓
    # 新开100股多仓需要约 1500 * 100 = 15万。总购买力约17.5万，但订单需要30万，资金不足
    ctx.data_provider.set_price('600519', 1500.0)
    flip_order_id = ctx.order_manager.submit_order(symbol='600519', amount=200, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    flip_order = ctx.order_manager.orders[flip_order_id]

    # 3. 断言订单被拒绝
    assert flip_order.status == OrderStatus.REJECTED

def test_position_flipping(mock_context):
    """测试多空模式下，多头寸能被一个大额卖单正确地反转为空头寸。"""
    ctx = mock_context({'account': {'initial_cash': 200000, 'trading_rule': 'T+0', 'trading_mode': 'long_short', 'short_margin_rate': 0.5}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    ctx.data_provider.set_price('000001', 10.0)

    # 1. 先建立一个1000股的多头仓位
    buy_order_id = ctx.order_manager.submit_order(symbol='000001', amount=1000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    assert ctx.order_manager.orders[buy_order_id].status == OrderStatus.FILLED
    long_pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert long_pos is not None
    assert long_pos.total_amount == 1000

    # 2. 下一个足以反转头寸的卖单 (卖出3000股)
    ctx.data_provider.set_price('000001', 12.0)
    flip_order_id = ctx.order_manager.submit_order(symbol='000001', amount=-3000, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)
    flip_order = ctx.order_manager.orders[flip_order_id]

    # 3. 验证结果
    assert flip_order.status == OrderStatus.FILLED
    # 多头仓位应被完全平掉
    assert ctx.position_manager.get_position('000001', PositionDirection.LONG) is None
    # 应建立了一个2000股的空头仓位
    short_pos = ctx.position_manager.get_position('000001', PositionDirection.SHORT)
    assert short_pos is not None
    assert short_pos.total_amount == 2000
    # 验证保证金是否被正确计算
    assert ctx.portfolio.margin == pytest.approx(flip_order.filled_price * 2000 * 0.5)



# Test Suite for Simulation Mode Logic
# =====================================

def test_simulation_mode_uses_order_creation_time(mock_context):
    """
    测试在 Simulation 模式下，撮合引擎是否正确使用了订单自己的创建时间
    去获取价格，而不是使用 Scheduler 传入的时间脉冲。
    """
    # 1. 设置 Context 为 simulation 模式
    ctx = mock_context({'engine': {'mode': 'simulation'}})
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))

    # 2. 模拟 DataProvider，并监视 get_current_price 方法
    mock_get_price = MagicMock(return_value={'current_price': 10.0})
    ctx.data_provider.get_current_price = mock_get_price

    # 3. 提交一个订单。在 simulation 模式下，OrderManager 会自动
    #    将 order.created_time 设置为 datetime.now()
    with patch('qtrader.trading.order_manager.datetime') as mock_dt:
        # 冻结一个可预测的 "now" 时间
        fake_now = datetime(2025, 10, 20, 10, 0, 5)
        mock_dt.now.return_value = fake_now
        
        order_id = ctx.order_manager.submit_order(
            symbol='000001', amount=100, order_type=OrderType.MARKET
        )

    order = ctx.order_manager.orders[order_id]
    # 确认订单的创建时间是我们伪造的 "now"
    assert order.created_time == fake_now

    # 4. 调用撮合引擎，但传入一个 *不同* 的时间戳，模拟 Scheduler 的时间脉冲
    scheduler_pulse_dt = datetime(2025, 10, 20, 10, 0, 10)
    me.match_orders(scheduler_pulse_dt)

    # 5. 断言：检查 get_current_price 被调用时，传入的是订单自己的创建时间，
    #    而不是 Scheduler 的时间脉冲，这证明了我们的逻辑是正确的。
    mock_get_price.assert_called_once()
    call_args, _ = mock_get_price.call_args
    assert call_args[0] == '000001'       # symbol
    assert call_args[1] == fake_now  # dt
