# qtrader/trading/order_manager.py

from typing import Dict, List, Optional, Union
from datetime import datetime
from ..trading.order import Order, OrderType, OrderSide, OrderStatus
from ..core.context import Context


class OrderManager:
    """
    订单管理器，负责处理所有与订单相关的操作。

    包括提交、撤销、查询订单，以及管理当日订单和历史成交订单。
    """
    def __init__(self, context: Context):
        self.context = context
        self.orders: Dict[str, Order] = {}
        self.filled_orders_history: List[Order] = []

    def submit_order(
        self,
        symbol: str,
        amount: int,
        order_type: Union[str, OrderType],
        price: Optional[float] = None,
        symbol_name: Optional[str] = None
    ) -> Optional[str]:
        """
        提交一个新订单。

        Args:
            symbol (str): 证券代码。
            amount (int): 订单数量（正数为买入，负数为卖出）。
            order_type (OrderType): 订单类型（市价单或限价单）。
            price (Optional[float]): 限价单的价格。
            symbol_name (Optional[str]): 证券名称。

        Returns:
            Optional[str]: 如果订单成功提交，则返回订单ID，否则返回 None。
        """
        if amount == 0:
            self.context.logger.warning("下单数量为0，订单被拒绝。")
            return None

        order_type_enum: OrderType
        if isinstance(order_type, str):
            try:
                order_type_enum = OrderType(order_type.lower())
            except ValueError:
                self.context.logger.error(f"无效的订单类型字符串: '{order_type}'. 请使用 'market' 或 'limit'。")
                return None
        elif isinstance(order_type, OrderType):
            order_type_enum = order_type
        else:
            self.context.logger.error(f"订单类型参数类型错误: {type(order_type)}. 请使用 OrderType 枚举或字符串。")
            return None

        lot_size = int(self.context.config.get('account', {}).get('order_lot_size', 1) or 1)
        lot_size = max(lot_size, 1)

        sign = 1 if amount > 0 else -1
        abs_amount = abs(amount)

        # 根据最小交易单位（如100股）对订单数量进行规范化
        normalized_amount = (abs_amount // lot_size) * lot_size
        if normalized_amount == 0:
            self.context.logger.warning(
                f"下单数量 {abs_amount} 不满足最小交易单位 {lot_size}，订单被拒绝。"
            )
            return None

        if normalized_amount != abs_amount:
            self.context.logger.info(
                f"订单数量根据最小交易单位 {lot_size} 已从 {abs_amount} 调整为 {normalized_amount}。"
            )

        adjusted_amount = sign * normalized_amount

        side = OrderSide.BUY if adjusted_amount > 0 else OrderSide.SELL
        order = Order(
            symbol=symbol,
            amount=abs(adjusted_amount),
            side=side,
            order_type=order_type_enum,
            limit_price=price,
            symbol_name=symbol_name
        )
        if self.context.mode == 'simulation':
            # 在模拟盘中，created_time 是下单那一刻的真实墙上时钟时间
            order.created_time = datetime.now()
        else:
            # 在回测中，created_time 是当前 K 线的时间戳
            order.created_time = self.context.current_dt
            
        order.created_bar_time = self.context.current_dt # 无论何种模式，都记录下是哪个Bar触发的
        self.orders[order.id] = order
        self.context.logger.info(
            f"提交订单: {order.id} | {side.value.upper()} {symbol} {order.amount} "
            f"@ {'Market' if price is None else price}"
        )
        return order.id

    def cancel_order(self, order_id: str) -> bool:
        """
        撤销一个未成交的订单。

        Args:
            order_id (str): 要撤销的订单ID。

        Returns:
            bool: 如果成功撤销，则返回 True，否则返回 False。
        """
        if order_id not in self.orders:
            self.context.logger.warning(f"撤单失败: 订单ID {order_id} 不存在。")
            return False

        order = self.orders[order_id]
        if order.cancel():
            self.context.logger.info(f"订单 {order_id} 已成功撤销。")
            return True
        else:
            self.context.logger.warning(f"撤单失败: 订单 {order_id} 状态为 {order.status.value}，无法撤销。")
            return False

    def get_open_orders(self) -> List[Order]:
        """获取所有当前未成交的订单。"""
        return [o for o in self.orders.values() if o.status == OrderStatus.OPEN]

    def get_filled_orders_today(self) -> List[Order]:
        """获取当日所有已成交的订单。"""
        return [o for o in self.orders.values() if o.status == OrderStatus.FILLED]

    def add_filled_order_to_history(self, order: Order):
        """将一个已成交的订单添加到历史记录中。"""
        self.filled_orders_history.append(order)

    def get_all_orders_history(self) -> List[Order]:
        """获取所有历史成交订单。"""
        return self.filled_orders_history

    def get_all_orders(self) -> List[Order]:
        """
        获取所有已知的订单，包括当日所有状态的订单和历史成交订单。
        """
        all_orders = self.orders.copy()
        all_orders_dict = {}
        # 使用字典来合并订单，确保当日的最新状态优先
        all_orders_dict = {order.id: order for order in self.filled_orders_history}
        all_orders_dict.update(self.orders)

        return list(all_orders_dict.values())

    def clear_today_orders(self):
        """在日终结算时，清空当日的订单记录。"""
        self.orders.clear()

    def restore_orders(self, orders: List[Order]):
        """
        从一个订单列表恢复订单管理器的状态。

        Args:
            orders (List[Order]): 用于恢复状态的订单列表。
        """
        # 将加载的订单区分为历史成交订单和当日未完成订单
        for order in orders:
            if order.status == OrderStatus.FILLED:
                self.filled_orders_history.append(order)
            else:
                self.orders[order.id] = order
