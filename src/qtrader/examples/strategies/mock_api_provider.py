# qtrader/data/examples/mock_api_provider.py
import datetime
import random
from typing import List, Dict, Optional
from qtrader.data.interface import AbstractDataProvider

class MockDataProvider(AbstractDataProvider):
    """一个用于测试和演示的模拟数据提供者"""
    def __init__(self):
        self._price_data = {} # 缓存模拟价格

    def get_trading_calendar(self, start: str, end: str) -> List[str]:
        start_date = datetime.datetime.strptime(start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(end, '%Y-%m-%d')
        days = []
        while start_date <= end_date:
            if start_date.weekday() < 5: # 周一到周五
                days.append(start_date.strftime('%Y-%m-%d'))
            start_date += datetime.timedelta(days=1)
        return days

    def get_current_price(self, symbol: str, dt: datetime) -> Optional[Dict]:
        # 只返回价格相关信息
        key = (symbol, dt.strftime('%Y-%m-%d'))
        if key not in self._price_data:
            self._price_data[key] = 10 + random.random() * 5
        
        base_price = self._price_data[key]
        price = base_price + (dt.hour - 9) * 0.1 + (dt.minute / 60) * 0.1 + random.uniform(-0.05, 0.05)
        price = round(price, 2)
        
        return {
            'current_price': price,
            'ask1': round(price * 1.001, 2),
            'bid1': round(price * 0.999, 2),
            'high_limit': round(base_price * 1.1, 2),
            'low_limit': round(base_price * 0.9, 2),
        }

    def get_symbol_info(self, symbol: str, date: str) -> Optional[Dict]:
        # [新增] 实现获取静态信息的方法
        # 在模拟环境中，我们简单地返回一个固定的名字，并且永不停牌
        return {
            'symbol_name': f'模拟股票{symbol}',
            'is_suspended': False,
        }