# qtrader/utils/serializer.py

import pickle
import os
from datetime import datetime
from typing import Optional
from ..core.context import Context
from ..trading.position import PositionDirection

class StateSerializer:
    """
    状态序列化器，负责将策略的完整运行状态保存到文件或从文件加载。

    这使得回测或模拟交易可以被暂停、恢复或分叉。保存的状态包括：
    - 上下文（Context）的核心信息
    - 投资组合（Portfolio）
    - 当前持仓（Positions）和每日快照
    - 所有订单（Orders）
    - 基准历史（Benchmark history）
    - 用户自定义数据（user_data）
    """
    
    def __init__(self, context: Context, save_dir: str = '.states'):
        """
        Args:
            context: 全局上下文
            save_dir: 状态保存目录
        """
        self.context = context
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)
    
    def save(self, tag: Optional[str] = None):
        """
        保存当前的完整运行状态到 .pkl 文件。

        在保存前，它会动态生成当日的实时持仓快照，以确保状态的完整性。

        Args:
            tag (Optional[str]): 用于文件名后缀的标签。如果未提供，则使用当前日期。
        """
        if tag is None:
            tag = self.context.current_dt.strftime('%Y%m%d')

        file_path = os.path.join(
            self.save_dir,
            f"{self.context.strategy_name}_{tag}.pkl"
        )
        
        # --- 动态生成并合并当日持仓快照 ---
        # 这样做是为了确保即使在盘中保存状态，也能捕获到最新的持仓情况。
        position_snapshots = self.context.position_manager.daily_snapshots.copy() or []
        settle_time_str = self.context.config.get('lifecycle', {}).get('hooks', {}).get(
            'broker_settle', '15:30:00'
        )
        settle_time = datetime.strptime(settle_time_str, "%H:%M:%S").time()
        current_dt = self.context.current_dt

        # 检查是否在盘中（结算时间之前），如果是，则生成实时快照
        if current_dt and current_dt.time() < settle_time:
            live_positions = []
            date_str = current_dt.strftime('%Y-%m-%d')
            
            for pos in self.context.position_manager.get_all_positions():
                if pos.total_amount == 0:
                    continue
                
                price_data = self.context.data_provider.get_current_price(pos.symbol, current_dt)
                current_price = (price_data['current_price']
                                 if (price_data and price_data.get('current_price'))
                                 else pos.current_price)
                
                direction_multiplier = 1 if pos.direction == PositionDirection.LONG else -1
                daily_pnl = (current_price - pos.last_settle_price) * pos.total_amount * direction_multiplier
                base_value = abs(pos.last_settle_price * pos.total_amount)
                daily_pnl_ratio = (daily_pnl / base_value) if base_value > 0 else 0.0

                live_positions.append({
                    "date": date_str,
                    "symbol": pos.symbol,
                    "symbol_name": pos.symbol_name,
                    "direction": pos.direction.value,
                    "amount": pos.total_amount,
                    "close_price": current_price,
                    # [重构] 修正市值计算，确保空头仓位市值为负
                    "market_value": (pos.total_amount * current_price) * direction_multiplier,
                    "daily_pnl": daily_pnl,
                    "daily_pnl_ratio": daily_pnl_ratio
                })
            
            if live_positions:
                # 移除今天可能已存在的旧快照，以实时快照为准
                position_snapshots = [s for s in position_snapshots if s.get('date') != date_str]
                position_snapshots.append({"date": date_str, "positions": live_positions})
        
        self.context.position_manager.daily_snapshots = position_snapshots
        
        # 兼容 MockDateTime：将可能的 MockDateTime 对象转换为标准 datetime
        current_dt_to_save = self.context.current_dt
        if current_dt_to_save and 'MockDateTime' in str(type(current_dt_to_save)):
            current_dt_to_save = datetime(
                year=current_dt_to_save.year,
                month=current_dt_to_save.month,
                day=current_dt_to_save.day,
                hour=current_dt_to_save.hour,
                minute=current_dt_to_save.minute,
                second=current_dt_to_save.second,
                microsecond=current_dt_to_save.microsecond,
                tzinfo=getattr(current_dt_to_save, 'tzinfo', None)
            )

        # --- 收集所有需要序列化的状态数据 ---
        state = {
            'context': {
                'mode': self.context.mode,
                'strategy_name': self.context.strategy_name,
                'start_date': self.context.start_date,
                'end_date': self.context.end_date,
                'current_dt': current_dt_to_save or self.context.current_dt,
                'frequency': self.context.frequency,
                'frequency_options': self.context.frequency_options,
                'config': self.context.config,
                'intraday_equity_history': self.context.intraday_equity_history,
                'intraday_benchmark_history': self.context.intraday_benchmark_history,
                'was_interrupted': self.context.was_interrupted,
                'is_running': self.context.is_running,
                'scheduler_state_machine': self.context.scheduler_state_machine,
                'custom_schedule_points': self.context.custom_schedule_points,
            },
            'portfolio': self.context.portfolio,
            'positions': self.context.position_manager.get_all_positions(),
            'position_snapshots': position_snapshots,
            'orders': self.context.order_manager.get_all_orders(),
            'benchmark_history': self.context.benchmark_manager.benchmark_history,
            'benchmark_symbol': self.context.benchmark_manager.benchmark_symbol,
            'benchmark_name': self.context.benchmark_manager.benchmark_name,
            'benchmark_initial_value': self.context.benchmark_manager.initial_value,
            'user_data': self.context.user_data,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(file_path, 'wb') as f:
            pickle.dump(state, f)
        
        self.context.logger.info(f"状态已保存到 {file_path}")
    
    def load(self, file_path: str):
        """
        从 .pkl 文件加载运行状态，并恢复到当前 `Context` 对象。

        Args:
            file_path (str): 状态文件的路径。
        """
        with open(file_path, 'rb') as f:
            state = pickle.load(f)
        
        # --- 恢复 Context ---
        context_data = state['context']
        self.context.mode = context_data['mode']
        self.context.strategy_name = context_data['strategy_name']
        self.context.start_date = context_data['start_date']
        self.context.end_date = context_data['end_date']
        self.context.current_dt = context_data['current_dt']
        self.context.frequency = context_data['frequency']
        self.context.frequency_options = context_data.get('frequency_options', {})
        self.context.config = context_data['config']
        
        # --- 恢复 Portfolio ---
        self.context.portfolio = state['portfolio']
        
        # --- 恢复 Positions ---
        self.context.position_manager.restore_positions(state['positions'])
        self.context.position_manager.restore_daily_snapshots(state.get('position_snapshots', []))
        
        # --- 恢复 Orders ---
        self.context.order_manager.restore_orders(state['orders'])
        
        # --- 恢复 Benchmark ---
        self.context.benchmark_manager.benchmark_history = state['benchmark_history']
        
        # --- 恢复 user_data ---
        self.context.user_data = state['user_data']
        
        self.context.logger.info(f"状态已从 {file_path} 加载")
        self.context.logger.info(f"保存时间: {state['timestamp']}")