# qtrader/runner/backtest_runner.py

from qtrader.core.engine import Engine
from typing import Optional
import sys
import traceback
import logging

# Configure a simple logger for the runner
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BacktestRunner:
    """
    为 QTrader 引擎提供一个高级的、程序化的运行接口 (Runner)。

    此类封装了调用 `Engine` 的三种核心模式（全新运行、恢复、分叉）的
    标准流程，并提供了统一的日志记录和异常处理。它的主要目的是让用户
    可以方便地在自己的 Python 脚本（例如 `run_backtest.py`）中以编
    程方式启动、控制和集成 QTrader 的核心功能，而无需直接与 `Engine`
    的复杂初始化过程交互。

    可以将其视为 QTrader 框架的“官方”入口点或客户端 API。
    """

    @staticmethod
    def run_new(
        config_path: str,
        strategy_path: str,
        data_provider_path: str,
        start_paused: bool = False
    ):
        """
        启动一个全新的运行（回测或模拟交易）。

        这是最常用的模式，用于从头开始执行一个完整的策略回测或启动一个
        全新的模拟交易会话。

        Args:
            config_path (str): 指向 YAML 配置文件的路径。
            strategy_path (str): 指向策略逻辑的 Python 文件路径。
            data_provider_path (str): 指向数据提供者实现的 Python 文件路径。
            start_paused (bool): 若为 True，引擎将在初始化后立即进入暂停状态，
                                 通常用于需要手动启动的调试或监控场景。
        """
        logger.info("=" * 60)
        logger.info("QTrader - 启动全新运行")
        logger.info("=" * 60)
        logger.info(f"配置文件: {config_path}")
        logger.info(f"策略文件: {strategy_path}")
        logger.info(f"数据提供者: {data_provider_path}")
        if start_paused:
            logger.info("启动模式: 启动后立即暂停")
        logger.info("=" * 60)
        try:
            engine = Engine(config_path)
            engine.run(strategy_path, data_provider_path, start_paused=start_paused)
        except Exception as e:
            logger.error(f"\n运行失败: {e}", exc_info=True)

    @staticmethod
    def run_resume(
        state_file: str,
        config_path: Optional[str] = None,
        data_provider_path: Optional[str] = None,
        start_paused: bool = False
    ):
        """
        从一个由“暂停”操作生成的状态文件恢复运行。

        此方法用于继续一个之前被手动暂停的会话。它会加载 `.pkl` 状态文件，
        重建当时的完整市场和策略状态，然后从中断点无缝地继续执行。

        注意：此方法不能用于恢复由程序崩溃或正常结束时生成的状态文件。

        Args:
            state_file (str): 由 `engine.pause()` 生成的 `.pkl` 状态文件路径。
            config_path (Optional[str]): (可选) 提供一个新的配置文件路径，
                                         可以覆盖原配置中的某些参数（例如日志级别）。
            data_provider_path (Optional[str]): (可选) 提供一个新的数据提供者，
                                                例如从实时数据切换到修复后的历史数据。
            start_paused (bool): (可选) 若为 True，在恢复加载后再次立即暂停。
        """
        logger.info("=" * 60)
        logger.info("QTrader - 恢复中断的运行")
        logger.info("=" * 60)
        logger.info(f"状态文件: {state_file}")
        if config_path: logger.info(f"覆盖配置文件: {config_path}")
        if data_provider_path: logger.info(f"覆盖数据提供者: {data_provider_path}")
        if start_paused: logger.info("启动模式: 恢复后立即暂停")
        logger.info("=" * 60)
        try:
            engine = Engine.load_from_state(state_file, config_path)
            engine.resume(data_provider_path, start_paused=start_paused)
        except Exception as e:
            logger.error(f"\n运行失败: {e}", exc_info=True)

    @staticmethod
    def run_fork(
        state_file: str,
        strategy_path: str,
        config_path: Optional[str] = None,
        data_provider_path: Optional[str] = None,
        reinitialize: bool = True,
        start_paused: bool = False
    ):
        """
        从一个历史状态文件分叉（Fork）出一个新的运行实例。

        分叉是一种强大的“假设分析”工具。它加载一个过去的状态（例如，回测
        到一半的某个时间点），保留该时间点之前的所有历史和持仓，但从该点
        开始应用一个全新的策略逻辑或配置，然后继续运行。

        使用场景:
        - 测试不同参数对策略后半段表现的影响。
        - 在某个关键市场事件发生时，对比不同策略的应对。

        Args:
            state_file (str): 用于分叉的源 `.pkl` 状态文件路径。
            strategy_path (str): **必须提供**一个新的策略文件路径。
            config_path (Optional[str]): (可选) 提供新的配置文件。
            data_provider_path (Optional[str]): (可选) 提供新的数据提供者。
            reinitialize (bool): (可选) 若为 True，新策略的 `initialize()` 方法
                                 将被调用；若为 False，则会尝试保留旧策略的
                                 `user_data`，适用于仅微调策略逻辑的场景。
            start_paused (bool): (可选) 若为 True，在分叉加载后立即暂停。
        """
        logger.info("=" * 60)
        logger.info("QTrader - 从快照分叉运行")
        logger.info("=" * 60)
        logger.info(f"状态文件: {state_file}")
        logger.info(f"新策略文件: {strategy_path}")
        if config_path: logger.info(f"覆盖配置文件: {config_path}")
        if data_provider_path: logger.info(f"新数据提供者: {data_provider_path}")
        logger.info(f"重新初始化策略: {'是' if reinitialize else '否'}")
        if start_paused: logger.info("启动模式: 分叉后立即暂停")
        logger.info("=" * 60)
        
        try:
            engine = Engine.load_from_state(state_file, config_path)
            engine.run_fork(
                strategy_path=strategy_path,
                data_provider_path=data_provider_path,
                reinitialize=reinitialize,
                start_paused=start_paused
            )
        except Exception as e:
            logger.error(f"\n运行失败: {e}", exc_info=True)