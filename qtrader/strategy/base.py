# qtrader/strategy/base.py

from abc import ABC, abstractmethod
from ..core.context import Context

class Strategy(ABC):
    """
    策略接口抽象基类 (Abstract Base Class for Strategies)。

    这是所有用户自定义策略的模板。用户通过继承此类并实现其定义的生命周期
    钩子方法 (Lifecycle Hooks)，来将自己的交易思想融入 QTrader 框架中。

    框架采用“好莱坞原则”（"Don't call us, we'll call you."），用户只需在
    正确的方法中定义好逻辑，`Scheduler` 会在正确的时间自动调用它们。

    - `initialize`: **必须实现**，用于策略的一次性初始化。
    - 其他钩子 (`before_trading`, `handle_bar`, etc.): **可选实现**，
      用户根据策略的复杂度和需求选择性地覆盖这些方法。
    """

    def __init__(self):
        """
        策略类的构造函数。

        用户可以在此进行不依赖于 `context` 对象的早期初始化。
        """
        pass

    @abstractmethod
    def initialize(self, context: Context):
        """
        策略初始化方法【必须实现】。

        此方法在整个回测或模拟交易生命周期中【仅被调用一次】，在所有
        核心组件（如数据接口、账户等）准备就绪之后，但在第一个交易日
        的 `before_trading` 之前。

        典型用途:
        - 设置策略参数 (例如 `context.user_data['ma_period'] = 20`)。
        - 订阅您感兴趣的证券列表。
        - 预加载所需的部分历史数据用于指标计算。
        - 设置自定义的日志记录。
        """
        pass

    def before_trading(self, context: Context):
        """
        盘前处理方法【可选实现】。

        此方法在【每个交易日】的 `handle_bar` 首次调用之前被触发一次。
        `context.current_dt` 此时通常被设置为配置中的 `before_trading` 时间
        (例如 09:15:00)。

        典型用途:
        - 获取当天的市场行情快照。
        - 基于前一天的收盘数据，计算当天的交易信号。
        - 筛选出当天计划关注或交易的股票池。
        - 提交开盘前下达的限价单。
        """
        pass

    def handle_bar(self, context: Context):
        """
        核心策略逻辑处理方法【可选实现】。

        这是策略最核心的部分。此方法在交易时段内被【反复调用】。调用的
        频率由配置文件中的 `engine.frequency` (`daily` 或 `minute`) 决定。
        `context.current_dt` 会在每次调用时更新为当前的 Bar (K线) 时间。

        典型用途:
        - 获取当前 Bar 的价格和成交量数据。
        - 更新技术指标。
        - 根据交易信号执行判断，并调用 `context.order_manager` 下单。
        - 管理和调整现有持仓。
        """
        pass

    def after_trading(self, context: Context):
        """
        盘后处理方法【可选实现】。

        此方法在【每个交易日】的 `handle_bar` 最后一次调用之后，但在
        `broker_settle` 之前被触发一次。`context.current_dt` 此时通常被
        设置为配置中的 `after_trading` 时间 (例如 15:05:00)。

        典型用途:
        - 对当日的交易进行复盘和记录。
        - 计算并保存当日的自定义指标。
        - 为第二天的交易做初步的数据准备。
        """
        pass

    def broker_settle(self, context: Context):
        """
        日终结算后处理方法【可选实现】。

        此方法在【每个交易日】的 `MatchingEngine` 完成了所有内部结算
        （资金划转、持仓更新、T+1状态变更等）之后被调用。此时，
        `context.portfolio` 和 `context.position_manager` 中的数据
        已是当日收盘后的最终状态。

        典型用途:
        - 获取并记录当日最终的账户净值和持仓详情。
        - 在模拟交易中，可用于与外部真实券商的账户进行对账。
        """
        pass

    def on_end(self, context: Context):
        """
        策略结束方法【可选实现】。

        此方法在整个回测或模拟交易过程【完全结束时】被调用一次。
        它在 `Engine` 即将生成最终报告和清理资源之前执行。

        典型用途:
        - 执行最终的、全局性的数据分析。
        - 保存策略运行过程中积累的自定义数据到文件。
        - 进行资源清理（例如关闭文件句柄、数据库连接等）。
        """
        pass