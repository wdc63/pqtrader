# qtrader/core/engine.py

import signal
import webbrowser
import os
import importlib.util
import sys
from pathlib import Path
import time
from datetime import datetime, timedelta, time as time_obj, date
from typing import Optional, Type, Dict, Any

from ..core.config import load_config
from ..core.context import Context
from ..core.workspace_manager import WorkspaceManager
from ..core.time_manager import TimeManager
from ..core.scheduler import Scheduler
from ..core.lifecycle import LifecycleManager
from ..strategy.base import Strategy
from ..data.interface import AbstractDataProvider
from ..trading.account import Portfolio
from ..trading.order_manager import OrderManager
from ..trading.position_manager import PositionManager
from ..trading.matching_engine import MatchingEngine
from ..benchmark.benchmark_manager import BenchmarkManager
from ..utils.logger import setup_logger
from ..utils.serializer import StateSerializer
from ..analysis.integrated_server import IntegratedServer
from ..trading.order import OrderStatus

class Engine:
    """
    QTrader 框架的核心引擎 (Core Engine)。

    作为框架的总协调官和执行器，Engine 负责管理整个回测或模拟交易的生命周期。
    它将所有独立的模块（如数据、策略、交易、风控、分析等）组装在一起，
    并驱动整个事件循环的执行。

    主要职责:
    1.  **配置加载与验证**:
        - 读取 YAML 配置文件，并校验关键字段的完整性。

    2.  **组件初始化与组装 (IoC/DI)**:
        - 根据运行模式（回测/模拟）和状态（全新/恢复/分叉），创建并初始化所有
          核心组件，如 `Context`, `Scheduler`, `Portfolio`, `OrderManager` 等。
        - 通过 `Context` 对象将这些组件互相解耦，实现依赖注入。

    3.  **生命周期管理**:
        - 提供 `run`, `resume`, `run_fork` 等统一入口，管理一个交易会话的
          启动、暂停、恢复和终止。
        - 驱动 `Scheduler` 运行主事件循环。
        - 在会话结束时，负责执行清理工作、状态持久化和报告生成。

    4.  **状态管理**:
        - 与 `StateSerializer` 协作，负责在暂停、中断或正常结束时保存系统
          的完整状态。
        - 在恢复或分叉时，精确地从状态文件中重建系统。

    5.  **环境设置**:
        - 管理工作区（Workspace），为每次运行创建独立的目录以存放日志、数据快照和报告。
        - 设置日志记录器。
        - 注册信号处理器以实现优雅退出 (Ctrl+C)。
    """
    
    def __init__(self, config_path: str):
        """
        初始化 Engine 实例。

        Args:
            config_path (str): 配置文件路径。
        """
        self.config = load_config(config_path)
        self.config_path = config_path
        
        self.context: Optional[Context] = None
        self.workspace_manager: Optional[WorkspaceManager] = None
        self.state_serializer: Optional[StateSerializer] = None
        self.scheduler: Optional[Scheduler] = None
        self.server: Optional[IntegratedServer] = None
        
        # 临时日志记录器
        import logging
        self.temp_logger = logging.getLogger("qtrader.engine")
        if not self.temp_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.temp_logger.addHandler(handler)
            self.temp_logger.setLevel(logging.INFO)
        self.temp_logger.propagate = False

    
    @classmethod
    def load_from_state(cls, state_file: str, config_path: Optional[str] = None):
        """
        通过加载状态文件来创建一个 Engine 实例，用于恢复或分叉运行。

        Args:
            state_file (str): 状态文件的路径。
            config_path (Optional[str]): 可选的配置文件路径，如果未提供，则尝试从工作区快照加载。

        Returns:
            Engine: 一个准备好恢复或分叉的 Engine 实例。
        """
        import pickle
        with open(state_file, 'rb') as f:
            state = pickle.load(f)
        
        if config_path is None:
            state_path = Path(state_file)
            workspace_dir = state_path.parent
            config_snapshot = workspace_dir / "snapshot_config.yaml"
            if config_snapshot.exists():
                config_path = str(config_snapshot)
            else:
                import tempfile
                import yaml
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    yaml.dump(state['context']['config'], f)
                    config_path = f.name
        
        engine = cls(config_path)
        engine._state_to_restore = state
        engine._state_file_path = state_file
        
        return engine
    
    def run(self, strategy: str, data_provider: str, start_paused: bool = False):
        """
        启动一个全新的回测或模拟交易。

        Args:
            strategy (str): 策略文件路径。
            data_provider (str): 数据提供者文件路径。
            start_paused (bool): 是否在启动后立即暂停。
        """
        mode = self.config.get('engine', {}).get('mode', 'backtest')
        if mode == 'simulation':
            self._run_simulation_unified(
                strategy_path=strategy,
                data_provider_path=data_provider,
                is_resume=False,
                start_paused=start_paused
            )
        else:
            self._run_backtest_new(
                strategy=strategy,
                data_provider=data_provider,
                start_paused=start_paused
            )
    
    def resume(self, data_provider_path: str = None, start_paused: bool = False):
        """
        从一个由“暂停”操作生成的状态文件恢复运行。

        Args:
            data_provider_path (str, optional): 新的数据提供者路径，如果提供则替换旧的。
            start_paused (bool): 是否在恢复后立即暂停。
        """
        if not hasattr(self, '_state_to_restore'):
            raise RuntimeError("无法恢复：未从状态文件加载引擎。")
        
        state_context = self._state_to_restore.get('context', {})
        mode = self.config.get('engine', {}).get('mode', state_context.get('mode', 'backtest'))
        
        if mode == 'simulation':
            self._run_simulation_unified(
                strategy_path=None,
                data_provider_path=data_provider_path,
                is_resume=True,
                start_paused=start_paused
            )
        else:
            self._run_backtest_resume(data_provider_path, start_paused=start_paused)

    def run_fork(self, strategy_path: str = None, data_provider_path: str = None, reinitialize: bool = True, start_paused: bool = False):
        """
        从一个暂停状态文件分叉出一个新的运行实例。

        这允许在回测的某个时间点上，用新的策略、数据或配置继续运行，
        同时保留历史账户和持仓状态。

        Args:
            strategy_path (str, optional): 新的策略文件路径。
            data_provider_path (str, optional): 新的数据提供者路径。
            reinitialize (bool): 是否在新策略中调用 `initialize()` 方法。
            start_paused (bool): 是否在分叉后立即暂停。
        """
        if not hasattr(self, '_state_to_restore'):
            raise RuntimeError("无法恢复：未从状态文件加载引擎。")
        
        state_context = self._state_to_restore.get('context', {})
        mode = self.config.get('engine', {}).get('mode', state_context.get('mode', 'backtest'))
        
        if mode == 'simulation':
            self._run_simulation_unified(
                strategy_path=strategy_path,
                data_provider_path=data_provider_path,
                is_resume=True,
                start_paused=start_paused
            )
        else:
            self._run_from_snapshot(
                strategy=strategy_path,
                data_provider=data_provider_path,
                reinitialize=reinitialize,
                start_paused=start_paused
            )

    def _run_backtest_new(self, strategy: str, data_provider: str, start_paused: bool = False):
        """
        执行一个全新的回测流程。
        
        此方法负责从零开始设置回测环境，包括创建工作区、加载用户代码、
        初始化所有交易组件，并最终启动事件循环。
        """
        self.temp_logger.info("=" * 60)
        self.temp_logger.info("QTrader - 启动全新回测")
        self.temp_logger.info("=" * 60)
        
        # --- 1. 加载数据提供者 ---
        # 这是第一步，因为后续的工作区和组件初始化可能需要数据接口。
        data_provider_instance = self._load_data_provider(data_provider)

        # --- 2. 初始化工作区和上下文 ---
        # Context 是所有模块共享的“全局”状态容器。
        self.context = Context(config=self.config)
        # 指定Context的引擎
        self.context.engine = self
        # WorkspaceManager 负责创建本次回测的独立目录，用于存放日志、快照和报告。
        self.workspace_manager = WorkspaceManager(
            strategy_path=strategy,
            data_provider_path=data_provider,
            config=self.config,
            logger=self.temp_logger,
            mode=self.context.mode
        )
        
        # --- 3. 设置正式日志记录器 ---
        # 将日志输出重定向到工作区内的日志文件。
        log_config = self.config.get('logging', {})
        log_config['file'] = str(self.workspace_manager.log_file)
        self.context.logger = setup_logger(log_config, self.context)
        self.workspace_manager.logger = self.context.logger
        
        # --- 4. 加载策略并注册组件 ---
        strategy_class = self._load_strategy_class(strategy)
        self.context.strategy_name = self.config.get('engine', {}).get('strategy_name', strategy_class.__name__)
        
        self.context.data_provider = data_provider_instance
        self.context.logger.info(f"数据提供者 {type(data_provider_instance).__name__} 已注册")
        
        # --- 5. 初始化核心交易组件 ---
        # 创建 Portfolio, OrderManager, Scheduler 等。
        self._initialize_components(strategy_class)
        
        # --- 6. 初始化历史数据起点 ---
        # 为净值曲线和基准添加一个 "第0天" 的数据点，以便计算第一天的收益率。
        self._initialize_history()
        
        # --- 7. 启动可选服务和信号处理 ---
        self._start_server_if_enabled()
        self._register_signal_handlers()
        
        # --- 8. 准备启动 ---
        if start_paused:
            self.context.start_paused = True

        # --- 9. 移交控制权给主循环 ---
        self._execute_main_loop()

    def _run_backtest_resume(self, data_provider: str = None, start_paused: bool = False):
        """
        从一个由“暂停”操作生成的状态文件恢复回测。
        
        此方法重建了回测暂停时的完整状态，并从中断点继续执行。
        它会严格检查状态文件的有效性，确保只能从可恢复的暂停点（而不是
        终结点或中断点）继续。
        """
        # --- 1. 验证状态文件的可恢复性 ---
        state = self._state_to_restore
        state_context = state.get('context', {})
        if not state_context.get('is_running', False):
            state_file_path_str = getattr(self, '_state_file_path', 'Unknown file')
            was_interrupted = state_context.get('was_interrupted', False)
            reason = "回测被强制中断时生成的" if was_interrupted else "回测正常结束后生成的"
            
            raise RuntimeError(
                f"操作被禁止：不允许从一个终结状态文件 ({state_file_path_str}) 恢复回测。\n"
                f"原因：该状态是[{reason}]，并非由'暂停'(Pause)操作创建的可恢复状态。\n"
                f"终结状态文件仅用于生成报告和事后分析。"
            )
        
        self.temp_logger.info("=" * 60)
        self.temp_logger.info("QTrader - 恢复中断的回测")
        self.temp_logger.info("=" * 60)

        # --- 2. 确定工作区并设置上下文和日志 ---
        state_path = Path(self._state_file_path)
        workspace_dir = state_path.parent
        
        self.context = Context(config=self.config)
        log_config = self.config.get('logging', {})
        log_config['file'] = str(workspace_dir / "backtest.log")
        self.context.logger = setup_logger(log_config, self.context)
        
        # --- 3. 从状态字典中恢复核心组件 ---
        # 这是恢复过程的核心，它会重建 Portfolio, OrderManager, PositionManager 等的状态。
        self._restore_components_from_state(state)
        
        # --- 4. 加载代码快照和数据提供者 ---
        # 恢复时，总是使用工作区中的代码快照，以保证一致性。
        strategy_snapshot = workspace_dir / "snapshot_code.py"
        if not strategy_snapshot.exists():
            raise FileNotFoundError(f"策略快照不存在: {strategy_snapshot}")
        strategy_class= self._load_strategy_class(str(strategy_snapshot))
        
        # 用户可以选择提供一个新的数据提供者，否则使用快照。
        if not data_provider:
            data_provider_path = workspace_dir / "snapshot_data_provider.py"
            if not data_provider_path.exists():
                raise FileNotFoundError(f"数据提供者不存在: {data_provider_path}")
            data_provider_instance = self._load_data_provider(str(data_provider_path))
        else:
            data_provider_instance = self._load_data_provider(data_provider)
        self.context.data_provider = data_provider_instance

        # --- 5. 重新初始化非状态组件 ---
        # WorkspaceManager, Scheduler 等不需要序列化的组件在这里被重新创建。
        self.workspace_manager = WorkspaceManager(strategy_path=str(strategy_snapshot),
                                    data_provider_path=str(data_provider or data_provider_path),
                                    config=self.config,
                                    logger=self.context.logger,
                                    mode=self.context.mode,
                                    workspace_dir_override=str(workspace_dir)
                                )
        
        matching_engine = MatchingEngine(self.context, self.config.get('matching', {}))
        time_manager = TimeManager(self.context)
        lifecycle_manager = LifecycleManager(self.context)
        strategy_instance = strategy_class()
        lifecycle_manager.register_strategy(strategy_instance)
        
        self.scheduler = Scheduler(self.context, time_manager, matching_engine, lifecycle_manager)
        
        self.state_serializer = StateSerializer(self.context, str(workspace_dir))
        self.context.state_serializer = self.state_serializer
        
        # --- 6. 启动服务并准备执行 ---
        self._start_server_if_enabled()
        self._register_signal_handlers()
        
        if start_paused:
            self.context.start_paused = True
            
        # --- 7. 移交控制权给主循环 ---
        # 恢复运行时，必须跳过 strategy.initialize() 的调用。
        self._execute_main_loop(skip_initialize=True)

    def _run_from_snapshot(
        self,
        strategy: str = None,
        data_provider: str = None,
        reinitialize: bool = True,
        start_paused: bool = False
    ):
        """
        从一个暂停状态文件分叉出一个新的回测实例。

        分叉（Fork）是一种强大的功能，它允许用户在回测的某个特定时间点“克隆”
        出一条新的时间线。用户可以保留该时间点之前的所有交易历史和持仓状态，
        但从该点开始，应用新的策略、新的数据或新的配置参数继续运行。

        这对于以下场景非常有用：
        - 测试不同参数对策略后期表现的影响。
        - 在特定市场条件下，对比不同策略的应对方式。
        - 对一个长周期回测的后半段进行精细化调整和研究。
        """
        # --- 1. 验证状态文件的可分叉性 ---
        if not hasattr(self, '_state_to_restore'):
            raise RuntimeError("无法分叉：未从状态文件加载引擎。请使用 Engine.load_from_state()")
        state = self._state_to_restore
        state_context = state.get('context', {})
        if not state_context.get('is_running', False):
            state_file_path_str = getattr(self, '_state_file_path', 'Unknown file')
            was_interrupted = state_context.get('was_interrupted', False)
            reason = "回测被强制中断时生成的" if was_interrupted else "回测正常结束后生成的"
            raise RuntimeError(
                f"操作被禁止：不允许从一个终结状态文件 ({state_file_path_str}) 进行分叉。\n"
                f"原因：该状态是[{reason}]，并非由'暂停'(Pause)操作创建的可分叉状态。"
            )
        
        self.temp_logger.info("=" * 60)
        self.temp_logger.info("QTrader - 从快照分叉回测")
        self.temp_logger.info(f"重新初始化: {reinitialize}")
        self.temp_logger.info("=" * 60)

        # --- 2. 设置上下文和日志 ---
        state_path = Path(self._state_file_path)
        original_workspace_dir = state_path.parent
        self.context = Context(config=self.config)
        self.context.engine = self
        log_config = self.config.get('logging', {})
        log_config['file'] = str(original_workspace_dir/"backtest.log") # 日志仍在原工作区
        self.context.logger = setup_logger(log_config, self.context)
        self.context.logger.info(f"从状态文件分叉: {self._state_file_path}")

        # --- 3. 加载新的（或旧的）策略和数据提供者 ---
        if strategy:
            strategy_class = self._load_strategy_class(strategy)
        else:
            strategy_path = original_workspace_dir / "snapshot_code.py"
            if not strategy_path.exists(): raise FileNotFoundError(f"策略快照不存在: {strategy_path}")
            strategy_class = self._load_strategy_class(str(strategy_path))
            strategy = str(strategy_path)

        if data_provider:
            data_provider_instance = self._load_data_provider(data_provider)
        else:
            data_provider_path = original_workspace_dir / "snapshot_data_provider.py"
            if not data_provider_path.exists(): raise FileNotFoundError(f"数据提供者不存在: {data_provider_path}")
            data_provider_instance = self._load_data_provider(str(data_provider_path))
            data_provider = str(data_provider_path)

        # --- 4. 设置分叉运行的上下文 ---
        self.context.data_provider = data_provider_instance
        context_data = state['context']
        fork_dt = context_data['current_dt']
        fork_date_str = fork_dt.strftime('%Y-%m-%d')
        
        # a. 确定最终的运行参数.
        #    优先级: new config > saved state > default.
        #    Context 的 __post_init__ 已从 new config 加载了初始值.
        #    现在, 我们用状态文件中的值作为备选, 来覆盖那些未在新 config 中指定的属性.
        engine_config = self.config.get('engine', {})
        self.context.strategy_name = engine_config.get('strategy_name', strategy_class.__name__)
        self.context.mode = engine_config.get('mode', context_data.get('mode', self.context.mode))
        self.context.frequency = engine_config.get('frequency', context_data.get('frequency', self.context.frequency))
        self.context.end_date = engine_config.get('end_date', context_data.get('end_date', self.context.end_date))
        
        # 分叉的起始日期是固定的, 必须覆盖
        self.context.start_date = fork_date_str

        # b. 创建一个全新的工作区用于存放分叉后的结果
        self.workspace_manager = WorkspaceManager(
            strategy_path=strategy, data_provider_path=data_provider,
            config=self.config, logger=self.context.logger,
            mode=self.context.mode
        )

        # --- 5. 精确重建分叉时刻的状态 ---
        # a. 恢复并截断历史记录
        self.context.portfolio = state['portfolio']
        self.context.portfolio.history = [h for h in state['portfolio'].history if h['date'] < fork_date_str]

        # c. 从分叉点前一天的快照重建初始持仓
        self.context.position_manager = PositionManager(self.context)
        self.context.position_manager.restore_daily_snapshots(
            [s for s in state.get('position_snapshots', []) if s['date'] < fork_date_str]
        )
        all_snapshots = state.get('position_snapshots', [])
        last_day_snapshot = next((s for s in reversed(all_snapshots) if s.get('date') < fork_date_str), None)
        if last_day_snapshot:
            self.context.logger.info(f"从 {last_day_snapshot['date']} 的收盘快照恢复初始持仓...")
            from ..trading.position import Position, PositionDirection
            for pos_data in last_day_snapshot.get('positions', []):
                if pos_data.get('symbol_name') == '现金': continue
                direction = PositionDirection.LONG if pos_data['direction'] == 'long' else PositionDirection.SHORT
                new_pos = Position(
                    symbol=pos_data['symbol'], symbol_name=pos_data['symbol_name'],
                    amount=pos_data['amount'], avg_cost=pos_data['close_price'],
                    current_dt=fork_dt, direction=direction
                )
                new_pos.available_amount = new_pos.total_amount
                new_pos.today_open_amount = 0
                new_pos.last_settle_price = pos_data['close_price']
                key = self.context.position_manager._key(new_pos.symbol, new_pos.direction)
                self.context.position_manager.positions[key] = new_pos

        # d. 恢复历史已成交订单
        self.context.order_manager = OrderManager(self.context)
        all_orders = state.get('orders', [])
        restored_orders = [o for o in all_orders if (o.status == OrderStatus.FILLED and o.filled_time and o.filled_time.date() < datetime.strptime(fork_date_str, "%Y-%m-%d").date())]
        self.context.order_manager.restore_orders(restored_orders)

        # e. 处理用户自定义状态
        if reinitialize:
            self.context.user_data = {}
            # 如果重新初始化，则从一个干净的调度列表开始，让新策略自己定义
            self.context.custom_schedule_points = []
        else:
            self.context.user_data = state.get('user_data', {})
            self.context.logger.warning("保留了旧策略的user_data - 请确保新策略兼容！")
            # 如果不重新初始化，则恢复旧策略的自定义调度点
            self.context.custom_schedule_points = state.get('context', {}).get('custom_schedule_points', [])

        # f. 恢复并截断基准历史
        benchmark_config = self.config.get('benchmark', {})
        self.context.benchmark_manager = BenchmarkManager(self.context, benchmark_config)
        self.context.benchmark_manager.benchmark_history = [h for h in state.get('benchmark_history', []) if h['date'] < fork_date_str]
        
        # --- 6. 重新初始化非状态组件 ---
        matching_engine = MatchingEngine(self.context, self.config.get('matching', {}))
        time_manager = TimeManager(self.context)
        strategy_instance = strategy_class()
        lifecycle_manager = LifecycleManager(self.context)
        lifecycle_manager.register_strategy(strategy_instance)
        
        if reinitialize:
            self.context.logger.info("调用新策略的initialize()...")
            lifecycle_manager.call_initialize()
        
        self.scheduler = Scheduler(self.context, time_manager, matching_engine, lifecycle_manager)
        self.state_serializer = StateSerializer(self.context, str(self.workspace_manager.workspace_dir))
        self.context.state_serializer = self.state_serializer
        
        # --- 7. 启动并执行 ---
        self._start_server_if_enabled()
        self._register_signal_handlers()
        if start_paused: self.context.start_paused = True
        self._execute_main_loop(skip_initialize=(not reinitialize))

    def _run_simulation_unified(self, strategy_path: Optional[str], data_provider_path: Optional[str], is_resume: bool, start_paused: bool = False):
        """
        统一处理全新启动和恢复的模拟交易流程。

        模拟交易与回测的主要区别在于其时间基准是真实世界的当前时间。
        因此，它需要一个特殊的时间同步过程，以确保在启动或恢复时，
        策略状态能与真实市场时间对齐。

        Args:
            strategy_path (Optional[str]): 策略文件路径。对于新运行是必需的。
            data_provider_path (Optional[str]): 数据提供者路径。对于新运行是必需的。
            is_resume (bool): 标记是全新启动还是从状态恢复。
            start_paused (bool): 是否在启动后立即暂停。
        """
        self.context = Context(config=self.config)
        self.context.engine = self
        self.context.mode = 'simulation'

        if is_resume:
            # --- 恢复模拟交易流程 ---
            self.temp_logger.info("=" * 60); self.temp_logger.info("QTrader - 恢复模拟交易"); self.temp_logger.info("=" * 60)
            
            # 1. 确定工作区并设置日志
            state = self._state_to_restore
            state_path = Path(self._state_file_path)
            workspace_dir = state_path.parent
            log_config = self.config.get('logging', {}); log_config['file'] = str(workspace_dir / "simulation.log")
            self.context.logger = setup_logger(log_config, self.context)
            
            # 2. 从状态恢复核心组件 (Portfolio, Positions, Orders etc.)
            self._restore_components_from_state(state)
            self.context.end_date = '9999-12-31' # 模拟盘永不结束
            
            # 3. 加载代码快照
            if strategy_path is None: strategy_path = str(workspace_dir / "snapshot_code.py")
            if data_provider_path is None: data_provider_path = str(workspace_dir / "snapshot_data_provider.py")
            
            # 4. 重新初始化非状态组件 (Workspace, Scheduler etc.)
            self.workspace_manager = WorkspaceManager(
                strategy_path, data_provider_path, self.config, self.context.logger,
                mode=self.context.mode,
                workspace_dir_override=str(workspace_dir)
            )
            self.state_serializer = StateSerializer(self.context, str(workspace_dir))
            self.context.state_serializer = self.state_serializer
            self.context.data_provider = self._load_data_provider(data_provider_path)

            time_manager = TimeManager(self.context)
            matching_engine = MatchingEngine(self.context, self.config.get('matching', {}))
            lifecycle_manager = LifecycleManager(self.context)
            strategy_class = self._load_strategy_class(str(self.workspace_manager.strategy_path))
            strategy_instance = strategy_class()
            lifecycle_manager.register_strategy(strategy_instance)
            self.scheduler = Scheduler(self.context, time_manager, matching_engine, lifecycle_manager)
        else:
            # --- 启动全新模拟交易流程 ---
            self.temp_logger.info("=" * 60); self.temp_logger.info("QTrader - 启动全新模拟交易"); self.temp_logger.info("=" * 60)
            
            # 1. 初始化工作区和上下文
            data_provider_instance = self._load_data_provider(data_provider_path)
            self.workspace_manager = WorkspaceManager(strategy_path, data_provider_path, self.config, self.temp_logger, mode=self.context.mode)
            self.context.frequency = self.config.get('engine', {}).get('frequency', 'daily')
            self.context.start_date = datetime.now().strftime('%Y-%m-%d')
            self.context.end_date = '9999-12-31' # 模拟盘永不结束

            # 2. 设置日志
            log_config = self.config.get('logging', {}); log_config['file'] = str(self.workspace_manager.log_file)
            self.context.logger = setup_logger(log_config, self.context)
            self.workspace_manager.logger = self.context.logger
            
            # 3. 加载策略和数据
            strategy_class = self._load_strategy_class(strategy_path)
            self.context.strategy_name = self.config.get('engine', {}).get('strategy_name', strategy_class.__name__)
            self.context.data_provider = data_provider_instance
            
            # 4. 初始化核心组件
            self._initialize_components(strategy_class)
            self._initialize_simulation_history()
        
        # --- 关键步骤：同步到真实时间 ---
        # 无论是恢复还是新启动，都需要确保内部时间与真实世界对齐
        self._synchronize_to_realtime(
            time_manager=self.scheduler.time_manager,
            lifecycle_manager=self.scheduler.lifecycle_manager,
            is_new_run=(not is_resume)
        )

        # --- 启动事件循环 ---
        if start_paused: self.context.start_paused = True
        self._start_server_if_enabled()
        self._register_signal_handlers()
        # 模拟盘总是跳过 `initialize`，因为它在 `_synchronize_to_realtime` 中被手动调用
        self._execute_main_loop(skip_initialize=True)

    def _synchronize_to_realtime(self, time_manager: TimeManager, lifecycle_manager: LifecycleManager, is_new_run: bool = False):
        """
        将模拟盘的状态快进并同步到当前真实时间。

        这是模拟交易的核心逻辑之一。当一个模拟交易程序停止一段时间后重新启动时，
        它的内部状态（如持仓、资金）还停留在过去的时间点。此方法的作用就是
        “追赶”上这段错失的时间。

        执行流程:
        1.  **确定时间跨度**: 计算上次同步时间（状态文件中记录的时间）与当前真实时间之间
            错过了多少个交易日。
        2.  **清理瞬时状态**: 如果是恢复运行，取消所有在暂停期间未成交的 `OPEN` 订单，
            因为它们在真实世界中早已过期。
        3.  **快进结算**: 遍历所有错过的交易日，对每一天执行一个简化的结算流程
            (`matching_engine.settle()`)。这会更新持仓的成本、计算每日盈亏，并更新
            投资组合的净值。注意：在这个快进阶段，不会触发用户策略的 `handle_data` 或
            其他事件，因为它仅仅是为了让账户状态跟上市场。
        4.  **更新当前时间**: 将 `context.current_dt` 设置为当前的真实时间。
        5.  **确定市场阶段**: 根据当前时间判断市场处于盘前、盘中还是盘后，以便 `Scheduler`
            可以从正确的状态开始其事件循环。
        """
        self.context.logger.info("开始执行时间同步程序...")
        
        # --- 1. 确定同步的起始时间 ---
        if is_new_run:
            # 对于全新运行，调用 initialize 并将当前时间设为起始点
            self.context.current_dt = datetime.now()
            self.context.logger.info("全新模拟，调用 initialize()...")
            lifecycle_manager.call_initialize()
            last_sync_dt = self.context.current_dt
        else:
            # 对于恢复运行，从状态文件中记录的时间点开始
            last_sync_dt = self.context.current_dt

        now = datetime.now()
        self.context.logger.info(f"上次同步时间: {last_sync_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        self.context.logger.info(f"目标同步时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        # --- 2. 状态清理 ---
        if not is_new_run:
            # 清理所有已过期的挂单
            self.context.logger.info("清理瞬时状态: 将所有 OPEN 订单置为 EXPIRED...")
            for order in self.context.order_manager.get_open_orders(): order.expire()
            self.context.order_manager.clear_today_orders()
        # 清理所有日内历史记录
        self.context.intraday_equity_history.clear()
        self.context.intraday_benchmark_history.clear()
        
        # --- 3. 快进结算错过的交易日 ---
        missed_trading_days = time_manager.get_trading_days(
            (last_sync_dt + timedelta(days=1)).strftime('%Y-%m-%d'),
            (now - timedelta(days=1)).strftime('%Y-%m-%d')
        )
        if missed_trading_days:
            self.context.logger.info(f"检测到 {len(missed_trading_days)} 个错过的交易日，开始状态快进...")
            fast_forward_me = MatchingEngine(self.context, self.config.get('matching', {}))
            broker_settle_time_str = self.config.get('lifecycle', {}).get('hooks', {}).get('broker_settle', '15:30:00')
            for day_str in missed_trading_days:
                # 在每个错过的交易日，模拟一次结算流程
                settle_dt = datetime.strptime(f"{day_str} {broker_settle_time_str}", "%Y-%m-%d %H:%M:%S")
                self.context.current_dt = settle_dt
                fast_forward_me.settle()
                self.context.benchmark_manager.update_daily()
        
        # --- 4. 更新到当前时间并确定市场阶段 ---
        self.context.current_dt = now
        self.context.logger.info(f"状态已同步至当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        hooks = self.config.get('lifecycle', {}).get('hooks', {})
        before_trading_time = datetime.strptime(hooks.get('before_trading', '09:15:00'), '%H:%M:%S').time()
        after_trading_time = datetime.strptime(hooks.get('after_trading', '15:05:00'), '%H:%M:%S').time()

        if time_manager.is_trading_day(now):
            current_time = now.time()
            if current_time < before_trading_time:
                self.context.market_phase = 'BEFORE_TRADING'
            elif current_time < after_trading_time:
                self.context.market_phase = 'TRADING'
            else:
                self.context.market_phase = 'AFTER_TRADING'
        else:
             self.context.market_phase = 'CLOSED'
        self.context.logger.info(f"当前市场阶段判定为: {self.context.market_phase}")

    def _execute_main_loop(self, skip_initialize=False):
        """
        启动并管理主事件循环。

        这是引擎将控制权移交给 `Scheduler` 的地方。`Scheduler` 负责根据时间
        驱动，依次生成和分发各种事件（如 `before_trading`, `handle_data`,
        `after_trading` 等），并调用策略的相应方法。

        整个过程被包裹在一个 `try...finally` 块中，以确保无论运行是正常结束、
        被用户中断还是因异常崩溃，`_finalize()` 收尾函数都一定会被执行。
        """
        self.context.is_running = True
        try:
            # 调用 Scheduler 的 run 方法，阻塞直到整个回测/模拟结束。
            self.scheduler.run(skip_initialize=skip_initialize)
        except Exception as e:
            # 捕获所有未处理的异常，记录日志，并标记为中断。
            self.context.logger.error(f"运行时发生异常: {e}", exc_info=True)
            self.context.was_interrupted = True
        finally:
            # 无论成功或失败，都执行最终的清理和收尾工作。
            self.context.logger.info("执行最终收尾程序..."); self._finalize()

    def _restore_components_from_state(self, state: Dict[str, Any]):
        """
        从 state 字典中恢复所有核心组件的状态。
        
        此方法是 `StateSerializer` 保存操作的逆过程。它逐一重建了
        各个核心组件，并用 state 字典中的数据填充它们，从而将整个
        系统恢复到保存时的状态。
        """
        self.context.engine = self
        self.context.logger.info(f"从状态文件恢复...")
        self.context.logger.info(f"保存时间: {state.get('timestamp', 'Unknown')}")
        
        # 1. 恢复 Context 中的基本信息
        context_data = state['context']
        self.context.mode = self.config.get('engine', {}).get('mode', context_data['mode'])
        self.context.strategy_name = self.config.get('engine', {}).get('strategy_name', context_data['strategy_name'])
        self.context.start_date = context_data['start_date']
        self.context.end_date = self.config.get('engine', {}).get('end_date', context_data['end_date'])
        self.context.current_dt = context_data['current_dt']
        self.context.frequency = self.config.get('engine', {}).get('frequency', context_data['frequency'])
        self.context.frequency_options = self.config.get('engine', {}).get(
            'frequency_options', context_data.get('frequency_options', {})
        )
        self.context.user_data = state.get('user_data', {})
        self.context.intraday_equity_history = context_data.get('intraday_equity_history', [])
        self.context.intraday_benchmark_history = context_data.get('intraday_benchmark_history', [])
        self.context.log_buffer = context_data.get('log_buffer', [])
        self.context.scheduler_state_machine = context_data.get('scheduler_state_machine')
        self.context.custom_schedule_points = context_data.get('custom_schedule_points', [])
        
        # 2. 恢复 Portfolio (账户)
        self.context.portfolio = state['portfolio']
        
        # 3. 恢复 OrderManager (订单管理器)
        self.context.order_manager = OrderManager(self.context)
        self.context.order_manager.restore_orders(state.get('orders', []))
        
        # 4. 恢复 PositionManager (持仓管理器)
        self.context.position_manager = PositionManager(self.context)
        self.context.position_manager.restore_positions(state.get('positions', []))
        self.context.position_manager.restore_daily_snapshots(state.get('position_snapshots', []))
        
        # 5. 恢复 BenchmarkManager (基准管理器)
        benchmark_config = self.config.get('benchmark', {})
        self.context.benchmark_manager = BenchmarkManager(self.context, benchmark_config)
        self.context.benchmark_manager.benchmark_history = state.get('benchmark_history', [])
        if (benchmark_config and
            'symbol' in benchmark_config and
            not self.context.benchmark_manager.benchmark_symbol):
            self.context.benchmark_manager.benchmark_symbol = benchmark_config['symbol']
            self.context.benchmark_manager.benchmark_name = benchmark_config.get(
                'name', self.context.benchmark_manager.benchmark_symbol
            )
            self.context.benchmark_manager.initial_value = state.get('benchmark_initial_value')

    def _load_strategy_class(self, strategy_path: str) -> Type[Strategy]:
        """从给定的文件路径动态加载策略类。"""
        strategy_path_obj = Path(strategy_path).resolve()
        if not strategy_path_obj.exists():
            raise FileNotFoundError(f"策略文件不存在: {strategy_path_obj}")
        
        spec = importlib.util.spec_from_file_location("user_strategy", strategy_path_obj)
        module = importlib.util.module_from_spec(spec)
        sys.modules["user_strategy"] = module
        spec.loader.exec_module(module)
        
        strategy_class = None
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                strategy_class = obj
                break
        
        if strategy_class is None:
            raise ValueError(f"在 {strategy_path} 中未找到Strategy子类")
        
        logger = self.context.logger if self.context and self.context.logger else self.temp_logger
        logger.info(f"策略类 {strategy_class.__name__} 已加载")
        return strategy_class
    
    def _load_data_provider(self, provider_path: str) -> AbstractDataProvider:
        """从给定的文件路径动态加载数据提供者实例。"""
        provider_file_path = Path(provider_path).resolve()
        if not provider_file_path.exists():
            raise FileNotFoundError(f"数据提供者文件不存在: {provider_file_path}")

        module_name = provider_file_path.stem
        spec = importlib.util.spec_from_file_location(module_name, provider_file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module 
        spec.loader.exec_module(module)
        
        provider_class = None
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, AbstractDataProvider) and obj is not AbstractDataProvider:
                provider_class = obj
                break
        
        if provider_class is None:
            raise TypeError(f"在 {provider_path} 中未找到 AbstractDataProvider 的子类")
            
        logger = self.context.logger if self.context and self.context.logger else self.temp_logger
        logger.info(f"已加载数据提供者: {provider_class.__name__}")
        return provider_class()
    
    def _initialize_components(self, strategy_class: Type[Strategy]):
        """
        为一次全新的运行初始化所有核心组件。

        此方法扮演着“依赖注入容器”的角色。它按照正确的顺序创建所有
        核心服务和管理器，并将它们注册到 `context` 对象中，以便各组件
        之间可以通过 `context` 互相访问，实现解耦。
        """
        # --- 1. 初始化基础账户和交易组件 ---
        account_config = self.config.get('account', {})
        self.context.portfolio = Portfolio(account_config.get('initial_cash', 1000000))
        self.context.order_manager = OrderManager(self.context)
        self.context.position_manager = PositionManager(self.context)
        
        # --- 2. 初始化基准管理器 ---
        benchmark_config = self.config.get('benchmark', {})
        self.context.benchmark_manager = BenchmarkManager(self.context, benchmark_config)
        if benchmark_config and benchmark_config.get('symbol',None):
            self.context.benchmark_manager.initialize(benchmark_config)
        
        # --- 3. 初始化核心引擎和管理器 ---
        # 这些组件是无状态的或依赖于其他已初始化的组件
        matching_engine = MatchingEngine(self.context, self.config.get('matching', {}))
        time_manager = TimeManager(self.context)
        
        # --- 4. 实例化策略并注册到生命周期管理器 ---
        strategy_instance = strategy_class()
        lifecycle_manager = LifecycleManager(self.context)
        lifecycle_manager.register_strategy(strategy_instance)
        
        # --- 5. 初始化调度器，这是事件循环的核心 ---
        self.scheduler = Scheduler(self.context, time_manager, matching_engine, lifecycle_manager)
        
        # --- 6. 初始化状态序列化器 ---
        if self.workspace_manager:
            self.state_serializer = StateSerializer(self.context, str(self.workspace_manager.workspace_dir))
            self.context.state_serializer = self.state_serializer
    
    def _initialize_history(self):
        """为投资组合和基准的历史记录注入一个初始时间点。"""
        initial_cash = self.context.portfolio.initial_cash
        trading_days = self.scheduler.time_manager.get_trading_days(self.context.start_date, self.context.end_date)
        
        if trading_days:
            first_trading_day_dt = datetime.strptime(trading_days[0], '%Y-%m-%d')
            day_before_str = (first_trading_day_dt - timedelta(days=1)).strftime('%Y-%m-%d')

            self.context.portfolio.history.append({
                'date': day_before_str,
                'cash': initial_cash,
                'position_value': 0.0,
                'total_value': initial_cash,
                'returns': 0.0,
            })
            
            if self.context.benchmark_manager and self.context.benchmark_manager.benchmark_symbol:
                self.context.benchmark_manager.benchmark_history.append({
                    'date': day_before_str,
                    'close_price': self.context.benchmark_manager.initial_value,
                    'returns': 0.0,
                    'value': initial_cash,
                })
            self.context.logger.debug(f"在 {day_before_str} 注入初始净值点。")
    
    def _initialize_simulation_history(self):
        """为模拟交易注入基于当前时间的初始历史记录点。"""
        self.context.logger.info("为模拟盘注入初始净值点...")
        initial_cash = self.context.portfolio.initial_cash

        # 从今天开始往前找，找到“昨天”
        # 确保我们从“昨天”开始搜索，而不是今天
        previous_day = datetime.now() - timedelta(days=1)
        day_before_str = previous_day.strftime('%Y-%m-%d')

        self.context.portfolio.history.append({
            'date': day_before_str,
            'cash': initial_cash,
            'position_value': 0.0,
            'total_value': initial_cash,
            'returns': 0.0,
        })
        
        if self.context.benchmark_manager and self.context.benchmark_manager.benchmark_symbol:
            # 确保基准已初始化
            if not self.context.benchmark_manager.initial_value:
                self.context.benchmark_manager.initialize(self.config.get('benchmark', {}))
            
            if self.context.benchmark_manager.initial_value is not None:
                self.context.benchmark_manager.benchmark_history.append({
                    'date': day_before_str,
                    'close_price': self.context.benchmark_manager.initial_value,
                    'returns': 0.0,
                    'value': initial_cash,
                })
                self.context.logger.info(f"在 {day_before_str} (前一交易日) 注入初始净值和基准点。")
            else:
                self.context.logger.warning(f"基准 {self.context.benchmark_manager.benchmark_symbol} 缺少 initial_value，无法注入基准历史点。")
        else:
            self.context.logger.info(f"在 {day_before_str} (前一交易日) 注入初始净值点。")
    
    def _start_server_if_enabled(self):
        """如果配置中启用，则启动集成监控服务器。"""
        server_config = self.config.get('server', {})
        if server_config.get('enable', False) and self.workspace_manager:
            self.server = IntegratedServer(self.context, self.workspace_manager, server_config)
            self.server.start()
            self.context.visualization_server = self.server
            
            if server_config.get('auto_open_browser', False):
                time.sleep(1)
                webbrowser.open(f"http://localhost:{server_config.get('port', 8050)}", new=2)
    
    def _register_signal_handlers(self):
        """注册信号处理器以实现优雅退出 (Ctrl+C)。"""
        def handle_exit(signum, frame):
            logger = self.context.logger if self.context and self.context.logger else self.temp_logger
            if self.context and self.context.is_running:
                logger.warning(f"接收到停止信号 ({signum})，正在优雅退出...")
                self.stop()
            else:
                logger.warning("已在停止过程中，强制退出。")
                sys.exit(1)
        
        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)
    
    def _finalize(self):
        """
        在运行结束后执行所有清理工作，如保存状态、生成报告等。

        此方法是 `_execute_main_loop` 中 `finally` 块的核心，确保无论
        运行以何种方式结束，都能执行必要的收尾操作，保证数据完整性和
        资源释放。
        """
        if not self.context: return
        self.context.is_running = False
        
        # 如果是因异常或用户中断而结束，确保调用策略的 on_end() 方法。
        if self.context.was_interrupted and self.scheduler:
            self.scheduler.lifecycle_manager.call_on_end()

        # 1. 保存最终状态
        # 根据结束方式（中断/正常结束）保存状态文件，用于事后分析或报告生成。
        if self.state_serializer:
            tag = 'interrupt' if self.context.was_interrupted else 'final'
            self.state_serializer.save(tag=tag)
        
        # 2. 导出关键数据到 CSV
        # 将每日持仓、订单历史、净值曲线等导出为 CSV 文件，方便外部工具分析。
        if self.workspace_manager:
            self.context.logger.info("正在导出CSV文件...")
            self.workspace_manager.export_csv_files(self.context)

        # 3. 生成 HTML 性能报告
        if self.config.get('report', {}).get('enable', True) and self.workspace_manager:
            self.context.logger.info("正在生成最终报告...")
            # 如果已有 server 实例则复用，否则创建一个临时的用于生成报告
            server_for_report = self.server or IntegratedServer(
                self.context, self.workspace_manager, self.config.get('server', {})
            )
            try:
                server_for_report.generate_final_report(str(self.workspace_manager.report_file), self.context)
            except Exception as e:
                self.context.logger.error(f"生成报告失败: {e}", exc_info=True)
        
        # 4. 关闭监控服务器
        if self.server:
            self.context.logger.info("正在关闭监控服务器...")
            self.server.trigger_update() # 最后一次更新前端
            time.sleep(0.5)
            self.server.stop()
            self.context.logger.info("监控服务器已关闭。")
        
        # 5. 自动打开报告
        if (self.config.get('report', {}).get('auto_open', False) and
            self.workspace_manager and
            self.workspace_manager.report_file.exists()):
            self.context.logger.info("正在自动打开回测报告...")
            try:
                report_path = str(self.workspace_manager.report_file.resolve())
                if sys.platform == "win32":
                    os.startfile(report_path)
                else:
                    webbrowser.open(self.workspace_manager.report_file.as_uri())
                time.sleep(3) # 增加延时以确保浏览器有足够时间启动
            except Exception as e:
                self.context.logger.warning(f"自动打开报告失败: {e}")
        
        self.context.logger.info("引擎运行结束")
    
    def pause(self):
        """请求暂停当前的运行。"""
        if self.context and self.context.is_running and not self.context.is_paused:
            self.context.logger.info("收到暂停指令，将在当前K线/事件处理完毕后暂停。")
            self.context.pause_requested = True
    
    def resume_running(self):
        """从暂停状态恢复运行。"""
        if self.context and self.context.is_running and self.context.is_paused:
            self.context.is_paused = False
            self.context.pause_requested = False
            self.context.logger.info("回测已恢复运行")
    
    def stop(self):
        """请求停止当前的运行。"""
        if self.context and self.context.is_running:
            self.context.logger.info("收到停止指令，将在当前K线/事件处理完毕后优雅退出。")
            self.context.stop_requested = True
            if self.context.is_paused:
                self.context.is_running = False