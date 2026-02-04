# qtrader/core/workspace_manager.py

import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import logging
from ..analysis.performance import PerformanceAnalyzer

class WorkspaceManager:
    """
    管理每次回测或模拟交易的工作区。

    它负责创建独立的目录来存放每次运行所产生的所有文件，
    包括日志、状态快照、配置文件副本以及最终的报告和数据导出，
    从而确保每次运行都是自包含且可追溯的。
    """

    def __init__(
        self,
        strategy_path: str,
        data_provider_path: str,
        config: Dict[str, Any],
        logger: logging.Logger,
        mode: str = 'backtest',
        workspace_dir_override: Optional[str] = None,
        config_path: Optional[str] = None
    ):
        """
        Args:
           strategy_path (str): 策略文件的路径。
           data_provider_path (str): 数据提供者文件的路径。
           config (Dict[str, Any]): 配置字典。
           logger (logging.Logger): 日志记录器实例。
           mode (str): 运行模式 ('backtest' or 'simulation')。
           workspace_dir_override (Optional[str]): 如果提供，则直接使用此路径作为工作区，
               而不是创建一个新的带时间戳的目录。
           config_path (Optional[str]): 配置文件路径，用于创建配置快照。
        """
        self.strategy_path = Path(strategy_path).resolve()
        self.data_provider_path = Path(data_provider_path).resolve()
        self.config = config
        self.config_path = Path(config_path).resolve() if config_path else None
        self.logger = logger
        self.mode = mode
        
        if workspace_dir_override:
            self.workspace_dir = Path(workspace_dir_override).resolve()
            self.logger.info(f"附加到现有工作区: {self.workspace_dir}")
            self._create_snapshots()

        else:
            self.strategy_name = self.strategy_path.stem
            
            workspace_config = config.get('workspace', {})
            root_dir = workspace_config.get('root_dir')
            
            if root_dir:
                self.root_dir = Path(root_dir).resolve()
            else:
                # 默认在策略文件旁边创建与策略同名的目录作为根工作区
                self.root_dir = self.strategy_path.parent / self.strategy_name
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            self.workspace_dir = self.root_dir / self.mode / timestamp
            
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            
            self.logger.info(f"工作区已创建: {self.workspace_dir}")
            
            self._create_snapshots()
    
    def _create_snapshots(self):
        """
        为策略代码、配置文件和数据提供者创建快照。
        
        这确保了每次运行的可复现性。如果目标快照文件与源文件相同，则跳过复制。
        """
        workspace_config = self.config.get('workspace', {})
        
        if workspace_config.get('create_code_snapshot', True) and self.strategy_path:
            snapshot_code = self.workspace_dir / "snapshot_code.py"
            try:
                # 仅当快照文件不存在，或快照文件与源文件不是同一个文件时，才执行复制
                if not snapshot_code.exists() or not snapshot_code.samefile(self.strategy_path):
                    shutil.copy2(self.strategy_path, snapshot_code)
                    self.logger.info(f"策略代码快照已创建/更新: {snapshot_code.name}")
            except (FileNotFoundError, shutil.SameFileError):
                pass
            except Exception as e:
                self.logger.warning(f"创建代码快照时发生未知错误: {e}")
        
        if workspace_config.get('create_config_snapshot', True) and self.config_path:
            snapshot_config = self.workspace_dir / "snapshot_config.yaml"
            try:
                # 直接复制配置文件，保持原始格式（不使用 yaml.dump 重新序列化）
                if not snapshot_config.exists() or not snapshot_config.samefile(self.config_path):
                    shutil.copy2(self.config_path, snapshot_config)
                    self.logger.info(f"配置快照已创建/更新: {snapshot_config.name}")
            except (FileNotFoundError, shutil.SameFileError):
                pass
            except Exception as e:
                self.logger.warning(f"创建配置快照失败: {e}")
        
        if (workspace_config.get('create_data_provider_snapshot', True) and
            self.data_provider_path):
            snapshot_data_provider = self.workspace_dir / "snapshot_data_provider.py"
            try:
                # 仅当快照文件不存在，或快照文件与源文件不是同一个文件时，才执行复制
                if (not snapshot_data_provider.exists() or
                    not snapshot_data_provider.samefile(self.data_provider_path)):
                    shutil.copy2(self.data_provider_path, snapshot_data_provider)
                    self.logger.info(f"数据提供者快照已创建/更新: {snapshot_data_provider.name}")
            except (FileNotFoundError, shutil.SameFileError):
                pass
            except Exception as e:
                self.logger.warning(f"创建数据提供者快照时发生未知错误: {e}")
    
    def get_path(self, filename: str) -> Path:
        """
        获取工作区内指定文件名的完整路径。

        Args:
            filename (str): 目标文件名。

        Returns:
            Path: 文件的完整 `pathlib.Path` 对象。
        """
        return self.workspace_dir / filename
    
    @property
    def log_file(self) -> Path:
        """获取日志文件的路径。"""
        return self.get_path(f"{self.mode}.log")
    
    @property
    def state_file(self) -> Path:
        """获取状态文件（.pkl）的路径。"""
        return self.get_path("state.pkl")
    
    @property
    def report_file(self) -> Path:
        """获取 HTML 报告文件的路径。"""
        return self.get_path("report.html")
    
    @property
    def equity_csv(self) -> Path:
        """获取权益曲线 CSV 文件的路径。"""
        return self.get_path("equity.csv")
    
    @property
    def positions_csv(self) -> Path:
        """获取每日持仓 CSV 文件的路径。"""
        return self.get_path("daily_positions.csv")
    
    @property
    def orders_csv(self) -> Path:
        """获取订单流水 CSV 文件的路径。"""
        return self.get_path("orders.csv")
    
    @property
    def pnl_pairs_csv(self) -> Path:
        """获取盈亏交易对 CSV 文件的路径。"""
        return self.get_path("pnl_pairs.csv")
    
    def export_csv_files(self, context):
        """
        将回测或模拟交易的结果数据导出为 CSV 文件。

        Args:
            context (Context): 包含所有运行时数据的全局上下文对象。
        """
        import pandas as pd
        
        # 1. 权益曲线
        if context.portfolio.history:
            equity_df = pd.DataFrame(context.portfolio.history)
            equity_df.to_csv(self.equity_csv, index=False, encoding='utf-8-sig')
            self.logger.info(f"权益曲线已导出: {self.equity_csv.name}")
        
        # 2. 每日持仓
        if context.position_manager.daily_snapshots:
            positions_data = []
            for snapshot in context.position_manager.daily_snapshots:
                date = snapshot['date']
                for pos in snapshot['positions']:
                    positions_data.append({
                        'date': date,
                        **pos
                    })
            if positions_data:
                positions_df = pd.DataFrame(positions_data)
                positions_df.to_csv(self.positions_csv, index=False, encoding='utf-8-sig')
                self.logger.info(f"每日持仓已导出: {self.positions_csv.name}")
        
        # 3. 订单流水
        all_orders = context.order_manager.get_all_orders()
        if all_orders:
            orders_data = []
            for order in all_orders:
                orders_data.append({
                    'id': order.id,
                    'symbol': order.symbol,
                    'symbol_name': order.symbol_name,
                    'side': order.side.value,
                    'amount': order.amount,
                    'order_type': order.order_type.value,
                    'limit_price': order.limit_price,
                    'status': order.status.value,
                    'created_time': order.created_time.isoformat() if order.created_time else None,
                    'filled_time': order.filled_time.isoformat() if order.filled_time else None,
                    'filled_price': order.filled_price,
                    'commission': order.commission,
                })
            orders_df = pd.DataFrame(orders_data)
            orders_df.to_csv(self.orders_csv, index=False, encoding='utf-8-sig')
            self.logger.info(f"订单流水已导出: {self.orders_csv.name}")
        
        # 4. 交易对
        analyzer = PerformanceAnalyzer(context)
        if not analyzer.pnl_df.empty:
            pnl_df = analyzer.pnl_df.copy()
            # 格式化时间列
            if 'entry_time' in pnl_df.columns:
                pnl_df['entry_time'] = pnl_df['entry_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            if 'exit_time' in pnl_df.columns:
                pnl_df['exit_time'] = pnl_df['exit_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            pnl_df.to_csv(self.pnl_pairs_csv, index=False, encoding='utf-8-sig')
            self.logger.info(f"交易对已导出: {self.pnl_pairs_csv.name}")