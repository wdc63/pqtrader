# qtrader/tests/test_position.py
# pytest qtrader/tests/

import pytest
from datetime import datetime, timedelta
from qtrader.trading.position import Position

@pytest.fixture
def sample_datetime():
    return datetime(2023, 1, 3, 10, 0, 0)

def test_t1_buy_on_t_cannot_sell(sample_datetime):
    """测试 T+1：当日买入的仓位，当日不可卖出。"""
    pos = Position("000001", "平安银行", 1000, 10.0, sample_datetime)
    assert pos.total_amount == 1000
    assert pos.today_open_amount == 1000
    assert pos.available_amount == 0

def test_t1_buy_on_t_can_sell_on_t1(sample_datetime):
    """测试 T+1：当日买入的仓位，次日可以卖出。"""
    pos = Position("000001", "平安银行", 1000, 10.0, sample_datetime)
    pos.settle_t1() # 模拟日终结算
    assert pos.total_amount == 1000
    assert pos.today_open_amount == 0
    assert pos.available_amount == 1000
    
    # 在 T+1 日卖出
    next_day = sample_datetime + timedelta(days=1)
    pnl = pos.close(500, 11.0, next_day)
    assert pnl == 500.0
    assert pos.total_amount == 500
    assert pos.available_amount == 500

def test_t1_with_base_position_buy_then_sell(sample_datetime):
    """测试 T+1：持有底仓，当日先买后卖，只能卖出底仓部分。"""
    # T-1日持有1000股
    pos = Position("000001", "平安银行", 1000, 10.0, sample_datetime - timedelta(days=1))
    pos.settle_t1()
    assert pos.available_amount == 1000

    # T日买入500股
    pos.open(500, 11.0, sample_datetime)
    assert pos.total_amount == 1500
    assert pos.today_open_amount == 500
    assert pos.available_amount == 1000 # 可用部分不变

    # T日卖出800股 (小于可用仓位)
    pnl = pos.close(800, 11.5, sample_datetime)
    assert pos.total_amount == 700
    assert pos.available_amount == 200 # 1000 - 800
    assert pos.today_open_amount == 500 # 当日买入部分不变

def test_t1_with_base_position_sell_then_buy(sample_datetime):
    """测试 T+1：持有底仓，当日先卖后买。"""
    # T-1日持有1000股
    pos = Position("000001", "平安银行", 1000, 10.0, sample_datetime - timedelta(days=1))
    pos.settle_t1()

    # T日卖出300股
    pos.close(300, 11.0, sample_datetime)
    assert pos.total_amount == 700
    assert pos.available_amount == 700

    # T日再买入200股
    pos.open(200, 11.5, sample_datetime)
    assert pos.total_amount == 900
    assert pos.today_open_amount == 200
    assert pos.available_amount == 700 # 可用部分不变

    # T日结算后
    pos.settle_t1()
    assert pos.total_amount == 900
    assert pos.today_open_amount == 0
    assert pos.available_amount == 900