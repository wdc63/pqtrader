# qtrader/trading/commission.py

from typing import Dict
from ..trading.order import Order, OrderSide

class CommissionCalculator:
    """
    交易手续费和税费计算器。

    根据配置计算买入和卖出订单的佣金和税费。
    """
    def __init__(self, config: Dict):
        self.buy_commission = config.get('buy_commission', 0.0002)
        self.sell_commission = config.get('sell_commission', 0.0002)
        self.buy_tax = config.get('buy_tax', 0.0)
        self.sell_tax = config.get('sell_tax', 0.001)
        self.min_commission = config.get('min_commission', 5.0)

    def calculate(self, order: Order, price: float) -> float:
        """
        计算给定订单的手续费和税费。

        Args:
            order (Order): 需要计算费用的订单对象。
            price (float): 订单的成交价格。

        Returns:
            float: 计算出的总费用（佣金 + 税费）。
        """
        total_value = price * order.amount
        
        # 根据订单方向（买/卖）应用不同的费率
        if order.side == OrderSide.BUY:
            commission = total_value * self.buy_commission
            tax = total_value * self.buy_tax
        else:  # SELL
            commission = total_value * self.sell_commission
            tax = total_value * self.sell_tax
        
        # 应用最低佣金限制
        commission = max(commission, self.min_commission)
        
        # 总费用 = 佣金 + 税费
        return commission + tax

