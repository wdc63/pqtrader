# qtrader/trading/account.py

from typing import List, Dict, Any, TYPE_CHECKING
from datetime import datetime
from .position import PositionDirection

# 避免循环导入
if TYPE_CHECKING:
    from .position_manager import PositionManager


class Portfolio:
    """
    投资组合（账户）对象，系统的核心财务状态机。

    本类负责跟踪和管理账户的所有核心财务指标，并提供清晰的会计科目，
    如净资产、总资产、多空市值等。
    """
    def __init__(self, initial_cash: float):
        self.initial_cash: float = initial_cash
        self.cash: float = initial_cash
        self.margin: float = 0.0
        
        # --- 核心会计指标 ---
        self.net_worth: float = initial_cash      # 净资产
        self.net_positions_value: float = 0.0   # 净持仓市值
        self.long_positions_value: float = 0.0  # 多头市值
        self.short_positions_value: float = 0.0 # 空头市值（负债，以正数计）
        self.total_assets: float = initial_cash   # 总资产

        self.history: List[Dict[str, Any]] = []

    @property
    def available_cash(self) -> float:
        """计算并返回当前账户的可用资金 (总现金 - 保证金)。"""
        return self.cash - self.margin

    def update_financials(self, position_manager: 'PositionManager'):
        """
        根据当前所有持仓，全面更新账户的所有财务指标。

        这是账户状态更新的核心方法，应在任何持仓或现金变动后调用。
        """
        all_positions = position_manager.get_all_positions()
        
        # 1. 更新保证金
        self.margin = sum(pos.margin for pos in all_positions)
        
        # 2. 分别计算多头和空头市值
        self.long_positions_value = sum(
            pos.market_value for pos in all_positions 
            if pos.direction == PositionDirection.LONG
        )
        # 空头市值作为负债，其绝对值被累加
        self.short_positions_value = sum(
            abs(pos.market_value) for pos in all_positions 
            if pos.direction == PositionDirection.SHORT
        )
        
        # 3. 计算净持仓市值和总资产
        self.net_positions_value = self.long_positions_value - self.short_positions_value
        self.total_assets = self.cash + self.long_positions_value

        # 4. 计算净资产 (核心)
        self.net_worth = self.cash + self.net_positions_value
    
    def record_history(self, dt: datetime, position_manager: 'PositionManager'):
        """
        在每日结算时，全面更新财务指标并记录当日的账户净值快照。
        """
        # 在记录前，确保所有财务数据是基于最新持仓计算的
        self.update_financials(position_manager)
        
        self.history.append({
            'date': dt.strftime('%Y-%m-%d'),
            'net_worth': self.net_worth,
            'total_assets': self.total_assets,
            'cash': self.cash,
            'margin': self.margin,
            'available_cash': self.available_cash,
            'long_positions_value': self.long_positions_value,
            'short_positions_value': self.short_positions_value,
            'net_positions_value': self.net_positions_value,
            'returns': self.returns,
        })

    @property
    def returns(self) -> float:
        """计算并返回当前投资组合基于净资产的累计收益率。"""
        if self.initial_cash == 0:
            return 0.0
        return (self.net_worth - self.initial_cash) / self.initial_cash

    @property
    def long_market_value(self) -> float:
        """返回当前所有多头持仓的总市值。"""
        return self.long_positions_value

    @property
    def short_liability(self) -> float:
        """返回当前所有空头持仓的总负债（市值绝对值）。"""
        return self.short_positions_value
