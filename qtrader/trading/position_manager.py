# qtrader/trading/position_manager.py

from typing import Dict, List, Optional, Any
from datetime import datetime
from ..trading.position import Position, PositionDirection
from ..core.context import Context

class PositionManager:
    """
    持仓管理器 (Position Manager)，负责精确跟踪和管理所有资产的持仓。

    本模块是账户状态的核心组成部分，与 `Portfolio` (资金) 和 `OrderManager` (订单)
    紧密协作。它不仅记录了持有什么，还记录了持仓的成本、数量、方向以及
    可用性（考虑 T+1 等交易规则）。

    主要职责:
    1.  **持仓跟踪**:
        - 使用字典 (`self.positions`) 存储所有当前的持仓对象 (`Position`)。
        - 支持为同一标的物同时管理多头 (`LONG`) 和空头 (`SHORT`) 持仓。

    2.  **交易处理 (`process_trade`)**:
        - 这是最核心的方法，当 `MatchingEngine` 成交一笔订单后调用此方法。
        - 根据订单的买卖方向，智能地处理开仓、平仓、平反向仓位等复杂逻辑。
        - 例如，一笔买单会优先用于平掉已有的空头仓位，剩余部分再用于开多仓。
        - 计算并返回每笔平仓交易的已实现盈亏 (`realized_pnl`)。

    3.  **可用性管理**:
        - 根据配置的交易规则（如 'T+1' 或 'T+0'），管理每个持仓的
          `available_amount` (可卖出数量)。

    4.  **状态持久化**:
        - 在每日结算时，记录当天所有持仓的详细快照 (`daily_snapshots`)。
        - 提供 `restore_positions` 和 `restore_daily_snapshots` 方法，
          以便在从状态文件恢复时重建持仓。
    """
    def __init__(self, context: Context):
        self.context = context
        self.positions: Dict[str, Position] = {}
        self.daily_snapshots: List[Dict[str, Any]] = []

    @staticmethod
    def _key(symbol: str, direction: PositionDirection) -> str:
        """生成用于持仓字典的唯一键。"""
        return f"{symbol}::{direction.value}"

    def get_position(self, symbol: str, direction: PositionDirection = PositionDirection.LONG) -> Optional[Position]:
        """
        获取指定证券和方向的持仓。

        Args:
            symbol (str): 证券代码。
            direction (PositionDirection): 持仓方向（多头或空头）。

        Returns:
            Optional[Position]: 如果存在则返回持仓对象，否则返回 None。
        """
        return self.positions.get(self._key(symbol, direction))

    def get_all_positions(self, direction: Optional[PositionDirection] = None) -> List[Position]:
        """
        获取所有持仓。

        Args:
            direction (Optional[PositionDirection]): （可选）筛选特定方向的持仓。

        Returns:
            List[Position]: 持仓对象列表。
        """
        if direction is None:
            return list(self.positions.values())
        return [p for p in self.positions.values() if p.direction == direction]

    def _ensure_position(
        self, symbol: str, symbol_name: Optional[str], amount: int,
        price: float, dt: datetime, direction: PositionDirection
    ) -> Position:
        """确保指定方向的持仓对象存在，如果不存在则创建一个。"""
        key = self._key(symbol, direction)
        if key not in self.positions:
            margin_rate = self.context.config.get('account', {}).get('short_margin_rate', 0.2)
            trading_rule = self.context.config.get('account', {}).get('trading_rule', 'T+1')
            pos = Position(
                symbol, symbol_name, amount, price, dt, direction, 
                margin_rate=margin_rate, trading_rule=trading_rule
            )
            self.positions[key] = pos
        return self.positions[key]



    def process_trade(self, order, price: float, dt: datetime, trading_mode: str) -> float:
        """
        根据一笔已成交的订单，处理并更新相关的持仓。

        这是持仓管理的核心逻辑，它模拟了真实的交易行为，包括“平昨”、“平今”、
        “开仓”以及多空双向的“先平后开”。

        执行逻辑:
        - **对于买单 (`buy`)**:
          1. 检查是否存在对应的空头持仓 (`short_pos`)。
          2. 如果存在，优先使用买单数量来平掉空仓（回补），并计算已实现盈亏。
          3. 如果买单数量在平空后仍有剩余，用剩余数量来开立或增加多头持仓。
        - **对于卖单 (`sell`)**:
          1. 检查是否存在对应的多头持仓 (`long_pos`)。
          2. 如果存在，优先使用卖单数量来平掉多仓，并计算已实现盈亏。
          3. 如果卖单数量在平多后仍有剩余，并且系统允许做空 (`long_short` 模式)，
             则用剩余数量来开立或增加空头持仓。

        Args:
            order (Order): 已成交的订单对象。
            price (float): 最终成交价格。
            dt (datetime): 成交时间戳。
            trading_mode (str): 交易模式 ('long_only' 或 'long_short')。

        Returns:
            float: 该笔交易产生的已实现盈亏 (realized PnL)。对于开仓交易，此值为 0。
        """
        realized_pnl = 0.0
        amount_remaining = abs(order.amount)
        symbol = order.symbol
        symbol_name = order.symbol_name

        rule = self.context.config.get('trading_rule', 'T+1')

        if order.side.value == 'buy':
            short_pos = self.get_position(symbol, PositionDirection.SHORT)
            # 场景1: 如果存在空头持仓，则此买单优先用于平空
            if short_pos and short_pos.total_amount > 0:
                closable = short_pos.available_amount if rule == 'T+1' else short_pos.total_amount
                cover_amount = min(amount_remaining, closable)
                if cover_amount > 0:
                    realized_pnl += short_pos.close(cover_amount, price, dt)
                    amount_remaining -= cover_amount
                    if short_pos.total_amount == 0:
                        del self.positions[self._key(symbol, PositionDirection.SHORT)]
            
            # 场景2: 如果买单数量在平空后仍有剩余，则用于开多仓
            if amount_remaining > 0:
                long_pos = self._ensure_position(
                    symbol, symbol_name, 0, price, dt, PositionDirection.LONG
                )
                long_pos.open(amount_remaining, price, dt)

        else:  # SELL
            long_pos = self.get_position(symbol, PositionDirection.LONG)
            # 场景1: 如果存在多头持仓，则此卖单优先用于平多
            if long_pos and long_pos.total_amount > 0:
                closable = long_pos.available_amount
                sell_amount = min(amount_remaining, closable)
                if sell_amount > 0:
                    realized_pnl += long_pos.close(sell_amount, price, dt)
                    amount_remaining -= sell_amount
                    if long_pos.total_amount == 0:
                        del self.positions[self._key(symbol, PositionDirection.LONG)]
            
            # 场景2: 如果卖单数量在平多后仍有剩余，且模式允许，则用于开空仓
            if amount_remaining > 0:
                if trading_mode != 'long_short':
                    raise RuntimeError("当前设置为只做多模式，无法开空。")
                short_pos = self._ensure_position(
                    symbol, symbol_name, 0, price, dt, PositionDirection.SHORT
                )
                short_pos.open(amount_remaining, price, dt)

        return realized_pnl

    def adjust_position(
        self, symbol: str, amount: int, avg_cost: float,
        symbol_name: Optional[str] = None,
        direction: PositionDirection = PositionDirection.LONG
    ):
        """
        手动调整或设置一个持仓。

        Args:
            symbol (str): 证券代码。
            amount (int): 调整后的总数量。
            avg_cost (float): 调整后的平均成本。
            symbol_name (Optional[str]): 证券名称。
            direction (PositionDirection): 持仓方向。
        """
        key = self._key(symbol, direction)
        if amount <= 0:
            if key in self.positions:
                del self.positions[key]
        else:
            pos = self.positions.get(key)
            dt = self.context.current_dt or datetime.now()
            if pos:
                pos.total_amount = amount
                pos.avg_cost = avg_cost
                # For a manually adjusted/set position, we assume it's fully available for trading.
                pos.available_amount = amount
                pos.today_open_amount = 0
                pos.last_update_time = dt
                # Also update margin rate in case config changed
                pos.margin_rate = self.context.config.get('account', {}).get('short_margin_rate', 0.2)
            else:
                margin_rate = self.context.config.get('account', {}).get('short_margin_rate', 0.2)
                trading_rule = self.context.config.get('account', {}).get('trading_rule', 'T+1')
                pos = Position(
                    symbol, symbol_name, amount, avg_cost, dt, direction,
                    margin_rate=margin_rate, trading_rule=trading_rule
                )
                # For a manually adjusted/set position, we assume it's fully available for trading.
                pos.available_amount = amount
                pos.today_open_amount = 0
                self.positions[key] = pos
        self.context.logger.info(
            f"持仓已手动调整: {symbol} ({direction.value}), "
            f"数量: {amount}, 成本: {avg_cost:.2f}"
        )

    def record_daily_snapshot(self, date_str: str, entries: List[Dict[str, Any]]):
        """记录一天的持仓快照。"""
        self.daily_snapshots.append({
            "date": date_str,
            "positions": entries
        })

    def restore_positions(self, positions: List[Position]):
        """从一个持仓列表恢复当前的所有持仓。"""
        self.positions = {
            self._key(pos.symbol, pos.direction): pos for pos in positions
        }

    def restore_daily_snapshots(self, snapshots: List[Dict[str, Any]]):
        """从一个快照列表恢复历史每日持仓快照。"""
        self.daily_snapshots = snapshots or []