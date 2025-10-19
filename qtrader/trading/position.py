# qtrader/trading/position.py

from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

class PositionDirection(Enum):
    LONG = 'long'
    SHORT = 'short'

class Position:
    """
    表示单个证券的持仓对象。

    该类封装了持仓的所有核心属性，如数量、成本、方向等，
    并提供了开仓、平仓、结算等核心操作的方法。
    它同时内部处理 T+1 和 T+0 交易规则下的可用数量计算。
    """
    def __init__(
        self,
        symbol: str,
        symbol_name: Optional[str],
        amount: int,
        avg_cost: float,
        current_dt: datetime,
        direction: PositionDirection = PositionDirection.LONG,
        margin_rate: float = 0.2,
        trading_rule: str = 'T+1'
    ):
        # --- 核心持仓属性 ---
        self.symbol: str = symbol
        self.symbol_name: Optional[str] = symbol_name
        self.direction: PositionDirection = direction
        self.total_amount: int = amount
        self.avg_cost: float = avg_cost
        self.current_price: Optional[float] = avg_cost
        self.init_time: datetime = current_dt
        self.last_update_time: datetime = current_dt
        self.trading_rule = trading_rule

        # --- T+1 相关属性 ---
        self.today_open_amount: int = amount
        self.available_amount: int = 0
        if self.trading_rule == 'T+0':
            self.available_amount = amount
        
        # --- 结算与盈亏相关 ---
        self.last_settle_price: float = avg_cost
        self.margin_rate: float = margin_rate

    @property
    def market_value(self) -> float:
        """计算当前持仓的总市值。"""
        if self.current_price is None:
            return 0.0
        # 空头持仓的市值为负
        multiplier = 1 if self.direction == PositionDirection.LONG else -1
        return multiplier * self.total_amount * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        """计算当前持仓的浮动盈亏。"""
        if self.current_price is None:
            return 0.0
        if self.direction == PositionDirection.LONG:
            return (self.current_price - self.avg_cost) * self.total_amount
        return (self.avg_cost - self.current_price) * self.total_amount

    @property
    def unrealized_pnl_ratio(self) -> float:
        """计算当前持仓的浮动盈亏比例。"""
        if self.avg_cost == 0:
            return 0.0
        # 根据多空方向计算浮动盈亏比例
        multiplier = 1 if self.direction == PositionDirection.LONG else -1
        price = self.current_price or self.avg_cost
        return multiplier * (price - self.avg_cost) / self.avg_cost

    @property
    def margin(self) -> float:
        """计算此持仓占用的保证金。"""
        if self.direction == PositionDirection.SHORT:
            # 保证金总是基于市值的绝对值计算
            return abs(self.total_amount * self.current_price) * self.margin_rate if self.current_price else 0.0
        return 0.0

    @property
    def market_value_at_cost(self) -> float:
        """计算当前持仓的成本市值（带符号）。"""
        multiplier = 1 if self.direction == PositionDirection.LONG else -1
        return multiplier * self.total_amount * self.avg_cost

    def update_price(self, price: float):
        """更新持仓的当前市场价格。"""
        self.current_price = price

    def open(self, amount: int, price: float, dt: datetime):
        """
        增加持仓（开仓）。

        Args:
            amount (int): 开仓数量。
            price (float): 开仓价格。
            dt (datetime): 开仓时间。
        """
        # 更新平均成本: (旧总成本 + 新增成本) / 新总数量
        total_cost = self.avg_cost * self.total_amount + price * amount
        self.total_amount += amount
        if self.total_amount > 0:
            self.avg_cost = total_cost / self.total_amount
        else:
            self.avg_cost = 0.0
        self.today_open_amount += amount
        if self.trading_rule == 'T+0':
            self.available_amount += amount
        self.last_update_time = dt

    def close(self, amount: int, price: float, dt: datetime) -> float:
        """
        减少持仓（平仓），并计算已实现盈亏。

        Args:
            amount (int): 平仓数量。
            price (float): 平仓价格。
            dt (datetime): 平仓时间。

        Returns:
            float: 该笔平仓交易实现的盈亏。
        """
        if amount > self.total_amount:
            raise ValueError("平仓数量大于持仓数量。")
        # 根据多空方向计算已实现盈亏
        if self.direction == PositionDirection.LONG:
            pnl = (price - self.avg_cost) * amount
        else:  # SHORT
            pnl = (self.avg_cost - price) * amount
        self.total_amount -= amount
        self.available_amount = max(self.available_amount - amount, 0)
        if self.total_amount == 0:
            self.today_open_amount = 0
        self.last_update_time = dt
        return pnl
    
    def settle_t1(self):
        """
        执行 T+1 规则的日终结算。

        将今日开仓的数量累加到明日可用数量中。
        """
        self.available_amount += self.today_open_amount
        self.today_open_amount = 0

    def settle_day(self, close_price: float, date_str: str) -> Optional[Dict[str, Any]]:
        """
        执行每日结算，计算当日盈亏并更新结算价格。

        Args:
            close_price (float): 当日收盘价。
            date_str (str): 日期字符串 (YYYY-MM-DD)。

        Returns:
            Optional[Dict[str, Any]]: 如果持仓不为空，则返回包含当日持仓快照信息的字典。
        """
        if self.total_amount == 0:
            self.last_settle_price = close_price
            self.update_price(close_price)
            return None

        # 如果没有昨日结算价（例如持仓首日），则使用当日收盘价作为基准
        prev_price = self.last_settle_price if self.last_settle_price is not None else close_price
        if self.direction == PositionDirection.LONG:
            daily_pnl = (close_price - prev_price) * self.total_amount
        else:
            daily_pnl = (prev_price - close_price) * self.total_amount

        self.last_settle_price = close_price
        self.update_price(close_price)

        base_value = abs(self.avg_cost * self.total_amount)
        daily_pnl_ratio = (daily_pnl / base_value) if base_value > 0 else 0.0

        # [修正] 市值计算必须带符号，以反映空头头寸的负债属性
        market_val = (1 if self.direction == PositionDirection.LONG else -1) * self.total_amount * close_price

        return {
            "date": date_str,
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "direction": self.direction.value,
            "amount": self.total_amount,
            "close_price": close_price,
            "market_value": market_val,
            "daily_pnl": daily_pnl,
            "daily_pnl_ratio": daily_pnl_ratio
        }