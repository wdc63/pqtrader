# qtrader/core/lifecycle.py

from typing import Optional
import time
import traceback # 引入 traceback 模块以打印详细的错误信息
from qtrader.core.context import Context
from qtrader.strategy.base import Strategy

class LifecycleManager:
    """
    管理策略的生命周期事件回调。

    该管理器的核心职责是安全地调用策略中定义的生命周期钩子方法
    （如 `initialize`, `handle_bar` 等），并内置了两种关键的保护机制：
    1.  **异常隔离**: 捕获并记录策略代码中的所有异常，防止其影响框架主体的稳定性。
    2.  **阻塞检测**: 在模拟交易模式下，监控钩子方法的执行时间，防止用户代码的长时间阻塞导致系统时间与真实时间脱节。
    """

    def __init__(self, context: Context):
        self.context = context
        self.strategy: Optional[Strategy] = None
        self.block_threshold_seconds = self.context.config.get('engine', {}).get(
            'block_threshold_seconds', 5
        )

    def register_strategy(self, strategy: Strategy):
        self.strategy = strategy

    def _call_hook(self, hook_name: str):
        """
        安全地调用策略的指定钩子方法。

        该方法集成了异常捕获和执行超时监控，以确保用户策略的稳定性。
        """
        if self.strategy is None:
            self.context.logger.error("错误: 策略对象未注册。")
            return

        hook_method = getattr(self.strategy, hook_name, None)
        if callable(hook_method):
            
            is_simulation = self.context.mode == 'simulation'
            time_before = time.monotonic() if is_simulation else 0
            
            # --- 异常隔离防火墙 ---
            # 使用 try...except 块包裹用户策略代码，防止其异常导致整个框架崩溃。
            try:
                self.context.logger.debug(f"调用策略钩子: {hook_name}()")
                hook_method(self.context)
            
            except Exception as e:
                # 捕获策略代码中的异常，记录详细日志，并设置错误标志，但不会中断引擎。
                error_trace = traceback.format_exc()
                self.context.logger.error(f"执行策略钩子 {hook_name}() 时发生严重错误: {e}")
                self.context.logger.error(f"详细错误追踪:\n{error_trace}")
                self.context.strategy_error_today = True
                return

            # --- 阻塞看门狗 (仅在模拟盘模式下) ---
            # 检测策略代码是否执行超时，防止其阻塞导致与真实时间脱节。
            if is_simulation:
                time_after = time.monotonic()
                duration = time_after - time_before
                
                if duration > self.block_threshold_seconds:
                    self.context.logger.warning(
                        f"检测到策略钩子 '{hook_name}' 严重阻塞 {duration:.2f} 秒！"
                    )
                    self.context.logger.warning("已触发时间同步请求，系统将自动校准...")
                    self.context.resync_requested = True
    
    def call_initialize(self):
        self.context.is_initializing = True
        try:
            self._call_hook('initialize')
        finally:
            self.context.is_initializing = False

    def call_before_trading(self):
        self._call_hook('before_trading')

    def call_handle_bar(self):
        self._call_hook('handle_bar')

    def call_after_trading(self):
        self._call_hook('after_trading')

    def call_broker_settle(self):
        self._call_hook('broker_settle')

    def call_on_end(self):
        self._call_hook('on_end')
