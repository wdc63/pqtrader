# qtrader/trading/slippage.py

from typing import Dict
from ..trading.order import Order

class SlippageModel:
    """
    滑点模型，用于在回测中模拟交易滑点。

    目前仅支持固定比率滑点。
    """
    def __init__(self, config: Dict):
        self.type = config.get('type', 'fixed')
        self.rate = config.get('rate', 0.001)

    def calculate(self, order: Order, price: float) -> float:
        """
        根据配置计算滑点。

        Args:
            order (Order): 当前交易的订单。
            price (float): 理论成交价格。

        Returns:
            float: 计算出的滑点值。
        """
        if self.type == 'fixed':
            # 固定比率滑点：滑点值 = 价格 * 滑点率
            return price * self.rate
        return 0.0