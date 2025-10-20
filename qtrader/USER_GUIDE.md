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

这是回测的“总开关”，定义了回测的各项参数。

```yaml
# config.yaml
engine:
  mode: backtest
  strategy_name: "双均线策略"
  start_date: "2023-01-01"
  end_date: "2023-12-31"
  frequency: daily

account:
  initial_cash: 1000000.0
  trading_rule: "T+1"

matching:
  commission_rate: 0.0003
  slippage: 0.0001

benchmark:
  symbol: "000300.SH"
  name: "沪深300"
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

*   `context.current_dt` (`datetime`): 获取当前 Bar (K线) 的时间戳。
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

**PositionManager - 持仓管理 (`context.position_manager`)**

提供对当前所有持仓的详细访问。

*   `context.position_manager.get_position(symbol: str, direction: PositionDirection = PositionDirection.LONG) -> Position | None`:
    获取指定证券和方向的持仓。`PositionDirection` 可为 `PositionDirection.LONG` 或 `PositionDirection.SHORT`。如果无此持仓，返回 `None`。

*   `context.position_manager.get_all_positions() -> list[Position]`:
    获取当前所有的持仓对象列表。

**Position - 持仓对象**

`get_position` 返回的是一个 `Position` 对象，包含详细的持仓信息。

*   `pos.symbol` (`str`): 证券代码。
*   `pos.total_amount` (`int`): 总持仓数量。
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
    *   `order_type` (`OrderType`): 订单类型。`OrderType.MARKET` (市价单) 或 `OrderType.LIMIT` (限价单)。
    *   `price` (`float`, 可选): 如果是限价单，则必须提供此价格。
    *   **返回值**: 如果下单成功，返回唯一的订单 ID (`order_id`)。

*   `context.order_manager.cancel_order(order_id: str) -> bool`:
    根据订单 ID 撤销一个未成交的订单。

*   `context.order_manager.get_open_orders() -> list[Order]`:
    获取所有当前状态为 `OPEN` (未成交) 的订单列表。

#### 3.2.5. 高级功能

*   `context.add_schedule(time_str: str)`:
    **只能在 `initialize()` 中调用**。在默认的 `handle_bar` 调用之外，增加一个自定义的调用时间点。`time_str` 格式为 `"HH:MM:SS"`。

*   `context.set_initial_state(cash: float, positions: list[dict])`:
    **只能在 `initialize()` 中调用一次**。覆盖配置文件中的初始状态，手动设置一个自定义的期初现金和持仓。
    `positions` 列表的格式: `[{'symbol': '...', 'amount': 100, 'avg_cost': 10.0}, ...]`

## 4. 数据接入指南

QTrader 的数据源是可插拔的。您只需创建一个继承自 `qtrader.data.interface.AbstractDataProvider` 的类，并实现其定义的三个方法。

*   `get_trading_calendar(self, start: str, end: str) -> list[str]`:
    返回一个 `YYYY-MM-DD` 格式的交易日字符串列表。

*   `get_current_price(self, symbol: str, dt: datetime) -> dict | None`:
    返回指定时间点的价格快照字典，至少需要包含 `'current_price'` 键。

*   `get_symbol_info(self, symbol: str, date: str) -> dict | None`:
    返回证券的静态信息，必须包含 `'symbol_name'` 和 `'is_suspended'` 键。

## 5. 运行与操作

通过 `qtrader.runner.backtest_runner.BacktestRunner`，您可以以编程方式控制回测的运行。

*   `BacktestRunner.run_new(...)`: 启动一个全新的回测。
*   `BacktestRunner.run_resume(state_file: str, ...)`: 从一个由“暂停”操作生成的 `.pkl` 状态文件恢复运行。
*   `BacktestRunner.run_fork(state_file: str, new_strategy_path: str, ...)`: 从一个历史状态文件“分叉”出一个新的回测，用于对比不同策略或参数在同一历史节点后的表现。

## 6. 结果分析

每次回测结束后，QTrader 会在 `strategies/{策略名}/backtest/{时间戳}` 目录下生成一个工作区，其中包含：

*   `backtest.log`: 详细的日志文件。
*   `final_state.pkl`: 包含回测结束时所有状态的序列化文件。
*   `daily_portfolio.csv`: 每日账户净值快照。
*   `trade_history.csv`: 所有成交记录。
*   `report.html`: **最终的可视化回测报告**，包含了净值曲线、关键性能指标和交易详情，可直接在浏览器中打开。