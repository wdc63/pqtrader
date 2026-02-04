# qtrader/core/scheduler.py

import time as time_module
from datetime import datetime, time, timedelta, date
from typing import List
from ..core.context import Context
from ..core.time_manager import TimeManager
from ..core.lifecycle import LifecycleManager
from ..trading.matching_engine import MatchingEngine

# 定义默认时间常量
DEFAULT_BEFORE_TRADING_TIME = '09:15:00'
DEFAULT_HANDLE_BAR_TIME = '14:55:00'
DEFAULT_AFTER_TRADING_TIME = '15:05:00'
DEFAULT_BROKER_SETTLE_TIME = '15:30:00'

class Scheduler:
    """
    事件调度器 (Event Scheduler)，QTrader 框架的“心脏”。

    作为事件驱动循环的核心，Scheduler 负责根据时间精确地生成和分派
    一系列生命周期事件。它与 `Engine` 解耦，专注于“何时”做某事，而
    将“做什么”交给 `LifecycleManager` 和 `MatchingEngine`。

    主要职责:
    1.  **时间管理**:
        - 与 `TimeManager` 协作，获取交易日历和时间点。
        - 根据 `daily` 或 `minute` 等频率配置，构建详细的事件触发时间表
          (`_schedule_points`)。

    2.  **回测事件循环 (`_run_backtest`)**:
        - 按照交易日历逐天推进。
        - 在每个交易日内，严格按照 `before_trading`, `handle_bar` (循环),
          `after_trading`, `broker_settle` 的顺序触发事件。
        - 支持从暂停点恢复，并能智能地调整当天的事件时间表。

    3.  **模拟交易事件循环 (`_run_simulation`)**:
        - 基于真实世界的当前时间运行一个实时状态机。
        - 持续监控当前时间，并在到达预设的钩子时间点（如 09:15:00）时
          触发相应的事件。
        - 能够“追赶”因系统延迟而错过的 `handle_bar` 事件。

    4.  **用户交互处理**:
        - 在事件循环的各个关键节点检查 `context` 中的标志位（如
          `stop_requested`, `pause_requested`）。
        - 响应用户请求，执行暂停、恢复或终止操作，并负责在暂停时
          保存状态。
    """

    def __init__(
        self,
        context: Context,
        time_manager: TimeManager,
        matching_engine: MatchingEngine,
        lifecycle_manager: LifecycleManager
    ):
        self.context = context
        self.time_manager = time_manager
        self.matching_engine = matching_engine
        self.lifecycle_manager = lifecycle_manager
        
        self.config = context.config
        self.engine_config = self.config.get('engine', {})
        self.lifecycle_config = self.config.get('lifecycle', {})
        self.server_config = self.config.get('server', {})
        self._server_enabled = self.server_config.get('enable', False)
        self._update_interval = self.server_config.get('update_interval', 1.0)
        self._enable_intraday_statistics = self.engine_config.get('enable_intraday_statistics', False)
        self._intraday_update_freq = self.engine_config.get('intraday_update_frequency', 5)
        self._last_intraday_stats_update_dt = datetime(1970, 1, 1)
        self._benchmark_start_of_day_price = None
        self._strategy_start_of_day_value = None
        self._schedule_points = self._build_schedule_points()
        self._custom_schedule_merged = False

    def _enter_pause_loop(self) -> bool:
        """进入暂停等待循环"""
        while self.context.is_paused:
            if self.context.stop_requested:
                self.context.logger.info("在暂停期间收到停止指令，即将退出。")
                self.context.is_running = False
                self.context.was_interrupted = True
                return False
            time_module.sleep(0.1)
        return self.context.is_running

    def _check_and_handle_requests(self) -> bool:
        """检查暂停/停止请求"""
        if self.context.stop_requested:
            self.context.logger.info("响应停止请求，即将终止回测循环。")
            self.context.is_running = False
            self.context.was_interrupted = True
            return False

        if self.context.pause_requested:
            self.context.logger.info(f"响应暂停请求，将在 {self.context.current_dt} 暂停。")
            
            if self._enable_intraday_statistics:
                self._update_intraday_statistics(self.context.current_dt, force_update=True)
            
            if self.context.state_serializer:
                self.context.state_serializer.save(tag='pause')

            self.context.is_paused = True
            self.context.pause_requested = False

            self._maybe_update_server()

            while self.context.is_paused:
                if self.context.stop_requested:
                    self.context.logger.info("在暂停期间收到停止指令，即将退出。")
                    self.context.is_running = False
                    self.context.was_interrupted = True
                    return False
                time_module.sleep(0.1)
            
            if not self.context.is_running:
                return False
        
        return True

    def run(self, skip_initialize: bool = False):
        """
        启动主事件循环，这是 Scheduler 的总入口。

        此方法首先处理 `initialize` 事件和启动暂停的逻辑，然后根据
        `context.mode` 将执行权分派给回测或模拟交易的专用循环。

        Args:
            skip_initialize (bool): 是否跳过调用策略的 `initialize()` 方法。
                                    在从状态恢复时应为 True。
        """
        # 1. 调用策略初始化 (仅在全新运行时)
        if not skip_initialize:
            self.lifecycle_manager.call_initialize()

        # 1.5 合并自定义调度点
        self._merge_custom_schedule_points()

        # 2. 处理启动即暂停的请求
        if self.context.start_paused:
            self.context.logger.info("运行以暂停状态启动。请在监控页面点击 '恢复' 继续。")
            self.context.is_paused = True
            self.context.start_paused = False
            self._maybe_update_server()
            if not self._enter_pause_loop(): # 进入等待循环，直到用户恢复
                return

        # 3. 根据模式选择并启动相应的事件循环
        if self.context.mode == 'backtest':
            self._run_backtest(skip_initialize)
        else:
            self._run_simulation()

    def _run_backtest(self, skip_initialize: bool = False):
        """
        执行回测模式的事件循环。
        这是一个严格按天和时间点推进的确定性循环。
        """
        # --- 1. 初始化日期和交易日历 ---
        start_date_str = self.context.start_date
        end_date_str = self.context.end_date
        resume_dt = self.context.current_dt if skip_initialize else None

        if resume_dt: # 如果是恢复运行，则调整起始日期
            start_date_str = resume_dt.strftime('%Y-%m-%d')
            self.context.logger.info(f"从 {start_date_str} 的 {resume_dt.strftime('%H:%M:%S')} 之后继续回测")

        trading_days = self.time_manager.get_trading_days(start_date_str, end_date_str)
        
        if not trading_days:
            self.context.logger.warning("在指定日期范围内没有交易日，回测结束。")
            self.lifecycle_manager.call_on_end()
            return

        total_days = len(trading_days)
        self.context.logger.info(f"回测开始，共 {total_days} 个交易日")

        # --- 2. 获取生命周期钩子的触发时间 ---
        hooks = self.lifecycle_config.get('hooks', {})
        before_trading_time = hooks.get('before_trading', DEFAULT_BEFORE_TRADING_TIME)
        after_trading_time = hooks.get('after_trading', DEFAULT_AFTER_TRADING_TIME)
        broker_settle_time = hooks.get('broker_settle', DEFAULT_BROKER_SETTLE_TIME)

        # --- 3. 主循环：遍历每个交易日 ---
        for idx, date_str in enumerate(trading_days):
            if not self.context.is_running:
                self.context.logger.info("回测被手动停止")
                break

            self.context.logger.info(f"--- 交易日: {date_str} ({idx + 1}/{total_days}) ---")

            points_to_iterate = self._schedule_points
            is_resume_day = (resume_dt is not None and date_str == resume_dt.strftime('%Y-%m-%d'))

            # --- 4. 每日初始化 / 恢复日处理 ---
            if is_resume_day:
                # 在恢复日，跳过盘前准备，并调整 handle_bar 的时间点
                self.context.logger.info("此为恢复日，跳过盘前准备流程。")
                if self.context.portfolio.history: self._strategy_start_of_day_value = self.context.portfolio.history[-1]['net_worth']
                if self.context.benchmark_manager.benchmark_history: self._benchmark_start_of_day_price = self.context.benchmark_manager.benchmark_history[-1].get('close_price')
                self._last_intraday_stats_update_dt = resume_dt
                resume_time_str = resume_dt.strftime('%H:%M:%S')
                points_to_iterate = [t for t in self._schedule_points if t > resume_time_str]
                if points_to_iterate: self.context.logger.info(f"将从 bar: {points_to_iterate[0]} 开始执行。")
                else: self.context.logger.info(f"恢复时间晚于所有 bar，直接进入盘后。")
            else:
                # 在新的一天，重置日内状态并执行盘前事件
                self._last_intraday_stats_update_dt = datetime(1970, 1, 1)
                self.context.symbol_info_cache.clear()
                self.context.intraday_equity_history.clear()
                self.context.intraday_benchmark_history.clear()
                self._benchmark_start_of_day_price = None
                self._strategy_start_of_day_value = None

                dt_before_trading = datetime.strptime(f"{date_str} {before_trading_time}", "%Y-%m-%d %H:%M:%S")
                self.context.current_dt = dt_before_trading
                self.lifecycle_manager.call_before_trading()

                if self.context.portfolio.history: self._strategy_start_of_day_value = self.context.portfolio.history[-1]['net_worth']
                if self.context.benchmark_manager.benchmark_history: self._benchmark_start_of_day_price = self.context.benchmark_manager.benchmark_history[-1].get('close_price')
                
                # 记录开盘点
                if self._enable_intraday_statistics and not is_resume_day:
                    sessions = self.lifecycle_config.get('trading_sessions', [])
                    if sessions:
                        market_open_time_str = sessions[0][0]
                        dt_market_open = datetime.strptime(f"{date_str} {market_open_time_str}", "%Y-%m-%d %H:%M:%S")
                        self._update_intraday_statistics(dt_market_open, force_update=True)

                self._maybe_update_server()
                if not self._check_and_handle_requests(): break

            # --- 5. 盘中循环：遍历 handle_bar 时间点 ---
            for time_str in points_to_iterate:
                dt_bar = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                self.context.current_dt = dt_bar
                self.lifecycle_manager.call_handle_bar()
                self.matching_engine.match_orders(dt_bar)

                if self._enable_intraday_statistics: self._update_intraday_statistics(dt_bar)
                self._maybe_update_server()
                if not self._check_and_handle_requests(): break
            
            if not self.context.is_running: break

            # 记录收盘点
            if self._enable_intraday_statistics:
                sessions = self.lifecycle_config.get('trading_sessions', [])
                if sessions:
                    market_close_time_str = sessions[-1][1]
                    dt_market_close = datetime.strptime(f"{date_str} {market_close_time_str}", "%Y-%m-%d %H:%M:%S")
                    self._update_intraday_statistics(dt_market_close, force_update=True)

            # --- 6. 盘后与结算事件 ---
            dt_after_trading = datetime.strptime(f"{date_str} {after_trading_time}", "%Y-%m-%d %H:%M:%S")
            self.context.current_dt = dt_after_trading
            self.lifecycle_manager.call_after_trading()
            self._maybe_update_server()
            if not self._check_and_handle_requests(): break

            dt_settle = datetime.strptime(f"{date_str} {broker_settle_time}", "%Y-%m-%d %H:%M:%S")
            self.context.current_dt = dt_settle
            self.matching_engine.settle()
            self.lifecycle_manager.call_broker_settle()
            self.context.benchmark_manager.update_daily()
            self._maybe_update_server()
            if not self._check_and_handle_requests(): break
            
            # --- 7. 自动保存状态 ---
            if self.context.config.get('workspace', {}).get('auto_save_state', False):
                auto_save_interval = self.context.config.get('workspace', {}).get('auto_save_interval', 10)
                auto_save_mode = self.context.config.get('workspace', {}).get('auto_save_mode', 'increment')
                if (idx + 1) % auto_save_interval == 0 and self.context.state_serializer:
                    tag = 'auto_save' if auto_save_mode == 'overwrite' else f'auto_save_day_{idx+1}'
                    self.context.state_serializer.save(tag=tag)

        # --- 8. 最终收尾 ---
        self.lifecycle_manager.call_on_end()
        self.context.logger.info("回测结束")

    def _check_for_resync(self, state_machine):
        """
        检查并响应时间同步请求。

        如果在模拟交易中检测到阻塞，此方法会调用引擎的同步功能来校准时间。
        """
        if self.context.resync_requested:
            self.context.logger.info("响应同步请求，正在命令引擎重新校准时间...")
            self.context.engine._synchronize_to_realtime(self.time_manager, self.lifecycle_manager)
            state_machine['daily_flags'] = { k: False for k in state_machine['daily_flags'] }
            state_machine['last_handle_bar_dt'] = self.context.current_dt
            state_machine['last_known_date'] = self.context.current_dt.date()
            state_machine['is_today_trading_day'] = None # 重置交易日缓存标志，强制在下一轮循环中重新检查
            self.context.resync_requested = False
            return True, state_machine
        return False, state_machine

    def _run_simulation(self):
        """
        执行模拟交易模式的实时事件循环。
        此模式严格与真实时钟同步（可由TimePatcher“欺骗”以测试延迟），
        并采用“逐个销账”的模式处理Bar事件，错过的机会将不再执行。
        """
        self.context.logger.info("模拟盘模式启动，基于真实时间运行...")
        
        # --- 1. 初始化状态机 ---
        if not getattr(self.context, 'scheduler_state_machine', None):
            self.context.scheduler_state_machine = {
                'daily_flags': {
                    'before_trading_done': False, 'after_trading_done': False, 'settle_done': False,
                    'market_open_recorded': False, 'market_close_recorded': False
                },
                'last_known_date': date(1970, 1, 1),
                'last_executed_bar_time': None, # 将记录上一个执行的bar的datetime.time对象
                'is_today_trading_day': None  # 新增：用于缓存当天是否为交易日的标志
            }

        state_machine = self.context.scheduler_state_machine

        if self.context.benchmark_manager.benchmark_history: self._benchmark_start_of_day_price = self.context.benchmark_manager.benchmark_history[-1].get('close_price')
        
        # --- 2. 获取配置 ---
        hooks = self.lifecycle_config.get('hooks', {})
        before_trading_time = datetime.strptime(hooks.get('before_trading', DEFAULT_BEFORE_TRADING_TIME), '%H:%M:%S').time()
        after_trading_time = datetime.strptime(hooks.get('after_trading', DEFAULT_AFTER_TRADING_TIME), '%H:%M:%S').time()
        broker_settle_time = datetime.strptime(hooks.get('broker_settle', DEFAULT_BROKER_SETTLE_TIME), '%H:%M:%S').time()
        sessions = self.lifecycle_config.get('trading_sessions', [])
        trading_sessions = [(datetime.strptime(s, '%H:%M:%S').time(), datetime.strptime(e, '%H:%M:%S').time()) for s, e in sessions]

        # --- 3. 主循环 ---
        while self.context.is_running:
            loop_start_time = time_module.time()
            now = datetime.now()
            old_phase = self.context.market_phase
            
            # --- 4. 每日状态重置 ---
            if now.date() > state_machine['last_known_date']:
                self.context.current_dt = now
                state_machine['daily_flags'] = {
                    'before_trading_done': False, 'after_trading_done': False, 'settle_done': False,
                    'market_open_recorded': False, 'market_close_recorded': False
                }
                state_machine['last_known_date'] = now.date()
                state_machine['is_today_trading_day'] = self.time_manager.is_trading_day(now)
                state_machine['last_executed_bar_time'] = None
                self.context.order_manager.clear_today_orders()
                self.context.intraday_equity_history.clear()
                self.context.intraday_benchmark_history.clear()
                self._last_intraday_stats_update_dt = datetime(1970, 1, 1)
                if self.context.portfolio.history: self._strategy_start_of_day_value = self.context.portfolio.history[-1]['net_worth']
                if self.context.benchmark_manager.benchmark_history: self._benchmark_start_of_day_price = self.context.benchmark_manager.benchmark_history[-1].get('close_price')
                
                if state_machine['is_today_trading_day']:
                    self.context.logger.info(f"--- 新交易日: {now.strftime('%Y-%m-%d')} ---")
                else:
                    self.context.logger.info(f"--- 今日非交易日: {now.strftime('%Y-%m-%d')} ---")
                self._maybe_update_server()

            # --- 5. 市场阶段判断与事件分派 ---
            if state_machine.get('is_today_trading_day') is None:
                state_machine['is_today_trading_day'] = self.time_manager.is_trading_day(now)
            
            if state_machine.get('is_today_trading_day'):
                current_time = now.time()
                
                # a. 判断市场阶段
                if any(start <= current_time <= end for start, end in trading_sessions): self.context.market_phase = 'TRADING'
                elif before_trading_time <= current_time < (trading_sessions[0][0] if trading_sessions else time(0,0)): self.context.market_phase = 'BEFORE_TRADING'
                elif (trading_sessions[-1][1] if trading_sessions else time(0,0)) < current_time < broker_settle_time: self.context.market_phase = 'AFTER_TRADING'
                elif current_time >= broker_settle_time and (not state_machine['daily_flags']['settle_done']): self.context.market_phase = 'SETTLEMENT'
                else: self.context.market_phase = 'CLOSED'

                # d. 补录开盘/收盘点 (simulation only)
                if self._enable_intraday_statistics:
                    # 补录开盘点: 首次进入TRADING状态时
                    if self.context.market_phase == 'TRADING' and not state_machine['daily_flags']['market_open_recorded']:
                        sessions = self.lifecycle_config.get('trading_sessions', [])
                        if sessions:
                            market_open_time_str = sessions[0][0]
                            dt_market_open = datetime.combine(now.date(), datetime.strptime(market_open_time_str, '%H:%M:%S').time())
                            self._update_intraday_statistics(dt_market_open, force_update=True)
                            state_machine['daily_flags']['market_open_recorded'] = True
                    
                    # 补录收盘点: 首次进入AFTER_TRADING状态时
                    if self.context.market_phase == 'AFTER_TRADING' and not state_machine['daily_flags']['market_close_recorded']:
                        sessions = self.lifecycle_config.get('trading_sessions', [])
                        if sessions:
                            market_close_time_str = sessions[-1][1]
                            dt_market_close = datetime.combine(now.date(), datetime.strptime(market_close_time_str, '%H:%M:%S').time())
                            self._update_intraday_statistics(dt_market_close, force_update=True)
                            state_machine['daily_flags']['market_close_recorded'] = True

                # b. 每日一次的事件 (盘前/盘后/结算)
                if (self.context.market_phase == 'BEFORE_TRADING' and not state_machine['daily_flags']['before_trading_done']):
                    self.context.current_dt = datetime.now()
                    self.lifecycle_manager.call_before_trading()
                    state_machine['daily_flags']['before_trading_done'] = True

                    was_resynced, state_machine = self._check_for_resync(state_machine)   
                    if was_resynced:
                        continue
                    self._maybe_update_server()

                if (self.context.market_phase == 'AFTER_TRADING' and not state_machine['daily_flags']['after_trading_done']):
                    self.context.current_dt = datetime.now()
                    if self.context.current_dt.time() < after_trading_time:
                        continue
                    self.lifecycle_manager.call_after_trading()
                    state_machine['daily_flags']['after_trading_done'] = True

                    was_resynced, state_machine = self._check_for_resync(state_machine)
                    if was_resynced:
                        continue
                    self._maybe_update_server()

                if (self.context.market_phase == 'SETTLEMENT' and not state_machine['daily_flags']['settle_done']):
                    self.context.current_dt = datetime.now()
                    self.matching_engine.settle()
                    self.lifecycle_manager.call_broker_settle()
                    self.context.benchmark_manager.update_daily()
                    state_machine['daily_flags']['settle_done'] = True

                    was_resynced, state_machine = self._check_for_resync(state_machine)
                    if was_resynced:
                        continue
                    self._maybe_update_server()

                # c. 调度点处理（不限制市场阶段，与回测一致）
                schedule = self._schedule_points
                now_time = now.time()

                # 找到最后一个小于等于当前时间的预设bar时间点
                target_bar_str = None
                for t_str in schedule:
                    if datetime.strptime(t_str, '%H:%M:%S').time() <= now_time:
                        target_bar_str = t_str
                    else:
                        break

                if target_bar_str:
                    target_bar_time = datetime.strptime(target_bar_str, '%H:%M:%S').time()

                    # 检查这个bar是否是新的、未执行过的
                    if state_machine['last_executed_bar_time'] is None or target_bar_time > state_machine['last_executed_bar_time']:

                        # 设置容差（修复：为 daily 模式添加专门处理）
                        if self.context.frequency == 'daily':
                            # daily 模式：宽松容差，只要是当天且未执行就执行
                            tolerance = timedelta(hours=24)
                        elif self.context.frequency == 'minute':
                            tolerance = timedelta(seconds=60)
                        else:  # tick
                            tolerance = timedelta(seconds=self.engine_config.get('tick_interval_seconds', 3))

                        # 检查是否在容差范围内 (补一根容差范围内的过期bar)
                        if (now - datetime.combine(now.date(), target_bar_time)) <= tolerance:
                            event_dt = datetime.now()
                            self.context.current_dt = event_dt
                            self.lifecycle_manager.call_handle_bar()
                            self.matching_engine.match_orders(event_dt)

                            was_resynced, state_machine = self._check_for_resync(state_machine)
                            if was_resynced:
                                continue

                            self._maybe_update_server()
                        else:
                            self.context.logger.warning(f"跳过过期的Bar: {target_bar_str} (当前时间: {now_time})")

                        # 无论是否执行，都更新记录，防止重复判断
                        state_machine['last_executed_bar_time'] = target_bar_time

                # d. 日内统计（仅在交易时段）
                if self.context.market_phase == 'TRADING':
                    stats_interval = timedelta(minutes=self._intraday_update_freq)
                    if self._enable_intraday_statistics and (now - self._last_intraday_stats_update_dt >= stats_interval):
                        if self._update_intraday_statistics(now):
                            self._last_intraday_stats_update_dt = now
                            self._maybe_update_server()
            else:
                self.context.market_phase = 'CLOSED'

            if self.context.market_phase != old_phase:
                self._maybe_update_server()
                
            # --- 6. 检查用户请求并休眠 ---
            if not self._check_and_handle_requests(): break
            
            loop_end_time = time_module.time()
            elapsed = loop_end_time - loop_start_time
            sleep_duration = 1.0 - elapsed
            
            if sleep_duration > 0:
                time_module.sleep(sleep_duration)
            else:
                time_module.sleep(0.1)

        # --- 7. 最终收尾 ---
        self.lifecycle_manager.call_on_end()
        self.context.logger.info("模拟盘运行结束")

    def _maybe_update_server(self):
        """如果服务器启用，则触发一次异步数据更新。"""
        if self._server_enabled and self.context.visualization_server:
            self.context.visualization_server.trigger_update()

    def _build_schedule_points(self) -> List[str]:
        """根据配置的频率和交易时段，构建一个包含所有 handle_bar 调用时间点的列表。"""
        freq = self.context.frequency
        
        if freq == 'daily':
            hooks = self.lifecycle_config.get('hooks', {})
            handle_bar_time = hooks.get('handle_bar', DEFAULT_HANDLE_BAR_TIME)
            return [handle_bar_time] if isinstance(handle_bar_time, str) else handle_bar_time

        schedule = []
        sessions = self.lifecycle_config.get('trading_sessions', [])

        for start_str, end_str in sessions:
            current_dt = datetime.strptime(start_str, '%H:%M:%S')
            end_dt = datetime.strptime(end_str, '%H:%M:%S')
            tick_interval_seconds = self.engine_config.get('tick_interval_seconds', 3)
            delta = timedelta(minutes=1) if freq == 'minute' else timedelta(seconds=tick_interval_seconds)

            while current_dt <= end_dt:
                schedule.append(current_dt.strftime('%H:%M:%S'))
                current_dt += delta

        return sorted(list(set(schedule)))
    
    def _merge_custom_schedule_points(self):
        """合并来自 context 的自定义调度时间点。"""
        if self._custom_schedule_merged or not self.context.custom_schedule_points:
            return
        
        custom_points = self.context.custom_schedule_points
        self.context.logger.info(f"合并 {len(custom_points)} 个自定义调度点...")
        
        # 合并、去重、排序
        merged_points = sorted(list(set(self._schedule_points + custom_points)))
        
        if len(merged_points) > len(self._schedule_points):
            self.context.logger.info(f"调度点数量从 {len(self._schedule_points)} 增加到 {len(merged_points)}")
            self._schedule_points = merged_points
        
        self._custom_schedule_merged = True

    def _update_intraday_statistics(self, dt: datetime, force_update: bool = False) -> bool:
        """
        按指定频率记录账户与基准的日内价值。

        Args:
            dt (datetime): 当前时间戳。
            force_update (bool): 是否强制更新，忽略频率限制。

        Returns:
            bool: 如果执行了更新，则返回 True，否则返回 False。
        """
        # 增加安全检查：在模拟盘中，仅在交易时段内更新
        if self.context.mode == 'simulation':
            sessions = self.lifecycle_config.get('trading_sessions', [])
            trading_sessions = [(datetime.strptime(s, '%H:%M:%S').time(), datetime.strptime(e, '%H:%M:%S').time()) for s, e in sessions]
            current_time = dt.time()
            if not any(start <= current_time <= end for start, end in trading_sessions):
                return False

        stats_interval = timedelta(minutes=self._intraday_update_freq)
        is_on_schedule = dt - self._last_intraday_stats_update_dt >= stats_interval

        if not force_update and not is_on_schedule:
            return False
        
        self._last_intraday_stats_update_dt = dt
        
        pm = self.context.position_manager
        # 在计算前，先更新所有持仓的最新价格
        for pos in pm.get_all_positions():
            price_data = self.context.data_provider.get_current_price(pos.symbol, dt)
            current_price = price_data['current_price'] if price_data else pos.current_price
            pos.update_price(current_price)
        
        # 更新财务信息
        self.context.portfolio.update_financials(self.context.position_manager)
        net_worth = self.context.portfolio.net_worth
        
        self.context.intraday_equity_history.append({
            'time': dt.strftime('%H:%M:%S'),
            'net_worth': net_worth,
        })
        
        benchmark_symbol = self.context.benchmark_manager.benchmark_symbol
        if (benchmark_symbol and
            self._benchmark_start_of_day_price and
            self._strategy_start_of_day_value):
            price_data = self.context.data_provider.get_current_price(benchmark_symbol, dt)
            if price_data and price_data.get('current_price'):
                current_benchmark_price = price_data['current_price']
                if self._benchmark_start_of_day_price > 0:
                    current_benchmark_value = (self._strategy_start_of_day_value *
                                               (current_benchmark_price / self._benchmark_start_of_day_price))
                    self.context.intraday_benchmark_history.append({
                        'time': dt.strftime('%H:%M:%S'),
                        'value': current_benchmark_value,
                    })
        return True