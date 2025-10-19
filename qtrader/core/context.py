# qtrader/core/context.py

from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import logging

# 避免循环导入的类型提示
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..trading.account import Portfolio
    from ..trading.order_manager import OrderManager
    from ..trading.position_manager import PositionManager
    from ..benchmark.benchmark_manager import BenchmarkManager
    from ..analysis.integrated_server import IntegratedServer
    from ..data.interface import AbstractDataProvider
    from .engine import Engine

@dataclass
class Context:
    """
    全局上下文（Context）对象，作为框架内所有组件共享信息和状态的中央总线。

    它包含了策略运行所需的所有信息，例如时间、账户、订单、持仓、配置等，
    并贯穿于整个回测或交易的生命周期。
    """

    # --- 基础运行信息 ---
    mode: str = 'backtest'
    strategy_name: str = 'UnnamedStrategy'
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    current_dt: Optional[datetime] = None
    market_phase: str = 'CLOSED'  # 由 Scheduler 更新 (e.g., 'TRADING', 'CLOSED')

    # --- 频率设置 ---
    frequency: str = 'daily'
    frequency_options: Dict[str, Any] = field(default_factory=dict)

    # --- 核心管理器 ---
    portfolio: Optional['Portfolio'] = None
    order_manager: Optional['OrderManager'] = None
    position_manager: Optional['PositionManager'] = None
    benchmark_manager: Optional['BenchmarkManager'] = None
    engine: Optional['Engine'] = None  # 对主引擎 Engine 的引用，用于组件间的通信。

    # --- 配置与数据 ---
    config: Dict[str, Any] = field(default_factory=dict)
    user_data: Dict[str, Any] = field(default_factory=dict)

    # --- 运行状态 ---
    is_running: bool = False
    is_paused: bool = False
    is_initializing: bool = False # 标记是否处于策略初始化阶段
    start_paused: bool = False  # 标记是否在启动时立即暂停
    was_interrupted: bool = False
    pause_requested: bool = False
    stop_requested: bool = False
    resync_requested: bool = False  # 时间同步请求标志，用于处理生命周期中的阻塞。
    strategy_error_today: bool = False  # 标记当日策略是否发生运行时错误。
    scheduler_state_machine: Dict[str, Any] = None
    _initial_state_set: bool = False # 标记 set_initial_state 是否已被调用
    
    # --- 策略自定义扩展 ---
    custom_schedule_points: List[str] = field(default_factory=list)


    # --- 外部服务与数据接口 ---
    visualization_server: Optional['IntegratedServer'] = None
    logger: Optional[logging.Logger] = None
    data_provider: Optional['AbstractDataProvider'] = None

    # --- 缓存与历史数据 ---
    symbol_info_cache: Dict[str, Any] = field(default_factory=dict)
    intraday_equity_history: List[Dict[str, Any]] = field(default_factory=list)
    intraday_benchmark_history: List[Dict[str, Any]] = field(default_factory=list)
    log_buffer: List[Dict[str, Any]] = field(default_factory=list)
    log_buffer_limit: int = 1000

    def __post_init__(self):
        """
        在对象初始化后，根据传入的 config 字典来设置 Context 的核心属性。
        这使得 Context 能够自我配置，而不是依赖外部代码（如 Engine）来设置。
        """
        engine_config = self.config.get('engine', {})
        self.mode = engine_config.get('mode', self.mode)
        self.strategy_name = engine_config.get('strategy_name', self.strategy_name)
        self.start_date = engine_config.get('start_date', self.start_date)
        self.end_date = engine_config.get('end_date', self.end_date)
        self.frequency = engine_config.get('frequency', self.frequency)
        self.frequency_options = engine_config.get('frequency_options', self.frequency_options)

    def add_schedule(self, time_str: str):
        """
        在策略的 initialize() 阶段，添加一个自定义的 handle_bar 调用时间点。

        Args:
            time_str (str): 一个 "HH:MM:SS" 格式的时间字符串。
        """
        if not self.is_initializing:
            raise RuntimeError("add_schedule() 只能在策略的 initialize() 方法中调用。")
        
        try:
            # 验证时间格式是否正确
            datetime.strptime(time_str, '%H:%M:%S')
        except ValueError:
            raise ValueError(f"无效的时间格式: '{time_str}'。请使用 'HH:MM:SS' 格式。")
        
        if time_str not in self.custom_schedule_points:
            self.custom_schedule_points.append(time_str)
            if self.logger:
                self.logger.info(f"添加自定义调度时间点: {time_str}")

    def set(self, key: str, value: Any):
        """
        在 user_data 字典中存储用户自定义数据。
        这是为了兼容旧版API，方便策略编写者使用 context.set(key, value)。
        """
        self.user_data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        从 user_data 字典中获取用户自定义数据。
        这是为了兼容旧版API，方便策略编写者使用 context.get(key, default_value)。
        """
        return self.user_data.get(key, default)

    def set_initial_state(self, cash: float = 0.0, positions: List[Dict[str, Any]] = []):
        """
        在策略的 initialize() 阶段，设置账户的初始状态。此方法只能被调用一次。

        Args:
            cash (float): 初始的可用现金。
            positions (List[Dict[str, Any]]): 初始持仓列表。每个持仓是一个字典，
                必须包含 'symbol' 和 'amount'。
                - 'amount' (int): 持仓数量。正数表示多头，负数表示空头。
                可选字段:
                - 'avg_cost' (float): 持仓成本。如果未提供，将从数据源获取当前价。
                - 'symbol_name' (str): 证券名称。如果未提供，将自动获取。
        """
        if not self.is_initializing:
            raise RuntimeError("set_initial_state() 只能在策略的 initialize() 方法中调用。")
        if self._initial_state_set:
            raise RuntimeError("set_initial_state() 只能被调用一次，以防止重复设置或修改初始状态。")

        if self.portfolio is None or self.position_manager is None or self.data_provider is None:
            raise RuntimeError("核心组件 (Portfolio, PositionManager, DataProvider) 尚未初始化。")

        self.portfolio.cash = cash
        from ..trading.position import PositionDirection

        for pos_data in positions:
            symbol = pos_data.get('symbol')
            amount = pos_data.get('amount')
            if not symbol or amount is None:
                raise ValueError("每个持仓必须包含 'symbol' 和 'amount'。")
            if amount == 0:
                continue

            direction = PositionDirection.LONG if amount > 0 else PositionDirection.SHORT
            abs_amount = abs(amount)

            avg_cost = pos_data.get('avg_cost')
            if avg_cost is None:
                price_info = self.data_provider.get_current_price(symbol, self.current_dt)
                if not price_info or 'current_price' not in price_info:
                    raise RuntimeError(f"无法获取 {symbol} 的当前价格作为默认成本。")
                avg_cost = price_info['current_price']

            symbol_name = pos_data.get('symbol_name')
            if symbol_name is None:
                info = self.data_provider.get_symbol_info(symbol, self.current_dt.strftime('%Y-%m-%d'))
                symbol_name = info.get('symbol_name', symbol) if info else symbol

            self.position_manager.adjust_position(
                symbol=symbol,
                amount=abs_amount,
                avg_cost=avg_cost,
                symbol_name=symbol_name,
                direction=direction
            )

        # [重构] 全面更新账户财务指标，并正确计算初始净资产
        self.portfolio.update_financials(self.position_manager)
        self.portfolio.initial_cash = self.portfolio.net_worth # 初始净资产等于此刻的净值

        # 生成详细的日志摘要
        all_positions = self.position_manager.get_all_positions()
        log_message = f"初始状态设置完成:\n"
        log_message += f"  - 初始可用现金: {self.portfolio.cash:.2f}\n"
        log_message += f"  - 初始持仓 ({len(all_positions)} 个):\n"
        if not all_positions:
            log_message += "    - (无)\n"
        else:
            for pos in all_positions:
                display_amount = pos.total_amount if pos.direction == PositionDirection.LONG else -pos.total_amount
                log_message += (
                    f"    - {pos.symbol_name}({pos.symbol}): "
                    f"数量={display_amount}, "
                    f"方向={pos.direction.value}, "
                    f"成本={pos.avg_cost:.2f}\n"
                )
        log_message += f"  - 账户摘要:\n"
        log_message += f"    - 账户净资产: {self.portfolio.net_worth:,.2f}\n"
        log_message += f"    - 可用现金: {self.portfolio.available_cash:,.2f}\n"
        log_message += f"    - 占用保证金: {self.portfolio.margin:,.2f}"

        self.logger.info(log_message)
        self._initial_state_set = True

    def align_account_state(self, cash: float, positions: List[Dict[str, Any]]):
        """
        在 broker_settle() 阶段，将系统内的账户状态与外部实际状态对齐。

        Args:
            cash (float): 对齐后的目标可用现金。
            positions (List[Dict[str, Any]]): 对齐后的目标持仓列表。
                格式与 set_initial_state 中的 positions 参数相同。
        """
        if self.market_phase == 'TRADING':
            raise RuntimeError("align_account_state() 不能在交易时段内调用。")

        if self.portfolio is None or self.position_manager is None:
            raise RuntimeError("核心组件 (Portfolio, PositionManager) 尚未初始化。")

        from ..trading.position import PositionDirection
        
        # 1. 现金对齐
        original_cash = self.portfolio.cash
        self.portfolio.cash = cash
        
        # 2. 持仓对齐
        # 将目标持仓转换为易于查找的字典
        target_positions = {}
        for pos_data in positions:
            symbol = pos_data.get('symbol')
            amount = pos_data.get('amount')
            if not symbol or amount is None:
                raise ValueError("每个持仓必须包含 'symbol' 和 'amount'。")
            
            direction = PositionDirection.LONG if amount > 0 else PositionDirection.SHORT
            key = f"{symbol}::{direction.value}"
            target_positions[key] = pos_data

        # 获取当前持仓
        current_positions = {
            f"{pos.symbol}::{pos.direction.value}": pos
            for pos in self.position_manager.get_all_positions()
        }
        
        all_keys = set(target_positions.keys()) | set(current_positions.keys())
        
        for key in all_keys:
            target_pos_data = target_positions.get(key)
            current_pos_obj = current_positions.get(key)
            
            target_amount = target_pos_data.get('amount', 0) if target_pos_data else 0
            
            # 如果目标数量为0，则意味着需要平仓
            if target_amount == 0:
                if current_pos_obj:
                    self.position_manager.adjust_position(
                        symbol=current_pos_obj.symbol,
                        amount=0,
                        avg_cost=0,
                        direction=current_pos_obj.direction
                    )
                continue

            # 处理新增或更新
            direction = PositionDirection.LONG if target_amount > 0 else PositionDirection.SHORT
            abs_amount = abs(target_amount)
            avg_cost = target_pos_data.get('avg_cost')
            symbol = target_pos_data.get('symbol')
            symbol_name = target_pos_data.get('symbol_name')

            self.position_manager.adjust_position(
                symbol=symbol,
                amount=abs_amount,
                avg_cost=avg_cost,
                symbol_name=symbol_name,
                direction=direction
            )

        # 3. [重构] 更新账户状态并记录日志
        self.portfolio.update_financials(self.position_manager)
        
        all_final_positions = self.position_manager.get_all_positions()

        log_message = f"账户状态对齐完成:\n"
        log_message += f"  - 现金: {original_cash:.2f} -> {self.portfolio.cash:.2f}\n"
        log_message += f"  - 对齐后持仓 ({len(all_final_positions)} 个):\n"
        if not all_final_positions:
            log_message += "    - (无)\n"
        else:
            for pos in all_final_positions:
                display_amount = pos.total_amount if pos.direction == PositionDirection.LONG else -pos.total_amount
                log_message += (
                    f"    - {pos.symbol_name}({pos.symbol}): "
                    f"数量={display_amount}, 成本={pos.avg_cost:.2f}\n"
                )
        log_message += f"  - 对齐后账户摘要:\n"
        log_message += f"    - 账户净资产: {self.portfolio.net_worth:,.2f}\n"
        log_message += f"    - 可用现金: {self.portfolio.available_cash:,.2f}\n"
        log_message += f"    - 占用保证金: {self.portfolio.margin:,.2f}"
        
        self.logger.info(log_message)