# examples/simple_ma/run.py

import os
import sys
import datetime
import time
import threading

# --- 路径设置 ---
# 为了能直接运行此脚本，我们需要将项目根目录添加到 Python 路径中
# 这样我们就可以在不安装 'qtrader' 的情况下导入它
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from time_patcher import TimePatcher
from qtrader.core.engine import Engine
from qtrader.runner.backtest_runner import BacktestRunner


def run_qtrader_simulation(config_path, strategy_path, data_provider_path):
    """在一个单独的线程中运行QTrader模拟"""
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


def main():
    """主函数，用于选择并运行不同模式"""
    # 获取当前脚本目录，方便定位文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # --- 文件路径配置 ---
    config_backtest_path = os.path.join(current_dir, 'config_backtest.yaml')
    config_simulation_path = os.path.join(current_dir, 'config_simulation.yaml')
    strategy_path = os.path.join(current_dir, 'strategy.py')
    # 获取strategy_path的文件名不带后缀名
    strategy_name = os.path.splitext(os.path.basename(strategy_path))[0]
    data_provider_path = os.path.join(current_dir, 'data_provider.py')

    # --- 状态文件路径 (用于恢复/分叉) ---
    # 注意: 这是一个示例路径。请在运行模式3或4之前，
    # 先运行一次模式1，并在WEB UI中点击“暂停”以生成状态文件。
    # 然后，将下面的路径修改为您实际生成的状态文件路径。
    # 默认路径格式: <策略名>/<模式>/<时间戳>/<策略名>_pause.pkl
    pause_pkl_path = os.path.join(current_dir, strategy_name,'backtest', '20251020_133210', 'MyStrategy_pause.pkl')

    # print("="*80)
    # print("QTrader 运行入口")
    # print("请编辑此脚本 (examples/simple_ma/run.py)，取消注释您想运行的模式。")
    # print("="*80)

    # ==============================================================================
    # 模式1: 启动一个全新的回测
    # ==============================================================================
    # print("--- 模式1: 启动全新回测 ---")
    # BacktestRunner.run_new(
    #     config_path=config_backtest_path,
    #     strategy_path=strategy_path,
    #     data_provider_path=data_provider_path,
    #     start_paused=True  # 开始后暂停，可从WEB UI继续
    # )

    # ==============================================================================
    # 模式2: 启动一个时间加速的模拟盘
    # ==============================================================================
    print("\n--- 模式2: 启动时间加速模拟盘 ---")
    
    # --- 时间加速配置 ---
    fake_start_time = datetime.datetime(2025, 10, 13, 9, 0, 0)
    time_speed_multiplier = 600  # 真实世界的1秒 = 模拟世界的600秒 (10分钟)
    
    print(f"伪造启动时间: {fake_start_time}")
    print(f"时间流速倍率: {time_speed_multiplier}x")
    
    # --- 猴子补丁：禁用子线程中的信号处理 ---
    print("[Main Thread] 正在应用猴子补丁以禁用QTrader引擎中的信号处理器。")
    def _do_nothing_signal_handler(self):
        logger = getattr(self.context, 'logger', None) if getattr(self, 'context', None) else None
        if logger:
            logger.info("在非主线程中跳过信号处理器注册。")
        else:
            print("在非主线程中跳过信号处理器注册。")
    
    Engine._register_signal_handlers = _do_nothing_signal_handler
    
    # --- 需要为时间加速打补丁的模块 ---
    QTRADER_CORE_MODULES_TO_PATCH = [
        'qtrader.core.engine', 'qtrader.core.scheduler', 'qtrader.core.time_manager',
        'qtrader.analysis.integrated_server', 'qtrader.core.lifecycle', 'qtrader.trading.order',
        'qtrader.trading.position', 'qtrader.trading.matching_engine', 'qtrader.trading.order_manager',
    ]
    
    # 使用 TimePatcher 并启动 QTrader 线程
    with TimePatcher(
        initial_datetime=fake_start_time,
        time_speed=time_speed_multiplier,
        target_module_names=QTRADER_CORE_MODULES_TO_PATCH
    ) as patcher:
        qtrader_thread = threading.Thread(
            target=run_qtrader_simulation,
            args=(config_simulation_path, strategy_path, data_provider_path)
        )
        qtrader_thread.start()
    
        while qtrader_thread.is_alive():
            try:
                current_fake_time = datetime.datetime.now()
                print(f"模拟时间: {current_fake_time.strftime('%Y-%m-%d %H:%M:%S')}", end='\r')
                time.sleep(1)
            except KeyboardInterrupt:
                print("\n收到退出指令，正在尝试停止 QTrader...")
                break
        
        qtrader_thread.join()
    
    print("\n--- 模拟盘运行结束，时间补丁已自动移除 ---")

    # ==============================================================================
    # 模式3: 恢复一个已暂停的回测
    # ==============================================================================
    # print("\n--- 模式3: 恢复回测 ---")
    # if not os.path.exists(pause_pkl_path):
    #     print(f"错误: 状态文件不存在于 '{pause_pkl_path}'")
    #     print("请先运行模式1，并在WEB UI中暂停以生成状态文件，然后更新本脚本中的路径。")
    # else:
    #     BacktestRunner.run_resume(
    #         state_file=pause_pkl_path,
    #         # config_path=config_backtest_path,      # 可选，使用新的配置文件
    #         # data_provider_path=data_provider_path, # 可选，使用新的数据源
    #         start_paused=True                        # 可选，恢复后立即暂停
    #     )

    # ==============================================================================
    # 模式4: 从一个状态文件分叉出一个新的回测
    # ==============================================================================
    # print("\n--- 模式4: 分叉回测 ---")
    # if not os.path.exists(pause_pkl_path):
    #     print(f"错误: 状态文件不存在于 '{pause_pkl_path}'")
    #     print("请先运行模式1，并在WEB UI中暂停以生成状态文件，然后更新本脚本中的路径。")
    # else:
    #     BacktestRunner.run_fork(
    #         state_file=pause_pkl_path,
    #         strategy_path=strategy_path,             # 可选，使用新的策略文件
    #         config_path=config_simulation_path,        # 可选，使用新的配置文件
    #         # data_provider_path=data_provider_path, # 可选，使用新的数据源
    #         start_paused=True                        # 可选，分叉后立即暂停
    #     )


if __name__ == '__main__':
    main()