# qtrader/tests/conftest.py

import pytest

import logging

from datetime import datetime, timedelta

from unittest.mock import MagicMock



from ..core.context import Context

from ..trading.account import Portfolio

from ..trading.position_manager import PositionManager

from ..trading.order_manager import OrderManager

from ..data.interface import AbstractDataProvider



class MockDataProvider(AbstractDataProvider):

    """一个用于测试的模拟数据提供者。"""

    def __init__(self):

        self.prices = {}



    def set_price(self, symbol, price):

        self.prices[symbol] = {

            'current_price': price,

            'ask1': price,

            'bid1': price,

            'high_limit': price * 1.1,

            'low_limit': price * 0.9,

        }



    def get_current_price(self, symbol: str, dt: datetime):

        return self.prices.get(symbol)



    def get_symbol_info(self, symbol: str, date_str: str):

        return {'symbol_name': f'Symbol {symbol}', 'is_suspended': False}



    def get_trading_calendar(self) -> list[str]:

        return [

            (datetime(2023, 1, 3) + timedelta(days=i)).strftime('%Y-%m-%d')

            for i in range(10)

        ]



@pytest.fixture

def mock_context():

    """

    创建一个可配置的、用于测试的模拟 Context fixture。

    可以通过 request.param 传入配置字典。

    """

    def _create_context(config_override=None):

        base_config = {

            'account': {

                'initial_cash': 1000000,

                'trading_rule': 'T+1',

                'trading_mode': 'long_only',

                'short_margin_rate': 0.2

            },

            'matching': {}

        }

        if config_override:

            for key, value in config_override.items():

                if key in base_config and isinstance(base_config[key], dict):

                    base_config[key].update(value)

                else:

                    base_config[key] = value



        ctx = Context(config=base_config)

        ctx.portfolio = Portfolio(initial_cash=base_config['account']['initial_cash'])

        ctx.position_manager = PositionManager(ctx)

        ctx.order_manager = OrderManager(ctx)

        ctx.data_provider = MockDataProvider()

        # 使用真实的 logger 以便 caplog 能够捕获

        ctx.logger = logging.getLogger(f"test_logger_{id(_create_context)}")

        ctx.logger.propagate = True

        ctx.current_dt = datetime(2023, 1, 5, 10, 0, 0)

        return ctx



    return _create_context
