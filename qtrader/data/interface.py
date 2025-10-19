# qtrader/data/interface.py

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime

class AbstractDataProvider(ABC):
    """
    数据提供者抽象基类 (Abstract Base Class for Data Providers)。

    本接口定义了 QTrader 核心引擎与所有外部数据源之间的标准“契约”。
    任何想要接入 QTrader 的数据源（无论是来自本地文件、数据库还是实时 API），
    都必须创建一个继承自本类的子类，并完整实现其所有抽象方法。

    这种设计遵循了“依赖倒置原则”，使得核心引擎不依赖于任何具体的数据
    实现，从而可以轻松地替换和扩展数据源，而无需修改核心逻辑。
    """
    
    @abstractmethod
    def get_trading_calendar(self, start: str, end: str) -> List[str]:
        """
        获取指定日期范围内的所有交易日。

        此方法是回测时间循环的基础。`Scheduler` 在回测开始时会调用此方法
        一次，以确定需要遍历的所有交易日。

        Args:
            start (str): 开始日期 (格式: 'YYYY-MM-DD')。
            end (str): 结束日期 (格式: 'YYYY-MM-DD')。

        Returns:
            List[str]: 一个按升序排列的交易日字符串列表 (['YYYY-MM-DD', ...])。
                       如果指定范围内没有交易日，应返回空列表。
        """
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str, dt: datetime) -> Optional[Dict]:
        """
        获取指定证券在特定时间点的实时价格快照。

        这是框架中被调用最频繁的方法之一。`MatchingEngine` 在每次尝试撮合
        订单时，以及在每日结算更新持仓市值时，都会调用此方法来获取最新价格。

        Args:
            symbol (str): 证券代码。
            dt (datetime): 查询的时间点。

        Returns:
            Optional[Dict]: 一个包含价格信息的字典。如果此刻该证券无有效价格数据
                            （例如，未上市或数据缺失），应返回 None。
                            字典结构:
                            {
                                'current_price': float,  # 当前价 (必须提供)
                                'ask1': float,           # 卖一价 (可选, 用于更精确的市价单撮合)
                                'bid1': float,           # 买一价 (可选, 用于更精确的市价单撮合)
                                'high_limit': float,     # 当日涨停价 (可选, 用于风控)
                                'low_limit': float,      # 当日跌停价 (可选, 用于风控)
                            }
        """
        pass
    
    @abstractmethod
    def get_symbol_info(self, symbol: str, date: str) -> Optional[Dict]:
        """
        获取指定证券在特定日期的静态信息。

        `MatchingEngine` 在处理订单前会调用此方法，以检查诸如停牌等状态，
        避免在不应交易的证券上下单。

        Args:
            symbol (str): 证券代码。
            date (str): 查询的日期 (格式: 'YYYY-MM-DD')。

        Returns:
            Optional[Dict]: 一个包含静态信息的字典。如果无该证券信息，返回 None。
                            字典结构:
                            {
                                'symbol_name': str,  # 证券的中文或英文名称
                                'is_suspended': bool, # 在 `date` 这一天是否处于停牌状态
                            }
        """
        pass