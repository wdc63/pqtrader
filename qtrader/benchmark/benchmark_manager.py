# qtrader/benchmark/benchmark_manager.py

from typing import List, Dict, Optional
from ..core.context import Context
from datetime import datetime

class BenchmarkManager:
    """
    管理回测或交易过程中的基准（Benchmark）。

    负责初始化基准、每日更新基准数据，并提供获取基准收益和历史数据的接口。
    """
    def __init__(self, context: Context, config: Dict):
        self.context = context
        self.config = config
        self.benchmark_symbol: Optional[str] = None
        self.benchmark_name: Optional[str] = None
        self.benchmark_history: List[Dict] = []
        self.initial_value: Optional[float] = None

    def initialize(self, config: Dict):
        """
        根据配置初始化基准。

        Args:
            config (Dict): 基准相关的配置。
        """
        try:
            symbol = config.get('symbol')
            if not symbol:
                self.context.logger.info("未在配置中指定基准 symbol，基准功能将禁用。")
                self.benchmark_symbol = None
                return

            self.benchmark_symbol = symbol
            
            # 尝试从数据提供者获取基准的正式名称
            start_date_str = self.context.start_date
            symbol_info = self.context.data_provider.get_symbol_info(
                self.benchmark_symbol, start_date_str
            )
            
            if symbol_info and symbol_info.get('symbol_name'):
                self.benchmark_name = symbol_info['symbol_name']
            else:
                self.benchmark_name = config.get('name', self.benchmark_symbol)
            
            # 获取回测开始日期的基准价格作为初始值
            start_dt_str = self.context.start_date + ' 00:00:00'
            start_dt = datetime.strptime(start_dt_str, '%Y-%m-%d %H:%M:%S')
            price_data = self.context.data_provider.get_current_price(
                self.benchmark_symbol, start_dt
            )
            
            if (price_data and
                'current_price' in price_data and
                price_data['current_price'] is not None):
                self.initial_value = price_data['current_price']
            else:
                raise ValueError(f"无法获取基准 {self.benchmark_symbol} 的初始价格。")
            
            self.context.logger.info(
                f"基准初始化成功: {self.benchmark_name} ({self.benchmark_symbol}), "
                f"初始价格: {self.initial_value:.2f}"
            )

        except Exception as e:
            self.context.logger.warning(
                f"基准初始化失败，错误: {e}。回测将继续，但基准功能将被禁用。"
            )
            self.benchmark_symbol = None
            self.benchmark_name = None
            self.initial_value = None

    def update_daily(self):
        """
        在每个交易日结束时更新基准的收盘价和收益率。
        """
        if not self.benchmark_symbol:
            return
        date_str = self.context.current_dt.strftime('%Y-%m-%d')
        
        try:
            price_data = self.context.data_provider.get_current_price(
                self.benchmark_symbol, self.context.current_dt
            )
            
            if (price_data and
                'current_price' in price_data and
                price_data['current_price'] is not None):
                close_price = price_data['current_price']
                returns = (close_price - self.initial_value) / self.initial_value if self.initial_value else 0
                value = self.context.portfolio.initial_cash * (1 + returns)
                
                self.benchmark_history.append({
                    'date': date_str,
                    'close_price': close_price,
                    'returns': returns,
                    'value': value,
                })
            else:
                raise ValueError("返回的数据格式不正确或价格为空。")
            
        except Exception as e:
            self.context.logger.warning(
                f"无法获取基准 {self.benchmark_symbol} 在 {date_str} 的数据，错误: {e}。"
                f"当天基准数据将被跳过。"
            )
    def get_current_returns(self) -> float:
        """获取当前累计的基准收益率。"""
        return self.benchmark_history[-1]['returns'] if self.benchmark_history else 0.0

    def get_current_value(self) -> float:
        """获取当前基准的等价市值。"""
        return self.benchmark_history[-1]['value'] if self.benchmark_history else self.context.portfolio.initial_cash

    def get_benchmark_data(self) -> List[Dict]:
        """获取完整的基准历史数据。"""
        return self.benchmark_history