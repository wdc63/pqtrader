# examples/run_simulation.py

"""
QTrader 模拟盘运行示例 (V6 - 时间加速)

此脚本演示了如何使用 TimePatcher 来“欺骗”QTrader的simulation模式，
使其在一个加速的时间流中运行。
"""

from qtrader.runner.backtest_runner import BacktestRunner
import os
import datetime
import time
import threading

# [MODIFIED] 导入升级后的 TimePatcher
from time_patcher import TimePatcher

# [MODIFIED] 导入 Engine 类用于猴子补丁
from qtrader.core.engine import Engine

def run_qtrader_simulation(config_path, strategy_path, data_provider_path):
    """在一个单独的函数中运行QTrader，以便于在线程中调用"""
    print("[QTrader Runner] 线程已启动，正在初始化并运行 QTrader...")
    try:
        BacktestRunner.run_new(
            config_path=config_path,
            strategy_path=strategy_path,
            data_provider_path=data_provider_path,
            start_paused=False
        )
    except Exception as e:
        print(f"[QTrader Runner] 运行出错: {e}")
    print("[QTrader Runner] QTrader 运行结束。")


if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # --- 文件路径配置 ---
    # 重要: 请确保此处的配置文件中 engine.mode 设置为 'simulation'
    config_path = os.path.join(current_dir, 'strategies', 'backtest_simulation.yaml')
    strategy_path = os.path.join(current_dir, 'strategies', 'simple_ma.py')
    data_provider_path = os.path.join(current_dir, 'strategies','mock_api_provider.py')
    
    # --- 时间加速配置 ---
    
    # 1. 设置一个伪造的启动时间
    fake_start_time = datetime.datetime(2025, 10, 13, 9, 0, 0)
    
    # 2. 设置时间流逝的速度倍率
    #    例如: 60.0 意味着真实世界的1秒钟，等于模拟世界中的60秒（1分钟）
    #    设置为 3600.0 则 1秒 = 1小时
    time_speed_multiplier = 600

    print("="*60)
    print("--- 启动加速模拟盘测试 ---")
    print(f"伪造启动时间: {fake_start_time}")
    print(f"时间流速倍率: {time_speed_multiplier}x")
    print("="*60)

    # --- 猴子补丁：禁用子线程中的信号处理 ---
    # 解释: Python的signal模块只能在主线程中使用。QTrader引擎尝试注册
    # SIGINT (Ctrl+C)处理器，但在子线程中会失败。通过这个补丁，我们
    # 将注册函数替换为一个空函数，从而在不修改qtrader库代码的情况下
    # 绕过这个问题。
    print("[Main Thread] Applying monkey patch to disable signal handlers in QTrader engine.")
    def _do_nothing_signal_handler(self):
        # 尝试使用引擎的日志记录器（如果存在），以便记录此操作
        # [FIX] 使用 self.context.logger 而不是 self.temp_logger。
        # temp_logger 是在 context 和完整日志系统初始化之前使用的临时记录器。
        # 此时完整的日志记录器 self.context.logger 已经可用，它包含了注入 sim_time 所需的上下文过滤器。
        logger = getattr(self.context, 'logger', None) if getattr(self, 'context', None) else None
        if logger:
            logger.info("Signal handlers registration skipped in non-main thread.")
        else:
            # Fallback in case context or logger is not yet available
            print("Signal handlers registration skipped in non-main thread.")

    Engine._register_signal_handlers = _do_nothing_signal_handler


    # [MODIFIED] 定义需要被打补丁的所有核心模块
    # 确保所有调用 datetime.now() 的地方都被我们的 MockDateTime 替换
    QTRADER_CORE_MODULES_TO_PATCH = [
        'qtrader.core.engine',
        'qtrader.core.scheduler',
        'qtrader.core.time_manager',
        'qtrader.analysis.integrated_server',
        'qtrader.core.lifecycle'
    ]

    # 使用 TimePatcher 并启动 QTrader 线程
    with TimePatcher(
        initial_datetime=fake_start_time,
        time_speed=time_speed_multiplier,
        target_module_names=QTRADER_CORE_MODULES_TO_PATCH
    ) as patcher:
        
        # 创建并启动 QTrader 线程
        qtrader_thread = threading.Thread(
            target=run_qtrader_simulation,
            args=(config_path, strategy_path, data_provider_path)
        )
        qtrader_thread.start()

        # 主线程将保持运行，以维持时间补丁的有效性
        # 我们可以通过循环打印当前伪造时间来观察时间加速的效果
        while qtrader_thread.is_alive():
            try:
                # 获取并打印当前的伪造时间
                current_fake_time = datetime.datetime.now()
                print(f"模拟时间: {current_fake_time.strftime('%Y-%m-%d %H:%M:%S')}", end='\r')
                time.sleep(1) # 每秒更新一次
            except KeyboardInterrupt:
                print("\n收到退出指令，正在尝试停止 QTrader...")
                # 这里可以添加通过API调用 engine.stop() 的逻辑（如果未来支持）
                break
        
        # 等待 QTrader 线程完全结束
        qtrader_thread.join()

    print("\n--- 模拟盘运行结束，时间补丁已自动移除 ---")
    print(f"真实时间: {datetime.datetime.now()}")