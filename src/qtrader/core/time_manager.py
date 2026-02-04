# qtrader/core/time_manager.py

from datetime import datetime, time
from typing import List
from ..core.context import Context

class TimeManager:
    """
    时间管理器，提供所有与交易时间、日期和日历相关的功能。

    它依赖于数据提供者来获取交易日历，并根据配置来确定交易时段。
    """

    def __init__(self, context: Context):
        self.context = context
        trading_sessions_config = self.context.config.get('trading_sessions', [])
        
        self.parsed_sessions = [
            (
                datetime.strptime(start, '%H:%M:%S').time(),
                datetime.strptime(end, '%H:%M:%S').time()
            ) for start, end in trading_sessions_config
        ]
        self._calendar_cache = None

    def _get_full_calendar(self):
        """
        获取并缓存完整的交易日历。

        为了提高性能，交易日历在第一次请求时从数据提供者获取，然后缓存起来。
        """
        if self._calendar_cache is None:
            if self.context.data_provider is None:
                raise RuntimeError("未注册数据提供者")
            start = self.context.config.get("start_date", "2005-01-01")
            # 默认获取到明年年底的交易日历，以减少重复获取的次数
            end = self.context.config.get("end_date", f"{datetime.now().year + 1}-12-31")
            calendar_list = self.context.data_provider.get_trading_calendar(start, end)
            self._calendar_cache = set(calendar_list)
        return self._calendar_cache

    def get_trading_days(self, start: str, end: str) -> List[str]:
        """
        获取指定日期范围内的所有交易日。

        Args:
            start (str): 开始日期 (YYYY-MM-DD)。
            end (str): 结束日期 (YYYY-MM-DD)。

        Returns:
            List[str]: 按升序排列的交易日字符串列表。
        """
        full_calendar = self._get_full_calendar()
        # 从缓存的完整日历中筛选出指定范围内的交易日
        trading_days = [day for day in full_calendar if start <= day <= end]
        return sorted(trading_days)

    def is_trading_day(self, dt: datetime) -> bool:
        """
        判断给定日期是否为交易日。

        Args:
            dt (datetime): 需要检查的日期时间对象。

        Returns:
            bool: 如果是交易日，则返回 True，否则返回 False。
        """
        date_str = dt.strftime('%Y-%m-%d')
        return date_str in self._get_full_calendar()

    def is_trading_time(self, dt: datetime) -> bool:
        """
        判断给定的日期和时间是否处于配置的交易时段内。

        Args:
            dt (datetime): 需要检查的日期时间对象。

        Returns:
            bool: 如果是交易时段，则返回 True，否则返回 False。
        """
        if not self.is_trading_day(dt):
            return False

        current_time = dt.time()
        for start_time, end_time in self.parsed_sessions:
            if start_time <= current_time <= end_time:
                return True
        return False