# qtrader/tests/test_position_manager.py

import pytest
from qtrader.trading.position import PositionDirection

def test_get_position_with_string_and_enum_direction(mock_context):
    """
    测试 get_position 方法是否能正确处理字符串和枚举类型的 direction 参数。
    """
    ctx = mock_context({
        'account': {
            'trading_mode': 'long_short'
        }
    })
    pm = ctx.position_manager
    symbol = 'TEST_STOCK'

    # 1. 手动创建并添加一个多头和空头仓位
    pm.adjust_position(symbol, 100, 10.0, direction=PositionDirection.LONG)
    pm.adjust_position(symbol, 50, 20.0, direction=PositionDirection.SHORT)

    long_pos = pm.positions.get(f"{symbol}::{PositionDirection.LONG.value}")
    short_pos = pm.positions.get(f"{symbol}::{PositionDirection.SHORT.value}")

    assert long_pos is not None
    assert short_pos is not None

    # 2. 测试各种有效的输入
    # 2.1. 原始枚举类型
    assert pm.get_position(symbol, PositionDirection.LONG) is long_pos
    assert pm.get_position(symbol, PositionDirection.SHORT) is short_pos

    # 2.2. 小写字符串
    assert pm.get_position(symbol, 'long') is long_pos
    assert pm.get_position(symbol, 'short') is short_pos

    # 2.3. 大小写不敏感的字符串
    assert pm.get_position(symbol, 'Long') is long_pos
    assert pm.get_position(symbol, 'SHORT') is short_pos

    # 2.4. 默认参数 (应为 LONG)
    assert pm.get_position(symbol) is long_pos

    # 3. 测试无效的输入
    # 3.1. 无效的字符串
    with pytest.raises(ValueError, match="无效的持仓方向字符串"):
        pm.get_position(symbol, 'invalid_direction')

    # 3.2. 无效的类型
    with pytest.raises(TypeError, match="持仓方向参数类型错误"):
        pm.get_position(symbol, 123)

    # 4. 测试获取不存在的仓位
    assert pm.get_position('NON_EXISTENT_STOCK', 'long') is None