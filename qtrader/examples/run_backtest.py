# examples/run_backtest.py
# python -m examples.run_backtest

"""
QTrader 运行示例 (V5 - 程序化接口)
"""

from qtrader.runner.backtest_runner import BacktestRunner
import os

if __name__ == '__main__':
    # 获取当前脚本目录，方便定位文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # --- 文件路径配置 ---
    config_path = os.path.join(current_dir, 'strategies', 'backtest.yaml')
    config_simulation_path = os.path.join(current_dir, 'strategies', 'backtest_simulation.yaml')
    strategy_path = os.path.join(current_dir, 'strategies', 'simple_ma.py')
    # 注意: 示例中的 data_provider_path 指向了 examples 目录下的文件
    data_provider_path = os.path.join(current_dir, 'strategies','mock_api_provider.py')
    
    # 假设这是一个由暂停操作生成的状态文件
    # 请根据您实际生成的文件路径进行修改
    # 示例路径: <策略名>/backtest/<时间戳>/<策略名>_pause.pkl
    pause_pkl_path = os.path.join(current_dir, 'strategies', 'simple_ma', 'backtest', '20251019_001346', 'MyStrategy_pause.pkl')

    # --- 选择一种模式运行 (取消注释您想运行的代码块) ---

    # 模式1: 启动一个全新的回测
    # print("--- 模式1: 启动全新回测 ---")
    # BacktestRunner.run_new(
    #     config_path=config_path,  # 配置文件
    #     strategy_path=strategy_path,  # 策略文件
    #     data_provider_path=data_provider_path, # 数据源文件
    #     start_paused=True  # 开始后，是否暂停回测（可从WEBUI继续）
    # )


    # 模式2: 恢复一个已暂停的回测
    print("\n--- 模式2: 恢复回测 (直接运行) ---")
    BacktestRunner.run_resume(
        state_file=pause_pkl_path,
        # config_path=config_path,   # 可以换成一个新的配置文件，可选
        # data_provider_path=data_provider_path,  # 可以换成一个新的数据源，可选
        start_paused=True     # 恢复后是否立即暂停，可选，默认False
    )

    # 模式2: 示例
    # print("\n--- 模式3: 恢复回测 (启动即暂停) ---")
    # if os.path.exists(pause_pkl_path):
    #     BacktestRunner.run_resume(
    #         state_file=pause_pkl_path,
    #         config_path=config_path,
    #         start_paused=True 
    #     )
    # else:
    #     print(f"错误: 状态文件不存在于 '{pause_pkl_path}'")
    #     print("请先运行一次全新回测，并在监控页面点击'暂停'以生成可恢复的状态文件。")


    # 模式4: 从一个状态文件分叉出一个新的回测
    # print("\n--- 模式4: 分叉回测 ---")
    # if os.path.exists(pause_pkl_path):
    #     BacktestRunner.run_fork(
    #         state_file=pause_pkl_path,
    #         strategy_path=strategy_path, # 可以换成一个新的策略文件，可选
    #         config_path=config_path,   # 可以换成一个新的配置文件，可选
    #         data_provider_path=data_provider_path,  # 可以换成一个新的数据源，可选
    #         start_paused=True # 分叉后也可以立即暂停，可选，默认False
    #         no_reinit = False  # 是否在分叉时重新初始化，可选，默认False
    #     )
    # else:
    #      print(f"错误: 状态文件不存在于 '{pause_pkl_path}'")