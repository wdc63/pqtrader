# qtrader/trading/order.py

from datetime import datetime
from typing import Optional
from enum import Enum
from dataclasses import dataclass, field
from ..utils.helpers import generate_order_id

class OrderSide(Enum):
    """订单的交易方向。"""
    BUY = 'buy'
    SELL = 'sell'

class OrderType(Enum):
    """订单的类型。"""
    MARKET = 'market'
    LIMIT = 'limit'

class OrderStatus(Enum):
    """订单的生命周期状态。"""
    OPEN = 'open'          # 订单已创建，等待成交
    FILLED = 'filled'      # 订单已完全成交
    REJECTED = 'rejected'  # 订单被拒绝
    CANCELLED = 'cancelled'# 订单已被用户撤销
    EXPIRED = 'expired'    # 订单已过期（例如，当日未成交的订单）

@dataclass
class Order:
    """
    表示一个交易订单的数据类。

    它包含了订单的所有属性，如证券代码、数量、方向、类型和状态，
    以及由系统在订单生命周期中填充的成交信息。
    """
    # --- 用户提交的核心订单信息 ---
    symbol: str
    amount: int
    side: OrderSide
    order_type: OrderType
    limit_price: Optional[float] = None
    symbol_name: Optional[str] = None

    # --- 系统生成的订单状态与信息 ---
    id: str = field(default_factory=generate_order_id)
    status: OrderStatus = OrderStatus.OPEN
    created_time: Optional[datetime] = None
    created_bar_time: Optional[datetime] = None
    filled_time: Optional[datetime] = None
    filled_price: Optional[float] = None
    commission: Optional[float] = None
    is_immediate: bool = True  # 标记是否为立即成交订单

    def fill(self, price: float, commission: float, dt: datetime):
        """
        将订单标记为已成交。

        Args:
            price (float): 成交价格。
            commission (float): 交易手续费。
            dt (datetime): 成交时间。
        """
        self.status = OrderStatus.FILLED
        self.filled_price = price
        self.commission = commission
        self.filled_time = dt

    def reject(self, reason: str = ""):
        """
        将订单标记为已拒绝。

        Args:
            reason (str): 拒绝原因。
        """
        self.status = OrderStatus.REJECTED

    def cancel(self) -> bool:
        """
        尝试将订单标记为已撤销。

        只有当订单状态为 `OPEN` 时才能成功撤销。

        Returns:
            bool: 如果成功撤销，则返回 True，否则返回 False。
        """
        if self.status == OrderStatus.OPEN:
            self.status = OrderStatus.CANCELLED
            return True
        return False

    def expire(self):
        """将未成交的订单标记为已过期。"""
        if self.status == OrderStatus.OPEN:
            self.status = OrderStatus.EXPIRED

    def mark_as_historical(self):
        """将订单标记为历史挂单，用于撮合引擎区分处理。"""
        self.is_immediate = False