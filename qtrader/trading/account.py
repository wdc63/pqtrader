# qtrader/trading/account.py

from typing import List, Dict, Any, TYPE_CHECKING
from datetime import datetime
from .position_manager import PositionManager


class Portfolio:
    """
    投资组合（账户）对象，系统的核心财务状态机。

    本类负责跟踪和管理账户的所有核心财务指标。它不直接处理交易逻辑，
    而是作为一个被动的状态容器，由 `MatchingEngine` 在交易发生或每日
    结算时进行更新。

    核心属性:
    - `initial_cash`: 初始本金，用于计算累计收益率，一经设定不再改变。
    - `cash`: 当前可用现金。每次买入时减少，卖出时增加。
    - `total_value`: 总净值（现金 + 持仓市值），是衡量策略表现的主要指标。
    - `history`: 每日净值快照列表，用于生成性能报告和绘制资金曲线。
    """
    def __init__(self, initial_cash: float):
        """
        Args:
            initial_cash (float): 初始资金
        """
        self.initial_cash: float = initial_cash
        self.cash: float = initial_cash
        self.total_value: float = initial_cash
        self.margin: float = 0.0
        self.history: List[Dict[str, Any]] = []

    @property
    def available_cash(self) -> float:
        """
        计算并返回当前账户的可用资金。

        可用资金是指账户中可以用于开立新仓位或支付交易费用的现金部分。
        它的计算方式为：总现金 - 已占用保证金。
        对于涉及卖空或杠杆交易的策略，此指标尤为重要，因为它直接决定了
        策略的“火力”或可承担的风险敞口。
        """
        return self.cash - self.margin

    def update_margin(self, position_manager: 'PositionManager'):
        """
        根据当前所有持仓，重新计算并更新账户的总占用保证金。

        此方法应在任何可能影响保证金的操作（如开/平空仓）之后被调用，
        以确保 `available_cash` 的准确性。它会遍历所有持仓（特别是空头持仓），
        并累加它们各自占用的保证金。

        Args:
            position_manager (PositionManager): 持仓管理器实例，用于获取所有持仓。
        """
        self.margin = sum(pos.margin for pos in position_manager.get_all_positions())
    
    def record_history(self, dt: datetime, position_value: float):
        """
        在每日结算时记录当日的账户净值快照。

        此方法由 `MatchingEngine.settle()` 在计算完当日最终的持仓市值后调用。
        它会更新账户的总净值，并将当日的各项财务指标追加到 `history` 列表中，
        为最终的性能分析提供数据点。

        Args:
            dt (datetime): 当前结算的日期时间戳。
            position_value (float): 由 `PositionManager` 计算得出的、当日收盘时
                                    所有持仓的总市值。
        """
        self.total_value = self.cash + position_value
        self.history.append({
            'date': dt.strftime('%Y-%m-%d'),
            'cash': self.cash,
            'position_value': position_value,
            'total_value': self.total_value,
            'margin': self.margin,
            'available_cash': self.available_cash,
            'returns': self.returns,
        })

    @property
    def returns(self) -> float:
        """计算并返回当前投资组合的累计收益率。"""
        if self.initial_cash == 0:
            return 0.0
        return (self.total_value - self.initial_cash) / self.initial_cash
