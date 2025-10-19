# qtrader/tests/test_context.py

import pytest
from ..core.context import Context
from ..trading.position import PositionDirection

def test_set_initial_state_basic(mock_context):
    """测试 set_initial_state 的基本功能，包括设置现金和多头持仓。"""
    ctx = mock_context()
    ctx.is_initializing = True
    
    initial_cash = 50000
    positions = [
        {'symbol': '000001', 'amount': 100, 'avg_cost': 10.0, 'symbol_name': '平安银行'}
    ]
    
    ctx.set_initial_state(cash=initial_cash, positions=positions)
    
    # 验证现金
    assert ctx.portfolio.cash == initial_cash
    
    # 验证持仓
    pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert pos is not None
    assert pos.total_amount == 100
    assert pos.avg_cost == 10.0
    
    # 验证账户总值
    expected_total_value = initial_cash + (100 * 10.0)
    assert ctx.portfolio.initial_cash == expected_total_value
    assert ctx.portfolio.total_value == expected_total_value
    assert ctx.portfolio.available_cash == initial_cash # 多头不占用保证金
    assert ctx.portfolio.margin == 0

def test_set_initial_state_short_position(mock_context):
    """测试 set_initial_state 设置空头持仓和保证金计算。"""
    ctx = mock_context({'account': {'short_margin_rate': 0.5}})
    ctx.is_initializing = True
    
    ctx.set_initial_state(cash=100000, positions=[
        {'symbol': '600036', 'amount': -200, 'avg_cost': 50.0}
    ])
    
    # 验证持仓
    pos = ctx.position_manager.get_position('600036', PositionDirection.SHORT)
    assert pos is not None
    assert pos.total_amount == 200
    assert pos.avg_cost == 50.0
    
    # 验证保证金和可用现金
    expected_margin = 200 * 50.0 * 0.5
    assert ctx.portfolio.margin == expected_margin
    assert ctx.portfolio.available_cash == 100000 - expected_margin

def test_set_initial_state_fetch_cost_and_name(mock_context):
    """测试当成本和名称未提供时，自动从 data_provider 获取。"""
    ctx = mock_context()
    ctx.is_initializing = True
    ctx.data_provider.set_price('000002', 25.0)
    
    ctx.set_initial_state(cash=50000, positions=[
        {'symbol': '000002', 'amount': 100}
    ])
    
    pos = ctx.position_manager.get_position('000002', PositionDirection.LONG)
    assert pos is not None
    assert pos.avg_cost == 25.0
    assert pos.symbol_name == 'Symbol 000002'

def test_set_initial_state_call_restrictions(mock_context):
    """测试 set_initial_state 的调用限制。"""
    ctx = mock_context()
    
    # 1. 在非初始化阶段调用应失败
    ctx.is_initializing = False
    with pytest.raises(RuntimeError, match="set_initial_state.. 只能在策略的 initialize.. 方法中调用。"):
        ctx.set_initial_state(cash=10000)
        
    # 2. 多次调用应失败
    ctx.is_initializing = True
    ctx.set_initial_state(cash=10000) # 第一次成功
    with pytest.raises(RuntimeError, match="set_initial_state.. 只能被调用一次"):
        ctx.set_initial_state(cash=20000) # 第二次失败


def test_align_account_state_basic(mock_context):
    """测试 align_account_state 的基本功能，包括更新现金和现有持仓。"""
    ctx = mock_context()
    ctx.is_initializing = True
    ctx.set_initial_state(cash=100000, positions=[
        {'symbol': '000001', 'amount': 100, 'avg_cost': 10.0}
    ])
    
    # 模拟进入结算阶段
    ctx.market_phase = 'SETTLEMENT'
    
    # 对齐目标：现金减少，持仓成本增加
    target_cash = 95000
    target_positions = [
        {'symbol': '000001', 'amount': 100, 'avg_cost': 10.5}
    ]
    
    ctx.align_account_state(cash=target_cash, positions=target_positions)
    
    assert ctx.portfolio.cash == target_cash
    pos = ctx.position_manager.get_position('000001', PositionDirection.LONG)
    assert pos is not None
    assert pos.avg_cost == 10.5
    
    expected_total_value = target_cash + (100 * 10.5)
    assert ctx.portfolio.total_value == expected_total_value

def test_align_account_state_add_and_remove_positions(mock_context):
    """测试 align_account_state 新增和移除持仓的功能。"""
    ctx = mock_context()
    ctx.is_initializing = True
    ctx.set_initial_state(cash=100000, positions=[
        {'symbol': '000001', 'amount': 100, 'avg_cost': 10.0} # 将被移除
    ])
    ctx.market_phase = 'SETTLEMENT'
    
    # 对齐目标：移除 000001，新增 600036 (空头)
    target_positions = [
        {'symbol': '600036', 'amount': -50, 'avg_cost': 50.0}
    ]
    
    ctx.align_account_state(cash=100000, positions=target_positions)
    
    # 验证 000001 已被移除
    assert ctx.position_manager.get_position('000001', PositionDirection.LONG) is None
    
    # 验证 600036 已被添加
    pos_short = ctx.position_manager.get_position('600036', PositionDirection.SHORT)
    assert pos_short is not None
    assert pos_short.total_amount == 50
    
    # 验证保证金
    margin_rate = ctx.config['account']['short_margin_rate']
    expected_margin = 50 * 50.0 * margin_rate
    assert ctx.portfolio.margin == expected_margin

def test_align_account_state_call_restrictions(mock_context):
    """测试 align_account_state 的调用时机限制。"""
    ctx = mock_context()
    ctx.market_phase = 'TRADING'
    
    with pytest.raises(RuntimeError, match="不能在交易时段内调用"):
        ctx.align_account_state(cash=10000, positions=[])
