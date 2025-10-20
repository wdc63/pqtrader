# qtrader/examples/strategies/simple_ma.py

"""
简单双均线策略示例

策略逻辑：
1. 计算短期和长期均线
2. 金叉买入，死叉卖出
3. 仅持有一只股票

注意：用户需要自行实现历史数据获取
"""

from qtrader.strategy.base import Strategy
from qtrader.trading.order import OrderType
import time


class SimpleMAStrategy(Strategy):
    """简单双均线策略"""
    
    def initialize(self, context):
        """策略初始化"""
        # 设置策略参数
        context.set('ma_short', 5)   # 短期均线周期
        context.set('ma_long', 20)   # 长期均线周期
        context.set('symbol', '000001')  # 交易标的
        
        # 初始化价格历史（用于计算均线）
        context.set('price_history', [])
        
        context.logger.info("策略初始化完成")
        context.logger.info(f"交易标的: {context.get('symbol')}")
        context.logger.info(f"短期均线: {context.get('ma_short')}日")
        context.logger.info(f"长期均线: {context.get('ma_long')}日")
    
    # 修正：移除了未使用的 `data` 参数
    def before_trading(self, context):
        """盘前准备"""
        context.logger.info(f"===== {context.current_dt.date()} 盘前准备 =====")
    
    # 修正：移除了未使用的 `data` 参数
    def handle_bar(self, context):
        time.sleep(0.5)
        """盘中策略执行"""
        symbol = context.get('symbol')
        ma_short_period = context.get('ma_short')
        ma_long_period = context.get('ma_long')
        
       # 获取当前价格和静态信息
        price_data = context.data_provider.get_current_price(
            symbol,
            context.current_dt
        )
        # 从缓存或API获取静态信息
        symbol_info = context.symbol_info_cache.get(symbol)
        if not symbol_info:
            info = context.data_provider.get_symbol_info(symbol, context.current_dt.strftime('%Y-%m-%d'))
            if info:
                context.symbol_info_cache[symbol] = info
                symbol_info = info
        
        if price_data is None or 'current_price' not in price_data or price_data['current_price'] is None:
            context.logger.warning(f"无法获取{symbol}当前价格")
            return
            
        if symbol_info is None:
            context.logger.warning(f"无法获取{symbol}标的信息")
            return

        current_price = price_data['current_price']
        symbol_name = symbol_info.get('symbol_name', symbol)
        
        # 更新价格历史
        price_history = context.get('price_history')
        price_history.append(current_price)
        
        # 保持最近ma_long个价格
        if len(price_history) > ma_long_period:
            price_history = price_history[-ma_long_period:]
        context.set('price_history', price_history)
        
        # 如果数据不足，不执行交易
        if len(price_history) < ma_long_period:
            context.logger.debug(f"价格历史数据不足({len(price_history)}/{ma_long_period})")
            return
        
        # 计算均线
        ma_short = sum(price_history[-ma_short_period:]) / ma_short_period
        ma_long = sum(price_history) / ma_long_period
        
        context.logger.debug(
            f"当前价格: {current_price:.2f}, "
            f"MA{ma_short_period}: {ma_short:.2f}, "
            f"MA{ma_long_period}: {ma_long:.2f}"
        )
        
        # 获取当前持仓
        position = context.position_manager.get_position(symbol)
        
        # 交易逻辑
        if ma_short > ma_long:
            # 金叉：买入
            if position is None or position.total_amount == 0:
                # 使用50%资金买入
                cash = context.portfolio.cash
                amount = int(cash * 0.5 / current_price / 100) * 100
                
                if amount > 0:
                    # 使用 submit_order 方法
                    context.order_manager.submit_order(symbol, amount, OrderType.MARKET, symbol_name=symbol_name)
                    context.logger.info(
                        f"🔼 金叉买入信号: {symbol_name} {amount}股 "
                        f"@{current_price:.2f}"
                    )
        
        elif ma_short < ma_long:
            # 死叉：卖出
            if position and position.total_amount > 0:
                # 使用 submit_order 方法
                context.order_manager.submit_order(
                    symbol,
                    -position.total_amount,
                    OrderType.MARKET,
                    symbol_name=symbol_name
                )
                context.logger.info(
                    f"🔽 死叉卖出信号: {symbol_name} {position.total_amount}股 "
                    f"@{current_price:.2f}"
                )
                
    def after_trading(self, context):
        """盘后处理"""
        filled_orders = context.order_manager.get_filled_orders_today()
        context.logger.info(f"今日成交订单数: {len(filled_orders)}")
        
        portfolio = context.portfolio
        context.logger.info(
            f"账户净资产: ¥{portfolio.net_worth:,.2f}, "
            f"收益率: {portfolio.returns:.2%}"
        )
        
        benchmark_returns = context.benchmark_manager.get_current_returns()
        context.logger.info(f"基准收益率: {benchmark_returns:.2%}")
    
    def broker_settle(self, context):
        """日终结算"""
        context.logger.info("日终结算完成")
    
    def on_end(self, context):
        """策略结束"""
        final_returns = context.portfolio.returns
        benchmark_returns = context.benchmark_manager.get_current_returns()
        alpha = final_returns - benchmark_returns
        
        context.logger.info("===== 策略运行结束 =====")
        context.logger.info(f"策略最终收益率: {final_returns:.2%}")
        context.logger.info(f"基准最终收益率: {benchmark_returns:.2%}")
        context.logger.info(f"超额收益: {alpha:.2%}")