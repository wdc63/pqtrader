# qtrader/analysis/performance.py

from collections import defaultdict, deque
from typing import Dict, Any, List
import pandas as pd
import numpy as np
from ..core.context import Context
from ..trading.order import OrderSide

class PerformanceAnalyzer:
    """
    分析交易性能，基于FIFO（先进先出）原则配对平仓与开仓订单，
    计算各项关键性能指标，如盈亏、胜率、利润因子等。
    """
    def __init__(self, context: Context):
        self.context = context
        self.pnl_df = self._calculate_pnl()

    def _calculate_pnl(self) -> pd.DataFrame:
        """
        根据已成交订单，基于FIFO原则计算逐笔交易的盈亏。

        Returns:
            pd.DataFrame: 包含每笔配对交易详细信息的DataFrame。
        """
        filled_orders = sorted(
            self.context.order_manager.get_all_orders_history(),
            key=lambda o: o.filled_time
        )
        
        long_entries: Dict[str, deque] = defaultdict(deque)
        short_entries: Dict[str, deque] = defaultdict(deque)
        trade_pairs = []
        
        for order in filled_orders:
            symbol = order.symbol
            
            if order.side == OrderSide.BUY:
                remaining = order.amount
                queue = short_entries[symbol]
                
                # 平空仓
                while remaining > 0 and queue:
                    short_entry = queue[0]
                    trade_amount = min(short_entry["remaining"], remaining)
                    
                    # 按比例计算本次平仓部分对应的开仓和平仓手续费
                    entry_commission = (short_entry["order"].commission *
                                        (trade_amount / short_entry["order"].amount))
                    exit_commission = order.commission * (trade_amount / order.amount)
                    total_commission = entry_commission + exit_commission
                    
                    # 计算毛利润（不含手续费）
                    gross_pnl = (short_entry["order"].filled_price - order.filled_price) * trade_amount
                    net_pnl = gross_pnl - total_commission
                    
                    trade_pairs.append({
                        "symbol": symbol,
                        "symbol_name": order.symbol_name or short_entry["order"].symbol_name,
                        "direction": "short",
                        "entry_time": short_entry["order"].filled_time,
                        "exit_time": order.filled_time,
                        "entry_price": short_entry["order"].filled_price,
                        "exit_price": order.filled_price,
                        "amount": trade_amount,
                        "total_commission": total_commission,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl
                    })
                    
                    remaining -= trade_amount
                    short_entry["remaining"] -= trade_amount
                    if short_entry["remaining"] == 0:
                        queue.popleft()
                
                # 开多仓
                if remaining > 0:
                    long_entries[symbol].append({"order": order, "remaining": remaining})
            
            else:  # SELL
                remaining = order.amount
                queue = long_entries[symbol]
                
                # 平多仓
                while remaining > 0 and queue:
                    long_entry = queue[0]
                    trade_amount = min(long_entry["remaining"], remaining)
                    
                    # 按比例计算本次平仓部分对应的开仓和平仓手续费
                    entry_commission = (long_entry["order"].commission *
                                        (trade_amount / long_entry["order"].amount))
                    exit_commission = order.commission * (trade_amount / order.amount)
                    total_commission = entry_commission + exit_commission

                    # 计算毛利润（不含手续费）
                    gross_pnl = (order.filled_price - long_entry["order"].filled_price) * trade_amount
                    net_pnl = gross_pnl - total_commission

                    trade_pairs.append({
                        "symbol": symbol,
                        "symbol_name": order.symbol_name or long_entry["order"].symbol_name,
                        "direction": "long",
                        "entry_time": long_entry["order"].filled_time,
                        "exit_time": order.filled_time,
                        "entry_price": long_entry["order"].filled_price,
                        "exit_price": order.filled_price,
                        "amount": trade_amount,
                        "total_commission": total_commission,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl
                    })
                    
                    remaining -= trade_amount
                    long_entry["remaining"] -= trade_amount
                    if long_entry["remaining"] == 0:
                        queue.popleft()

                # 开空仓
                if remaining > 0:
                    short_entries[symbol].append({"order": order, "remaining": remaining})
        
        if not trade_pairs:
            return pd.DataFrame()
        
        df = pd.DataFrame(trade_pairs)
        
        # 计算盈亏率（基于净利润）
        df['net_pnl_ratio'] = np.where(
            df['entry_price'] * df['amount'] != 0,
            df['net_pnl'] / (df['entry_price'] * df['amount']),
            0.0
        )
        
        # 计算持仓天数
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['hold_days'] = (df['exit_time'].dt.normalize() -
                           df['entry_time'].dt.normalize()).dt.days
        
        return df

    @property
    def summary(self) -> List[Dict[str, Any]]:
        """
        生成交易性能指标的摘要。

        如果没有任何交易记录，则返回包含默认值的指标。

        Returns:
            List[Dict[str, Any]]: 包含各项性能指标的列表。
        """
        # 当没有交易记录时，为所有指标设置默认值
        if self.pnl_df.empty:
            net_profit = 0.0
            gross_profit = 0.0
            gross_loss = 0.0
            total_commission = 0.0
            total_trades = 0
            winning_trades_count = 0
            losing_trades_count = 0
            win_rate = 0.0
            profit_factor = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            win_loss_ratio = 0.0
            max_win_val = 0.0
            max_loss_val = 0.0
            avg_hold_days = 0.0
        else:
            pnl = self.pnl_df
            total_trades = len(pnl)
            
            winning_trades = pnl[pnl['net_pnl'] > 0]
            losing_trades = pnl[pnl['net_pnl'] < 0]
            winning_trades_count = len(winning_trades)
            losing_trades_count = len(losing_trades)

            net_profit = pnl['net_pnl'].sum()
            gross_profit = winning_trades['net_pnl'].sum()
            gross_loss = abs(losing_trades['net_pnl'].sum())
            total_commission = pnl['total_commission'].sum()
            
            win_rate = winning_trades_count / total_trades if total_trades > 0 else 0
            # 利润因子 = 总盈利 / 总亏损
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
            
            avg_win = winning_trades['net_pnl'].mean() if winning_trades_count > 0 else 0
            avg_loss = abs(losing_trades['net_pnl'].mean()) if losing_trades_count > 0 else 0
            # 盈亏比 = 平均盈利 / 平均亏损
            win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else np.inf
            
            max_win_val = pnl['net_pnl'].max()
            max_loss_val = pnl['net_pnl'].min()
            
            avg_hold_days = pnl['hold_days'].mean()

        # 统一返回结构
        metrics = [
            {"key": "净利润", "value": f"{net_profit:,.2f}",
             "raw": 0 if self._is_nan_inf(net_profit) else net_profit},
            {"key": "总盈利", "value": f"{gross_profit:,.2f}",
             "raw": 0 if self._is_nan_inf(gross_profit) else gross_profit},
            {"key": "总亏损", "value": f"{gross_loss:,.2f}",
             "raw": 0 if self._is_nan_inf(gross_loss) else -gross_loss},
            {"key": "总手续费", "value": f"{total_commission:,.2f}",
             "raw": 0 if self._is_nan_inf(total_commission) else -total_commission},
            {"key": "利润因子", "value": f"{profit_factor:.2f}" if np.isfinite(profit_factor) else "N/A",
             "raw": 0 if self._is_nan_inf(profit_factor) else profit_factor},
            {"key": "总交易次数", "value": str(total_trades),
             "raw": 0 if self._is_nan_inf(total_trades) else total_trades},
            {"key": "盈利次数", "value": str(winning_trades_count),
             "raw": 0 if self._is_nan_inf(winning_trades_count) else winning_trades_count},
            {"key": "亏损次数", "value": str(losing_trades_count),
             "raw": 0 if self._is_nan_inf(losing_trades_count) else -losing_trades_count},
            {"key": "胜率", "value": f"{win_rate:.2%}",
             "raw": 0 if self._is_nan_inf(win_rate) else win_rate},
            {"key": "平均盈利", "value": f"{avg_win:,.2f}",
             "raw": 0 if self._is_nan_inf(avg_win) else avg_win},
            {"key": "平均亏损", "value": f"{avg_loss:,.2f}",
             "raw": 0 if self._is_nan_inf(avg_loss) else -avg_loss},
            {"key": "盈亏比", "value": f"{win_loss_ratio:.2f}" if np.isfinite(win_loss_ratio) else "N/A",
             "raw": 0 if self._is_nan_inf(win_loss_ratio) else win_loss_ratio},
            {"key": "最大单笔盈利", "value": f"{max_win_val:,.2f}",
             "raw": 0 if self._is_nan_inf(max_win_val) else max_win_val},
            {"key": "最大单笔亏损", "value": f"{max_loss_val:,.2f}",
             "raw": 0 if self._is_nan_inf(max_loss_val) else max_loss_val},
            {"key": "平均持仓天数", "value": f"{avg_hold_days:.2f}",
             "raw": 0 if self._is_nan_inf(avg_hold_days) else avg_hold_days}
        ]

        return metrics

    def _is_nan_inf(self, value):
        """检查一个值是否为 NaN (Not a Number) 或无穷大。"""
        return np.isnan(value) or np.isinf(value)