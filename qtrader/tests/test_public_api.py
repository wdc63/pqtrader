# qtrader/tests/test_public_api.py

import pytest
from datetime import datetime
from qtrader.trading.position import Position, PositionDirection

def test_portfolio_public_properties(mock_context):
    """
    测试在有持仓的情况下，Portfolio 的公开属性是否计算正确。
    特别是测试新添加的 long_market_value 和 short_liability。
    """
    # 1. 设置场景
    ctx = mock_context({
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_short' # 允许做空
        }
    })
    pm = ctx.position_manager
    portfolio = ctx.portfolio
    
    # 设定当前市场价格
    ctx.data_provider.set_price('AAPL', 150.0)
    ctx.data_provider.set_price('GOOG', 2800.0)

    # 2. 手动创建并添加一个多头仓位和一个空头仓位
    # 多头: 100 股 AAPL, 成本 140
    long_pos = Position(
        symbol='AAPL',
        symbol_name='Apple Inc.',
        amount=100,
        avg_cost=140.0,
        current_dt=ctx.current_dt,
        direction=PositionDirection.LONG,
        trading_rule='T+0'
    )
    long_pos.update_price(150.0) # 更新市价
    
    # 空头: 10 股 GOOG, 成本 2900
    short_pos = Position(
        symbol='GOOG',
        symbol_name='Google LLC',
        amount=10,
        avg_cost=2900.0,
        current_dt=ctx.current_dt,
        direction=PositionDirection.SHORT,
        trading_rule='T+0',
        margin_rate=0.5 # 假设保证金率50%
    )
    short_pos.update_price(2800.0) # 更新市价

    # 直接将持仓放入 PositionManager
    pm.positions = {
        pm._key('AAPL', PositionDirection.LONG): long_pos,
        pm._key('GOOG', PositionDirection.SHORT): short_pos,
    }

    # 3. 触发财务指标更新
    portfolio.update_financials(pm)

    # 4. 断言公开 API 的值
    
    # 检查新增的属性
    assert portfolio.long_market_value == pytest.approx(100 * 150.0) # 15000
    assert portfolio.short_liability == pytest.approx(10 * 2800.0) # 28000

    # 检查 USER_GUIDE 中提到的其他核心属性
    # 净持仓市值 = 多头市值 - 空头负债
    expected_net_pos_value = 15000 - 28000
    assert portfolio.net_positions_value == pytest.approx(expected_net_pos_value) # -13000

    # 总资产 = 现金 + 多头市值 (空头负债不计入总资产)
    expected_total_assets = 1000000 + 15000
    assert portfolio.total_assets == pytest.approx(expected_total_assets) # 1015000

    # 净资产 = 现金 + 净持仓市值
    expected_net_worth = 1000000 + expected_net_pos_value
    assert portfolio.net_worth == pytest.approx(expected_net_worth) # 987000
    
    # 保证金 = 空头仓位市值 * 保证金率
    expected_margin = (10 * 2800.0) * 0.5
    assert portfolio.margin == pytest.approx(expected_margin) # 14000

    # 可用现金 = 总现金 - 保证金
    expected_available_cash = 1000000 - expected_margin
    assert portfolio.available_cash == pytest.approx(expected_available_cash) # 986000

    # 累计收益率
    expected_returns = (expected_net_worth - 1000000) / 1000000
    assert portfolio.returns == pytest.approx(expected_returns) # -0.013
