# QTrader 用户文档

欢迎使用 QTrader，一个专为量化交易研究而设计的、事件驱动型 Python 回测框架。

本文档将详细介绍如何使用 QTrader 回测系统，包括环境配置、策略编写、数据接入和结果分析，并提供完整的 API 参考。

## 1. QTrader 简介

QTrader 是一个功能强大且高度可扩展的回测平台，其核心特性包括：

*   **事件驱动架构**: 模拟真实的交易环境，支持按日或按分钟的事件循环。
*   **策略与框架分离**: 用户只需关注策略逻辑的编写，无需关心底层实现。
*   **状态持久化**: 支持在回测过程中随时暂停、恢复，甚至“分叉”出一个新的回测，用于进行“假设分析”。
*   **灵活的数据接入**: 用户可以通过实现标准接口，轻松接入自定义的外部数据源（如本地文件、数据库或在线 API）。
*   **详细的结果报告**: 自动生成包含关键性能指标（夏普比率、最大回撤等）、交易历史和净值曲线的 HTML 报告。

## 2. 快速上手

本章节将通过一个简单的双均线策略，带您完整地体验一次回测流程。

### 2.1. 目录结构

一个典型的 QTrader 策略项目包含以下文件：

```
my_strategy_project/
├── run_backtest.py         # 回测启动脚本
├── config.yaml             # 回测配置文件
├── strategy.py             # 策略逻辑文件
└── data_provider.py        # 数据提供者文件
```

### 2.2. 配置文件 (`config.yaml`)

这是回测的“总开关”，定义了回测的各项参数。一个完整的配置文件包含了引擎、工作区、账户、交易、报告、日志等多个方面的设置。

下面是一个包含了所有可用选项的完整配置模板，您可以根据需要进行删减和修改：

```yaml
# QTrader 回测配置文件模板

# ==============================================================================
# 1. 引擎核心配置
# ==============================================================================
engine:
  mode: backtest                  # 运行模式: backtest (回测) / simulation (模拟盘)
  frequency: daily                # 运行频率: daily / minute / tick
  tick_interval_seconds: 3        # Tick模式下的秒数间隔 (例如: 3 表示每3秒一个bar
  start_date: "2023-01-01"        # 回测开始日期
  end_date: "2023-12-31"          # 回测结束日期
  strategy_name: "MyStrategy"     # 策略名称（可选，默认使用策略类名）
  enable_intraday_statistics: true # 记录盘中收益统计开关（只对 tick 和 minute 模式有效）
  intraday_update_frequency: 5    # 盘中收益更新频率，仅对 tick 和 minute 模式有效，默认5分钟

# ==============================================================================
# 2. 工作区与产物配置
# ==============================================================================
workspace:
  # root_dir: "qtrader_runs"      # (可选) 全局根目录，不指定则在策略文件旁创建
  create_code_snapshot: true      # 是否创建策略代码快照
  create_config_snapshot: true    # 是否创建配置文件快照
  create_data_provider_snapshot: true # 是否创建数据提供者快照
  auto_save_state: false          # 是否自动保存状态（每10天）
  auto_save_interval: 10         # 自动保存间隔（天）
  auto_save_mode: 'overwrite'    # 保存模式: 'overwrite' (覆盖) 或 'increment' (增量)

# ==============================================================================
# 3. 账户与交易规则
# ==============================================================================
account:
  initial_cash: 1000000           # 初始资金
  trading_rule: 'T+1'             # 交易制度: 'T+1' 或 'T+0'
  trading_mode: 'long_only'       # 交易模式: 'long_only' (仅多头) 或 'long_short' (多空)
  order_lot_size: 100             # 订单最小单位 (例如: A股为100股)
  short_margin_rate: 0.2          # 做空交易保证金

# ==============================================================================
# 4. 生命周期钩子
# ==============================================================================
lifecycle:
  # 交易时段定义 (适用于分钟/Tick频)
  trading_sessions:
    - ["09:30:00", "11:30:00"]
    - ["13:00:00", "15:00:00"]
  
  # 策略钩子执行时间点
  hooks:
    before_trading: "09:15:00"    # 盘前准备
    handle_bar: "14:55:00"        # 日频使用运行时间
    # 方式2：多个时间点
    # handle_bar_times:
    #   - "10:00:00"
    #   - "14:00:00"
    #   - "14:55:00"
    after_trading: "15:05:00"     # 盘后处理
    broker_settle: "15:30:00"     # 日终结算

# ==============================================================================
# 5. 撮合与费用
# ==============================================================================
matching:
  slippage:
    type: fixed                   # 滑点类型 (目前仅支持 fixed)
    rate: 0.001                   # 固定滑点率 (千分之一)
  
  commission:
    buy_commission: 0.0002        # 买入佣金率 (万分之二)
    sell_commission: 0.0002       # 卖出佣金率 (万分之二)
    buy_tax: 0.0                  # 买入印花税率 (A股为0)
    sell_tax: 0.001               # 卖出印花税率 (千分之一)
    min_commission: 5.0           # 单笔最低佣金 (元)

# ==============================================================================
# 6. 基准
# ==============================================================================
benchmark:
  symbol: "000300"                # 基准标的代码 (例如: 沪深300指数)

# ==============================================================================
# 7. 内置监控服务器
# ==============================================================================
server:
  enable: true                    # 是否启用内置监控服务器
  port: 8050                      # Web服务器端口
  auto_open_browser: true         # 启动时是否自动打开浏览器
  update_interval: 0.5            # 文件检查间隔(秒)，不影响回测速度

# ==============================================================================
# 8. 报告生成
# ==============================================================================
report:
  auto_open: true                 # 回测结束后是否自动打开报告

# ==============================================================================
# 9. 日志
# ==============================================================================
logging:
  level: INFO                     # 日志级别: DEBUG, INFO, WARNING, ERROR
  console_output: true            # 是否输出到控制台
  buffer_size: 1000               # 内存日志缓冲区大小
```

### 2.3. 数据提供者 (`data_provider.py`)

QTrader 需要您提供一个数据源。这里我们以一个读取本地 CSV 文件的简单`DataProvider`为例。

```python
# data_provider.py
import pandas as pd
from qtrader.data.interface import AbstractDataProvider
from datetime import datetime, timedelta

class CSVDataProvider(AbstractDataProvider):
    def __init__(self):
        # 假设您有一个包含价格和交易日历的 CSV 文件
        self.market_data = pd.read_csv("market_data.csv", index_col='date', parse_dates=True)
        self.trading_calendar = self.market_data.index.strftime('%Y-%m-%d').tolist()

    def get_trading_calendar(self, start: str, end: str) -> list[str]:
        return [d for d in self.trading_calendar if start <= d <= end]

    def get_current_price(self, symbol: str, dt: datetime) -> dict | None:
        date_str = dt.strftime('%Y-%m-%d')
        if date_str in self.market_data.index:
            price = self.market_data.loc[date_str, symbol]
            return {'current_price': price}
        return None

    def get_symbol_info(self, symbol: str, date: str) -> dict | None:
        return {'symbol_name': symbol, 'is_suspended': False}
```

### 2.4. 策略逻辑 (`strategy.py`)

这是您交易思想的体现。所有策略都必须继承自 `qtrader.strategy.base.Strategy`。

```python
# strategy.py
import pandas as pd
from qtrader.strategy.base import Strategy
from qtrader.core.context import Context
from qtrader.trading.order import OrderType

class MovingAverageStrategy(Strategy):
    def initialize(self, context: Context):
        """策略初始化，只在开始时运行一次"""
        context.log.info("开始初始化双均线策略...")
        # 订阅的股票池
        context.user_data['symbols'] = ['600519.SH']
        # 均线周期
        context.user_data['short_ma'] = 10
        context.user_data['long_ma'] = 30
        
        # 预加载历史数据用于计算初始均线
        # (此处省略数据加载细节)

    def handle_bar(self, context: Context):
        """策略核心逻辑，按K线周期运行"""
        symbols = context.user_data['symbols']
        short_ma_period = context.user_data['short_ma']
        long_ma_period = context.user_data['long_ma']

        for symbol in symbols:
            # 获取历史数据 (此处省略)
            # hist_data = context.data_provider.get_history(...) 
            # short_ma = hist_data['close'][-short_ma_period:].mean()
            # long_ma = hist_data['close'][-long_ma_period:].mean()
            
            # 此处为伪代码
            short_ma = 100 
            long_ma = 99

            position = context.position_manager.get_position(symbol)

            # 金叉：短均线上穿长均线，且当前无持仓，则买入
            if short_ma > long_ma and position is None:
                context.order_manager.submit_order(
                    symbol=symbol,
                    amount=1000, # 买入1000股
                    order_type=OrderType.MARKET
                )
                context.logger.info(f"金叉信号，买入 {symbol}")

            # 死叉：短均线下穿长均线，且当前有持仓，则卖出
            elif short_ma < long_ma and position is not None:
                context.order_manager.submit_order(
                    symbol=symbol,
                    amount=-position.total_amount, # 卖出所有持仓
                    order_type=OrderType.MARKET
                )
                context.logger.info(f"死叉信号，卖出 {symbol}")
```

### 2.5. 启动回测 (`run_backtest.py`)

使用 `BacktestRunner` 来启动回测。

```python
# run_backtest.py
from qtrader.runner.backtest_runner import BacktestRunner

if __name__ == "__main__":
    BacktestRunner.run_new(
        config_path="config.yaml",
        strategy_path="strategy.py",
        data_provider_path="data_provider.py"
    )
```

运行 `run_backtest.py`，QTrader 将开始执行回测，并在结束后自动打开一份详细的 HTML 报告。

## 3. 策略编写指南

### 3.1. `Strategy` 基类与生命周期

您的所有策略都必须继承自 `qtrader.strategy.base.Strategy`，并根据需要实现其定义的生命周期方法。框架会遵循“好莱坞原则”在正确的时间自动调用它们。

*   `initialize(self, context: Context)`: **【必须实现】**
    在回测开始时仅调用一次，用于设置策略参数、订阅证券、预加载数据等一次性操作。

*   `before_trading(self, context: Context)`: **【可选】**
    在每个交易日的交易开始前调用一次。可用于计算当日交易信号、筛选股票池等。

*   `handle_bar(self, context: Context)`: **【可选】**
    策略的核心逻辑，根据 `config.yaml` 中设置的 `frequency` (daily/minute) 反复调用。所有主要的交易决策和下单操作都在此进行。

*   `after_trading(self, context: Context)`: **【可选】**
    在每个交易日的交易结束后调用一次。可用于当日复盘、记录自定义指标等。

*   `broker_settle(self, context: Context)`: **【可选】**
    在每个交易日完成资金和持仓的结算后调用。此时 `context.portfolio` 和 `context.position_manager` 已是当日最终状态。

*   `on_end(self, context: Context)`: **【可选】**
    在整个回测完全结束时调用一次。可用于最终的数据分析、保存自定义结果等。

### 3.2. `Context` API 参考

`Context` 对象是策略与回测引擎交互的唯一接口，它被作为参数传递给所有生命周期方法。

#### 3.2.1. 时间与环境

*   `context.current_dt` (`datetime`): 获取回测或模拟系统的当前时间戳。在回测模式下，它代表当前正在处理的 Bar (K线) 的时间；在模拟模式下，它与真实世界的当前时间基本同步。
*   `context.mode` (`str`): 获取当前运行模式 (`'backtest'` 或 `'simulation'`)。

#### 3.2.2. 自定义数据存储

*   `context.user_data` (`dict`): 一个字典，用于在策略的整个生命周期中存储和传递任何您需要的数据。
*   `context.set(key, value)`: `context.user_data[key] = value` 的便捷写法。
*   `context.get(key, default=None)`: `context.user_data.get(key, default)` 的便捷写法。

#### 3.2.3. 查询账户与持仓

**Portfolio - 账户状态 (`context.portfolio`)**

提供账户的整体财务概览。

*   `context.portfolio.net_worth` (`float`): 账户净资产。
*   `context.portfolio.total_assets` (`float`): 总资产。
*   `context.portfolio.cash` (`float`): 总现金。
*   `context.portfolio.available_cash` (`float`): **可用资金**。
*   `context.portfolio.margin` (`float`): 占用的保证金（主要用于空头持仓）。
*   `context.portfolio.returns` (`float`): 基于初始资金的累计收益率。
*   `context.portfolio.long_market_value` (`float`): 多头持仓市值。
*   `context.portfolio.short_market_value` (`float`): 空头持仓市值（负载）。

**PositionManager - 持仓管理 (`context.position_manager`)**

提供对当前所有持仓的详细访问。

*   `context.position_manager.get_position(symbol: str, direction: str ) -> Position | None`:
    获取指定证券和方向的持仓。`direction` 参数接受字符串 `"long"` 或 `"short"`。如果无此持仓，返回 `None`。

*   `context.position_manager.get_all_positions() -> list[Position]`:
    获取当前所有的持仓对象列表。

**Position - 持仓对象**

`get_position` 返回的是一个 `Position` 对象，包含详细的持仓信息。

*   `pos.symbol` (`str`): 证券代码。
*   `pos.total_amount` (`int`): 总持仓数量。**（注意：此值始终为正数，代表持仓的绝对数量。方向由 `pos.direction` 决定。）**
*   `pos.available_amount` (`int`): **可卖出数量**（考虑了 T+1 规则）。
*   `pos.avg_cost` (`float`): 持仓成本价。
*   `pos.market_value` (`float`): 当前市值。
*   `pos.unrealized_pnl` (`float`): 未实现盈亏。
*   `pos.direction` (`PositionDirection`): 持仓方向。

#### 3.2.4. 执行交易

所有交易操作都通过 `OrderManager` 完成。

**OrderManager - 订单管理 (`context.order_manager`)**

*   `context.order_manager.submit_order(symbol, amount, order_type, price=None) -> str | None`:
    **核心下单函数**。
    *   `symbol` (`str`): 证券代码。
    *   `amount` (`int`): **下单数量。正数为买入，负数为卖出。**
    *   `order_type` (`str`): 订单类型。使用字符串 `"market"` (市价单) 或 `"limit"` (限价单)。
    *   `price` (`float`, 可选): 如果是限价单，则必须提供此价格。
    *   **返回值**: 如果下单成功，返回唯一的订单 ID (`order_id`)。

*   `context.order_manager.cancel_order(order_id: str) -> bool`:
    根据订单 ID 撤销一个未成交的订单。

*   `context.order_manager.get_open_orders() -> list[Order]`:
    获取所有当前状态为 `OPEN` (未成交) 的订单列表。

*   `context.order_manager.get_filled_orders_today() -> list[Order]`:
    获取当日所有已成交 (`FILLED`) 的订单列表。

*   `context.order_manager.get_all_orders_history() -> list[Order]`:
    获取所有历史成交订单。这包含了过去所有交易日的已成交订单。

*   `context.order_manager.get_all_orders() -> list[Order]`:
    获取所有已知的订单，包括当日所有状态的订单和历史成交订单。

**Order - 订单对象**

`OrderManager` 的查询方法（如 `get_open_orders`）返回的是一个 `Order` 对象列表。`Order` 对象包含了订单的详细信息。

*   `order.id` (`str`): 订单的唯一ID。
*   `order.symbol` (`str`): 证券代码。
*   `order.symbol_name` (`str` | `None`): 证券名称。
*   `order.amount` (`int`): 订单数量（始终为正数）。
*   `order.side` (`OrderSide`): 交易方向 (`OrderSide.BUY` 或 `OrderSide.SELL`)。
*   `order.order_type` (`OrderType`): 订单类型 (`OrderType.MARKET` 或 `OrderType.LIMIT`)。
*   `order.limit_price` (`float` | `None`): 限价单的价格。
*   `order.status` (`OrderStatus`): 订单状态，例如 `OrderStatus.OPEN`, `OrderStatus.FILLED`, `OrderStatus.CANCELLED` 等。
*   `order.created_time` (`datetime` | `None`): 订单创建时间。
*   `order.filled_time` (`datetime` | `None`): 订单成交时间。
*   `order.filled_price` (`float` | `None`): 订单成交均价。
*   `order.commission` (`float` | `None`): 交易手续费。

#### 3.2.5. 其他功能

*   `context.add_schedule(time_str: str)`:
    **只能在 `initialize()` 中调用**。可以多次调用此函数，在默认的 `handle_bar` 调用之外，增加多个自定义的策略逻辑调用时间点。`time_str` 格式为 `"HH:MM:SS"`。

*   `context.set_initial_state(cash: float, positions: list[dict])`:
    **只能在 `initialize()` 中调用一次**。覆盖配置文件中的初始状态，手动设置一个自定义的期初现金和持仓。这对于从一个特定的非零状态开始回测非常有用。
    *   `cash` (`float`): 初始可用现金。
    *   `positions` (`list[dict]`): 初始持仓列表。列表中的每个字典代表一个持仓，结构如下：
        *   `'symbol'` (`str`, **必须**): 证券代码。
        *   `'amount'` (`int`, **必须**): 持仓数量。**正数为多头，负为空头。**
        *   `'avg_cost'` (`float`, 可选): 持仓成本价。如果未提供，系统将尝试获取当日价格作为成本。
        *   `'symbol_name'` (`str`, 可选): 证券名称。

*   `context.align_account_state(cash: float, positions: list[dict])`:
    **建议在 `broker_settle()` 中调用**。此函数用于在模拟交易或实盘中，将系统内部的账户状态（现金和持仓）与外部的实际账户状态进行强制对齐，以修正可能存在的状态漂移。
    *   `cash` (`float`): 对齐后的目标现金。
    *   `positions` (`list[dict]`): 对齐后的目标持仓列表，其格式与 `set_initial_state` 完全相同。系统会自动计算差异并进行调整。

## 4. 数据接入指南

QTrader 的数据源是可插拔的。任何想要接入 QTrader 的数据源（无论是来自本地文件、数据库还是实时 API），都必须创建一个继承自 `qtrader.data.interface.AbstractDataProvider` 的子类，并完整实现其所有抽象方法。

这种设计遵循了“依赖倒置原则”，使得核心引擎不依赖于任何具体的数据实现，从而可以轻松地替换和扩展数据源，而无需修改核心逻辑。

下面是 `AbstractDataProvider` 的完整接口定义，包含了所有需要实现的方法及其详细说明：

```python
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
```

## 5. 运行与操作

通过 `qtrader.runner.backtest_runner.BacktestRunner`，您可以以编程方式控制回测的运行。

*   `BacktestRunner.run_new(...)`: 启动一个全新的回测。
*   `BacktestRunner.run_resume(state_file: str, ...)`: 从一个由“暂停”操作生成的 `.pkl` 状态文件恢复运行。
*   `BacktestRunner.run_fork(state_file: str, new_strategy_path: str, ...)`: 从一个历史状态文件“分叉”出一个新的回测，用于对比不同策略或参数在同一历史节点后的表现。

## 6. 工作区 (Workspace) 与结果分析

QTrader 会为每一次运行（无论是回测还是模拟）创建一个独立的工作区目录，以确保所有产物都被隔离存放，便于追溯和管理。

### 6.1. 目录结构

工作区的默认生成规则如下：

```
<策略文件所在目录>/
└── <策略名>/
    ├── backtest/
    │   └── <YYYYMMDD_HHMMSS>/  <-- 这是一个具体的回测工作区
    │       ├── ... (产出文件)
    └── simulation/
        └── <YYYYMMDD_HHMMSS>/  <-- 这是一个具体的模拟交易工作区
            ├── ... (产出文件)
```

*   **根目录**: 默认情况下，根目录是与您的策略文件 (`strategy.py`) 同级的、与策略同名的文件夹。您也可以在配置文件中的 `workspace.root_dir` 选项下指定一个全局的根目录。
*   **模式目录**: 在根目录下，会根据运行模式创建 `backtest` 或 `simulation` 子目录。
*   **时间戳目录**: 每次运行都会以当前的 `年-月-日_时-分-秒` 创建一个唯一的时间戳目录，作为本次运行的专属工作区。

### 6.2. 生成的文件详解

在一个典型的工作区内，您会看到以下文件：

*   **日志文件**:
    *   `backtest.log` 或 `simulation.log`: 根据运行模式命名，记录了从引擎启动到结束的所有详细日志，是排查问题的首要工具。

*   **代码与配置快照**: (如果 `workspace` 配置项开启)
    *   `snapshot_code.py`: 策略文件 (`strategy.py`) 在本次运行时的精确副本。
    *   `snapshot_config.yaml`: 配置文件 (`config.yaml`) 在本次运行时的精确副本。
    *   `snapshot_data_provider.py`: 数据提供者文件 (`data_provider.py`) 在本次运行时的精确副本。
    *   这些快照确保了每次运行都是完全可复现的。

*   **核心数据导出 (CSV)**:
    *   `equity.csv`: 每日净值曲线数据，包含了净资产、现金、市值、收益率等多个维度的历史记录。
    *   `daily_positions.csv`: 每日持仓快照，记录了每天收盘后所有持仓的详细信息（代码、方向、数量、成本、市值、每日盈亏等）。
    *   `orders.csv`: 完整的订单流水记录，包含了所有提交过的订单（无论成功、失败或撤销）的详细信息。
    *   `pnl_pairs.csv`: 盈亏交易对记录，详细记录了每一笔完整交易（从开仓到平仓）的各项指标，如进出场时间、价格、持有期、盈亏额、盈亏比等。

*   **状态序列化文件 (.pkl)**:
    这些文件以二进制格式保存了系统在某一时刻的完整状态，是实现暂停、恢复和分叉功能的核心。
    *   `{策略名}_final.pkl`: **[正常结束]** 当一次运行正常完成时生成。它包含了最终的完整状态，主要用于生成报告和进行事后分析。**无法从此文件恢复运行**。
    *   `{策略名}_interrupt.pkl`: **[异常中断]** 当运行被用户通过 `Ctrl+C` 强制中断或因代码错误而崩溃时生成。它同样包含了中断瞬间的完整状态，用于分析中断原因。**无法从此文件恢复运行**。
    *   `{策略名}_pause.pkl`: **[手动暂停]** 当用户通过监控页面或调用 `engine.pause()` 主动暂停运行时生成。这是**唯一一种可以用于恢复 (`resume`) 或分叉 (`fork`) 运行的状态文件**。

*   **可视化报告**:
    *   `report.html`: **最终的可视化回测报告**。这是一个独立的 HTML 文件，可以直接在浏览器中打开。它以图表和表格的形式，直观地展示了策略的净值曲线、与基准的对比、关键性能指标（如夏普比率、最大回撤、年化收益率等）以及详细的交易历史记录。

## 7. 模式切换：回测 (`backtest`) 与模拟 (`simulation`)

QTrader 的核心优势之一在于，同一套策略代码、数据接口和核心组件可以在回测与模拟盘模式之间无缝切换，您只需在配置文件中更改 `engine.mode` 即可。甚至，您可以从一个回测生成的暂停状态文件 (`_pause.pkl`) 直接启动一个模拟盘实例，实现从历史到现实的平滑过渡。

尽管底层设计差异显著（确定性的历史事件循环 vs. 实时的状态机），但这些对用户是透明的。您只需关注以下几个关键的用户层面的区别：

| 关键差异 | `backtest` (回测模式) | `simulation` (模拟盘模式) |
| :--- | :--- | :--- |
| **时间基准** | 由历史数据驱动，快速遍历指定的时间段。 | 由真实世界时钟驱动，与当前时间同步。 |
| **配置项** | `start_date` 和 `end_date` **必须**指定，定义了回测范围。 | `start_date` 和 `end_date` **被忽略**。模拟盘总是从当前时刻开始，并持续运行。 |
| **数据源要求** | 需要能提供完整历史区间数据的数据提供者。 | 需要能提供实时或准实时报价的数据提供者。 |
| **恢复 (`resume`) 行为** | 从暂停点 (`_pause.pkl`) 恢复时，将从中断的历史时间点精确继续。 | 从暂停点恢复时，会执行**时间同步**：自动结算所有错过的交易日，将账户状态快进到当前真实时间，然后再继续接收实时事件。 |

简而言之，使用 `backtest` 模式来开发和验证策略在历史上的表现；当策略成熟后，切换到 `simulation` 模式，在真实的市场环境中进行最终的模拟观察。