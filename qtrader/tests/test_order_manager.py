# qtrader/tests/test_order_manager.py

import pytest
from datetime import datetime
from qtrader.trading.order import OrderType, OrderStatus
from qtrader.trading.matching_engine import MatchingEngine


def test_submit_order_rounding(mock_context):
    """测试订单数量根据 lot_size 被正确取整。"""
    ctx = mock_context({'account': {'order_lot_size': 100}})
    
    # 测试买入时向下取整
    order_id_1 = ctx.order_manager.submit_order('000001', 150, OrderType.MARKET)
    assert ctx.order_manager.orders[order_id_1].amount == 100

    # 测试卖出时向下取整 (绝对值)
    order_id_2 = ctx.order_manager.submit_order('000001', -290, OrderType.MARKET)
    assert ctx.order_manager.orders[order_id_2].amount == 200

    # 测试数量小于 lot_size 的情况
    order_id_3 = ctx.order_manager.submit_order('000001', 50, OrderType.MARKET)
    assert order_id_3 is None


def test_cancel_order(mock_context):
    """测试订单撤销逻辑。"""
    ctx = mock_context()
    ctx.data_provider.set_price('000001', 10.0)

    # 提交一个市价单并成交
    filled_order_id = ctx.order_manager.submit_order('000001', 100, OrderType.MARKET)
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    me.match_orders(ctx.current_dt)
    
    # 提交一个不会立即成交的限价单
    open_order_id = ctx.order_manager.submit_order('000001', 100, OrderType.LIMIT, price=5.0)

    # 尝试撤销已成交订单（应失败）
    assert not ctx.order_manager.cancel_order(filled_order_id)
    assert ctx.order_manager.orders[filled_order_id].status == OrderStatus.FILLED

    # 尝试撤销未成交订单（应成功）
    assert ctx.order_manager.cancel_order(open_order_id)
    assert ctx.order_manager.orders[open_order_id].status == OrderStatus.CANCELLED

def test_get_orders(mock_context):
    """测试 get_* 方法能否正确筛选订单。"""
    ctx = mock_context()
    ctx.data_provider.set_price('000001', 10.0)
    ctx.data_provider.set_price('000002', 20.0) # 为被拒绝的订单也设置价格
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))

    # 1. 提交一个将成交的订单
    ctx.order_manager.submit_order('000001', 100, OrderType.MARKET)
    
    # 2. 提交一个将被拒绝的订单 (资金不足)
    ctx.order_manager.submit_order('000002', 1000000, OrderType.MARKET) 

    # 3. 提交一个将保持挂单的限价单
    ctx.order_manager.submit_order('000003', 100, OrderType.LIMIT, price=5.0)

    # 一次性撮合所有订单
    me.match_orders(ctx.current_dt)

    all_orders = ctx.order_manager.get_all_orders()
    # 诊断性断言：检查被拒绝的订单状态是否正确
    rejected_order = next(o for o in all_orders if o.symbol == '000002')
    assert rejected_order.status == OrderStatus.REJECTED

    assert len(ctx.order_manager.get_open_orders()) == 1
    assert ctx.order_manager.get_open_orders()[0].symbol == '000003'

    assert len(ctx.order_manager.get_filled_orders_today()) == 1
    assert ctx.order_manager.get_filled_orders_today()[0].symbol == '000001'

    statuses = {o.status for o in all_orders}
    assert statuses == {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.OPEN}
    assert len(ctx.order_manager.get_open_orders()) == 1
    assert ctx.order_manager.get_open_orders()[0].symbol == '000003'

    assert len(ctx.order_manager.get_filled_orders_today()) == 1
    assert ctx.order_manager.get_filled_orders_today()[0].symbol == '000001'

    all_orders = ctx.order_manager.get_all_orders()
    assert len(all_orders) == 3
    statuses = {o.status for o in all_orders}
    assert statuses == {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.OPEN}
