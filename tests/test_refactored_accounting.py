# qtrader/tests/test_refactored_accounting.py

import pytest
from datetime import datetime
from qtrader.core.context import Context
from qtrader.trading.matching_engine import MatchingEngine
from qtrader.trading.order import OrderType
from qtrader.trading.position import PositionDirection
from qtrader.data.interface import AbstractDataProvider
from qtrader.trading.account import Portfolio
from qtrader.trading.order_manager import OrderManager
from qtrader.trading.position_manager import PositionManager
from qtrader.utils.logger import setup_logger

class MockDataProvider(AbstractDataProvider):
    """用于测试的模拟数据提供者"""
    def __init__(self):
        self.prices = {}

    def set_price(self, symbol, price):
        self.prices[symbol] = {'current_price': price, 'close': price}

    def get_current_price(self, symbol, dt=None):
        return self.prices.get(symbol)

    def get_symbol_info(self, symbol, date_str):
        return {'symbol_name': symbol}

    def get_trading_calendar(self):
        """为抽象方法提供最小化实现"""
        return []

def test_short_selling_and_covering_with_refactored_accounting():
    """
    端到端测试：验证经过重构的会计模型在“卖空-回补”流程中的准确性。
    """
    # 1. 初始化上下文和撮合引擎
    ctx = Context()
    ctx.data_provider = MockDataProvider()
    # [修正] Context没有configure方法，正确的方式是设置config属性后初始化组件
    ctx.config = {
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_short',
            'short_margin_rate': 0.5,
            'trading_rule': 'T+0'
        },
        'matching': {
        'commission': { 'buy_commission': 0, 'sell_commission': 0, 'buy_tax': 0, 'sell_tax': 0, 'min_commission': 0 },
        # [修正] Slippage模型需要一个字典配置. 使用一个无效的type来确保滑点为0
        'slippage': {'type': 'fixed', 'rate': 0}
                    }
    }
    # [修正] 在单元测试中，手动创建并设置核心组件
    account_config = ctx.config.get('account', {})
    # [修正] Portfolio的构造函数不接受 trading_mode
    # [修正] Portfolio的构造函数只接受 initial_cash
    ctx.portfolio = Portfolio(
        initial_cash=account_config.get('initial_cash', 0)
    )
    # [修正] 手动初始化所有依赖的组件
    # [修正] 手动初始化所有依赖的组件
    # [修正] 使用 setup_logger 工厂函数来创建 logger
    ctx.logger = setup_logger({'level': 'INFO', 'console_output': True}, context=ctx)
    ctx.order_manager = OrderManager(ctx)
    ctx.position_manager = PositionManager(ctx)
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    initial_cash = ctx.portfolio.initial_cash
    # 手动设置初始净资产，确保起点干净
    ctx.portfolio.net_worth = initial_cash

    # 2. 执行卖空操作 (Short Sell @ $150)
    short_price = 150.0
    short_amount = 100
    stock_symbol = 'STOCK_A'
    ctx.data_provider.set_price(stock_symbol, short_price)
    # [修正] 为Context设置一个模拟的当前时间
    ctx.current_dt = datetime(2024, 1, 1, 10, 0, 0)

    ctx.order_manager.submit_order(
        symbol=stock_symbol,
        amount=-short_amount,  # 负数表示卖出
        order_type=OrderType.MARKET
    )
    me.match_orders(ctx.current_dt)

    # 3. 验证卖空后的账户状态
    portfolio = ctx.portfolio
    short_sale_value = short_price * short_amount

    # a) 现金应该增加卖空所得
    expected_cash_after_short = initial_cash + short_sale_value
    assert portfolio.cash == pytest.approx(expected_cash_after_short)

    # b) 保证金应该被冻结
    expected_margin = short_sale_value * 0.5
    assert portfolio.margin == pytest.approx(expected_margin)

    # c) 可用现金 = 总现金 - 保证金
    expected_available_cash = expected_cash_after_short - expected_margin
    assert portfolio.available_cash == pytest.approx(expected_available_cash)

    # d) 验证各项持仓市值
    assert portfolio.long_positions_value == 0
    assert portfolio.short_positions_value == pytest.approx(short_sale_value)
    assert portfolio.net_positions_value == pytest.approx(-short_sale_value)

    # e) 验证总资产和净资产
    expected_total_assets = expected_cash_after_short + portfolio.long_positions_value
    assert portfolio.total_assets == pytest.approx(expected_total_assets)
    
    # 净资产应约等于初始资金 (现金增加，但负债也等值增加)
    expected_net_worth = portfolio.total_assets - portfolio.short_positions_value
    assert portfolio.net_worth == pytest.approx(expected_net_worth)
    assert portfolio.net_worth == pytest.approx(initial_cash)

    # 4. 执行买入回补操作 (Buy to Cover @ $140, 实现盈利)
    cover_price = 140.0
    cover_amount = 100
    ctx.data_provider.set_price(stock_symbol, cover_price)
    # [修正] 更新模拟时间
    ctx.current_dt = datetime(2024, 1, 1, 11, 0, 0)

    ctx.order_manager.submit_order(
        symbol=stock_symbol,
        amount=cover_amount,  # 正数表示买入
        order_type=OrderType.MARKET
    )
    me.match_orders(ctx.current_dt)

    # 5. 验证回补后的最终账户状态
    profit = (short_price - cover_price) * cover_amount
    
    # a) 最终现金应反映交易利润
    expected_final_cash = expected_cash_after_short - (cover_price * cover_amount)
    assert portfolio.cash == pytest.approx(expected_final_cash)
    assert portfolio.cash == pytest.approx(initial_cash + profit)

    # b) 保证金应该被完全释放
    assert portfolio.margin == 0.0

    # c) 所有持仓应该都已平掉
    assert portfolio.long_positions_value == 0
    assert portfolio.short_positions_value == 0
    assert portfolio.net_positions_value == 0
    assert not ctx.position_manager.get_all_positions()

    # d) 最终净资产和总资产应反映利润
    expected_final_net_worth = initial_cash + profit
    assert portfolio.net_worth == pytest.approx(expected_final_net_worth)
    assert portfolio.total_assets == pytest.approx(expected_final_net_worth)

def test_unprofitable_short_sale_accounting():
    """
    边界测试：验证在“亏损的”卖空交易中，会计模型的准确性。
    """
    # 1. 初始化环境
    ctx = Context()
    ctx.data_provider = MockDataProvider()
    ctx.config = {
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_short',
            'short_margin_rate': 0.5,
            'trading_rule': 'T+0'  # [修正] 确保日内交易规则
        },
        'matching': {
            'commission': { 'buy_commission': 0, 'sell_commission': 0, 'buy_tax': 0, 'sell_tax': 0, 'min_commission': 0 },
            'slippage': {'type': 'fixed', 'rate': 0}
        }
    }
    ctx.portfolio = Portfolio(initial_cash=1000000)
    ctx.logger = setup_logger({'level': 'INFO', 'console_output': False}, context=ctx)
    ctx.order_manager = OrderManager(ctx)
    ctx.position_manager = PositionManager(ctx)
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    initial_cash = ctx.portfolio.initial_cash
    ctx.portfolio.net_worth = initial_cash

    # 2. 卖空 @ $100
    short_price = 100.0
    short_amount = 100
    stock_symbol = 'STOCK_B'
    ctx.data_provider.set_price(stock_symbol, short_price)
    ctx.current_dt = datetime(2024, 1, 2, 10, 0, 0)
    ctx.order_manager.submit_order(symbol=stock_symbol, amount=-short_amount, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    # 3. 回补 @ $110 (造成亏损)
    cover_price = 110.0
    ctx.data_provider.set_price(stock_symbol, cover_price)
    ctx.current_dt = datetime(2024, 1, 2, 11, 0, 0)
    ctx.order_manager.submit_order(symbol=stock_symbol, amount=short_amount, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    # 4. 验证最终状态
    loss = (cover_price - short_price) * short_amount
    expected_final_net_worth = initial_cash - loss
    
    assert not ctx.position_manager.get_all_positions()
    assert ctx.portfolio.margin == 0.0
    assert ctx.portfolio.net_worth == pytest.approx(expected_final_net_worth)
    assert ctx.portfolio.cash == pytest.approx(expected_final_net_worth)


def test_mixed_long_short_portfolio_accounting():
    """
    边界测试：验证在同时持有多仓和空仓时，各项聚合指标的准确性。
    """
    # 1. 初始化环境
    ctx = Context()
    ctx.data_provider = MockDataProvider()
    ctx.config = {
        'account': {
            'initial_cash': 1000000,
            'trading_mode': 'long_short',
            'short_margin_rate': 0.5,
            'trading_rule': 'T+0'  # [修正] 确保日内交易规则
        },
        'matching': {
            'commission': { 'buy_commission': 0, 'sell_commission': 0, 'buy_tax': 0, 'sell_tax': 0, 'min_commission': 0 },
            'slippage': {'type': 'fixed', 'rate': 0}
        }
    }
    ctx.portfolio = Portfolio(initial_cash=1000000)
    ctx.logger = setup_logger({'level': 'INFO', 'console_output': False}, context=ctx)
    ctx.order_manager = OrderManager(ctx)
    ctx.position_manager = PositionManager(ctx)
    me = MatchingEngine(ctx, ctx.config.get('matching', {}))
    initial_cash = ctx.portfolio.initial_cash
    ctx.portfolio.net_worth = initial_cash
    ctx.current_dt = datetime(2024, 1, 3, 10, 0, 0)

    # 2. 建立一个多头仓位和一个空头仓位
    # a) 买入 100 股 'STOCK_LONG' @ $50
    long_stock = 'STOCK_LONG'
    long_price = 50.0
    long_amount = 100
    ctx.data_provider.set_price(long_stock, long_price)
    ctx.order_manager.submit_order(symbol=long_stock, amount=long_amount, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    # b) 卖空 100 股 'STOCK_SHORT' @ $80
    short_stock = 'STOCK_SHORT'
    short_price = 80.0
    short_amount = 100
    ctx.data_provider.set_price(short_stock, short_price)
    ctx.order_manager.submit_order(symbol=short_stock, amount=-short_amount, order_type=OrderType.MARKET)
    me.match_orders(ctx.current_dt)

    # 3. 验证混合持仓下的账户状态
    portfolio = ctx.portfolio
    long_value = long_price * long_amount
    short_value = short_price * short_amount

    # a) 验证现金变化
    expected_cash = initial_cash - long_value + short_value
    assert portfolio.cash == pytest.approx(expected_cash)

    # b) 验证保证金
    expected_margin = short_value * 0.5
    assert portfolio.margin == pytest.approx(expected_margin)

    # c) 验证各项聚合市值
    assert portfolio.long_positions_value == pytest.approx(long_value)
    assert portfolio.short_positions_value == pytest.approx(short_value)
    assert portfolio.net_positions_value == pytest.approx(long_value - short_value)

    # d) 验证总资产和净资产
    expected_total_assets = expected_cash + long_value
    expected_net_worth = expected_total_assets - short_value
    assert portfolio.total_assets == pytest.approx(expected_total_assets)
    assert portfolio.net_worth == pytest.approx(expected_net_worth)
    # 净资产应约等于初始资金 (不计价格波动)
    assert portfolio.net_worth == pytest.approx(initial_cash)