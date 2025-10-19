# qtrader/tests/test_account.py

import pytest
from qtrader.trading.position import Position, PositionDirection
from unittest.mock import MagicMock


def test_available_cash(mock_context):
    """测试可用资金的计算是否正确。"""
    ctx = mock_context()
    portfolio = ctx.portfolio
    assert portfolio.available_cash == portfolio.cash  # 初始时，可用资金=总现金

    portfolio.margin = 50000
    assert portfolio.available_cash == portfolio.cash - 50000


def test_update_margin(mock_context):
    """测试保证金更新逻辑。"""
    ctx = mock_context()
    pm = ctx.position_manager
    portfolio = ctx.portfolio

    # 模拟一个多头仓位 (不应产生保证金)
    long_pos = MagicMock(spec=Position)
    long_pos.direction = PositionDirection.LONG
    long_pos.margin = 0

    # 模拟两个空头仓位
    short_pos_1 = MagicMock(spec=Position)
    short_pos_1.direction = PositionDirection.SHORT
    short_pos_1.margin = 20000

    short_pos_2 = MagicMock(spec=Position)
    short_pos_2.direction = PositionDirection.SHORT
    short_pos_2.margin = 35000

    pm.get_all_positions = MagicMock(return_value=[long_pos, short_pos_1, short_pos_2])

    portfolio.update_margin(pm)

    assert portfolio.margin == 55000
    assert portfolio.available_cash == portfolio.cash - 55000


def test_returns_calculation(mock_context):
    """测试累计收益率的计算。"""
    ctx = mock_context({'account': {'initial_cash': 1000000}})
    portfolio = ctx.portfolio

    assert portfolio.returns == 0.0  # 初始收益率为0

    # 模拟总资产增加
    portfolio.total_value = 1100000
    assert portfolio.returns == pytest.approx(0.1)

    # 模拟总资产减少
    portfolio.total_value = 950000
    assert portfolio.returns == pytest.approx(-0.05)

    # 测试初始资金为0的边缘情况
    portfolio.initial_cash = 0
    portfolio.total_value = 1000
    assert portfolio.returns == 0.0
