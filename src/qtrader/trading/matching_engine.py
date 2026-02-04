# qtrader/trading/matching_engine.py

from datetime import datetime
from typing import Dict, Optional, List, Tuple
from ..core.context import Context
from ..trading.order import Order, OrderStatus, OrderSide, OrderType
from ..trading.commission import CommissionCalculator
from ..trading.slippage import SlippageModel
from ..trading.position import PositionDirection

class MatchingEngine:
    """
    撮合引擎 (Matching Engine)，模拟交易所的核心功能。

    本模块负责处理所有订单的撮合与成交，是连接策略意图（订单）与
    账户状态（资金和持仓）的关键桥梁。它旨在模拟一个简化的、但符合
    逻辑的真实世界交易撮合过程。

    主要职责:
    1.  **订单撮合 (`match_orders`)**:
        - 接收来自 `Scheduler` 的时间脉冲，并尝试撮合所有处于 `OPEN` 状态的订单。
        - 区分处理“立即单”（如市价单）和“历史挂单”（如未成交的限价单）。

    2.  **价格确定**:
        - 从 `DataProvider` 获取最新的市场快照（价格、买卖盘、涨跌停等）。
        - 根据订单类型（市价/限价）和市场行情，决定最终的成交价格。

    3.  **交易成本计算**:
        - 调用 `SlippageModel` 计算滑点。
        - 调用 `CommissionCalculator` 计算交易手续费。

    4.  **前置风控检查 (`_pre_check`, `_check_sufficiency`)**:
        - **市场规则检查**: 检查标的是否停牌、价格是否超出涨跌停限制。
        - **账户状态检查**: 检查购买是否有足够资金、卖出是否有足够可用持仓（考虑 T+1 规则）。

    5.  **状态更新 (`_finalize_trade`)**:
        - 如果所有检查通过，则将订单标记为 `FILLED`。
        - 更新 `Portfolio` 中的现金。
        - 更新 `PositionManager` 中的持仓（开仓、平仓或反手）。

    6.  **每日结算 (`settle`)**:
        - 在每个交易日结束时，执行结算流程，包括取消未成交订单、按收盘价
          更新持仓市值、记录每日净值、并根据 T+1 规则更新可用持仓。
    """
    def __init__(self, context: Context, config: dict):
        self.context = context
        self.config = config
        self.commission_calc = CommissionCalculator(config.get('commission', {}))
        self.slippage_model = SlippageModel(config.get('slippage', {}))
        self.trading_mode = context.config.get('account', {}).get('trading_mode', 'long_only')
        self.margin_rate = self.context.config.get('account', {}).get('short_margin_rate', 0.2)

    def match_orders(self, dt: datetime):
        """
        在给定的时间点，尝试撮合所有活跃订单。

        为了模拟更真实的行为，这里将订单分为两类：
        - `immediate`: 立即单。通常指市价单或那些希望立即以对手价成交的限价单。
                       这类订单会被优先处理。
        - `historical`: 历史挂单。指那些在前一时间点未成交而留存下来的限价单。

        Args:
            dt (datetime): 当前的市场时间戳，用于获取价格数据。
        """
        open_orders = self.context.order_manager.get_open_orders()
        # is_immediate 标志在订单创建时设置，市价单默认为 True
        immediate = [o for o in open_orders if o.is_immediate]
        historical = [o for o in open_orders if not o.is_immediate]

        # 优先处理希望立即成交的订单
        for order in immediate:
            self._try_match_immediate(order, dt)

        # 再处理历史挂单
        for order in historical:
            self._try_match_historical(order, dt)

    # 辅助方法获取缓存的静态信息
    def _get_cached_symbol_info(self, symbol: str, dt: datetime) -> Optional[Dict]:
        """获取缓存的或实时查询的证券静态信息。"""
        date_str = dt.strftime('%Y-%m-%d')
        if symbol in self.context.symbol_info_cache:
            return self.context.symbol_info_cache[symbol]
        
        info = self.context.data_provider.get_symbol_info(symbol, date_str)
        if info:
            self.context.symbol_info_cache[symbol] = info
        return info

    def _try_match_immediate(self, order: Order, dt: datetime):
        """尝试立即撮合一个订单（通常是市价单或可立即成交的限价单）。"""
        # 原则：全新订单的撮合，必须参考其被创建那一刻的行情
        price_fetch_dt = order.created_time
        price_data = self.context.data_provider.get_current_price(order.symbol, price_fetch_dt)
        symbol_info = self._get_cached_symbol_info(order.symbol, price_fetch_dt)
        
        if not price_data:
            order.mark_as_historical()
            return
            
        if not symbol_info:
            symbol_info = {            
                'symbol_name': order.symbol,
                'is_suspended': False,
            }
        
        snapshot = {**price_data, **symbol_info}

        if not self._pre_check(order, snapshot):
            return

        match_price = self._determine_immediate_match_price(order, snapshot)
        if match_price is None:
            order.mark_as_historical()
            return

        self._execute_match_flow(order, match_price, snapshot, price_fetch_dt)

    def _try_match_historical(self, order: Order, dt: datetime):
        """尝试撮合一个历史挂单（限价单）。"""
        price_data = self.context.data_provider.get_current_price(order.symbol, dt)
        symbol_info = self._get_cached_symbol_info(order.symbol, dt)

        if not price_data:
            order.mark_as_historical()
            return
            
        if not symbol_info:
            symbol_info = {            
                'symbol_name': order.symbol,
                'is_suspended': False,
            }
        
        snapshot = {**price_data, **symbol_info}
        if not snapshot:
            return
        
        if snapshot.get('is_suspended', False):
            return

        current_price = snapshot.get('current_price')
        can_match = False
        if order.side == OrderSide.BUY and current_price is not None:
            if order.order_type == OrderType.MARKET or current_price <= order.limit_price:
                can_match = True
        elif order.side == OrderSide.SELL and current_price is not None:
            if order.order_type == OrderType.MARKET or current_price >= order.limit_price:
                can_match = True

        if can_match:
            match_price = current_price if order.order_type == OrderType.MARKET else order.limit_price
            self._execute_match_flow(order, match_price, snapshot, dt)

    def _execute_match_flow(self, order: Order, match_price: float, snapshot: Dict, dt: datetime):
        """
        执行从价格确定到最终成交的完整流程。

        这是一个核心的交易执行管道，依次执行以下步骤：
        1. 计算滑点，得到最终成交价。
        2. 检查最终成交价是否仍在涨跌停范围内。
        3. 计算交易手续费。
        4. 检查账户是否有足够的资金或持仓来完成交易。
        5. 如果所有检查通过，则执行交易，更新订单、资金和持仓状态。
        """
        # 1. 计算滑点和最终成交价
        slippage = self.slippage_model.calculate(order, match_price)
        final_price = match_price + slippage if order.side == OrderSide.BUY else match_price - slippage

        # 2. 检查价格是否因滑点超出涨跌停
        if not self._check_limit_price_range(final_price, snapshot):
            reason = f"加滑点后价格 {final_price:.2f} 超出涨跌停范围"
            self.context.logger.warning(f"订单 {order.id} ({order.side.value} {order.amount} {order.symbol}) 被拒绝: {reason}")
            order.reject(reason)
            return
        
        # 3. 计算手续费
        commission = self.commission_calc.calculate(order, final_price)

        # 4. 检查资金/持仓是否充足
        can_trade, reason = self._check_sufficiency(order, final_price, commission)
        if not can_trade:
            self.context.logger.warning(f"订单 {order.id} ({order.side.value} {order.amount} {order.symbol}) 被拒绝: {reason}")
            order.reject(reason)
            order.mark_as_historical() # 确保被拒绝的订单不会被再次处理
            return
            
        # 5. 执行成交
        self._finalize_trade(order, final_price, commission, dt)

    def _determine_immediate_match_price(self, order: Order, snapshot: Dict) -> Optional[float]:
        """根据订单类型和市场快照，确定立即成交的价格。"""
        price_ref = snapshot.get('current_price')
        ask1, bid1 = snapshot.get('ask1'), snapshot.get('bid1')

        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BUY:
                return ask1 if ask1 else price_ref
            return bid1 if bid1 else price_ref

        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                market_price = ask1 if ask1 else price_ref
                if market_price is None:
                    return None
                if order.limit_price >= market_price:
                    return market_price
            else:
                market_price = bid1 if bid1 else price_ref
                if market_price is None:
                    return None
                if order.limit_price <= market_price:
                    return market_price
        return None

    def _pre_check(self, order: Order, snapshot: Dict) -> bool:
        """对订单进行成交前的基本检查，如停牌、涨跌停等。"""
        if order.symbol_name is None:
            order.symbol_name = snapshot.get('symbol_name')

        if snapshot.get('is_suspended', False):
            reason = f"标的 {order.symbol} 停牌"
            self.context.logger.warning(f"订单 {order.id} 被拒绝: {reason}")
            order.reject(reason)
            return False

        current, high, low = snapshot.get('current_price'), snapshot.get('high_limit'), snapshot.get('low_limit')
        if current is None:
            reason = f"缺少标的 {order.symbol} 的当前价格"
            self.context.logger.warning(f"订单 {order.id} 被拒绝: {reason}")
            order.reject(reason)
            return False

        # 检查买单是否已达涨停价
        if (order.side == OrderSide.BUY and high is not None and
            abs(current - high) < 1e-6):
            reason = f"标的 {order.symbol} 当前价已涨停"
            self.context.logger.warning(f"订单 {order.id} 被拒绝: {reason}")
            order.reject(reason)
            return False
        
        # 检查卖单是否已达跌停价
        if (order.side == OrderSide.SELL and low is not None and
            abs(current - low) < 1e-6):
            reason = f"标的 {order.symbol} 当前价已跌停"
            self.context.logger.warning(f"订单 {order.id} 被拒绝: {reason}")
            order.reject(reason)
            return False
            
        return True

    def _check_limit_price_range(self, price: float, snapshot: Dict) -> bool:
        """检查价格是否在涨跌停范围内。"""
        high, low = snapshot.get('high_limit'), snapshot.get('low_limit')
        if high is not None and low is not None:
            # 增加一个极小的容差范围，避免浮点数精度问题
            return (low - 1e-6) <= price <= (high + 1e-6)
        return True

    def _check_sufficiency(self, order: Order, price: float, commission: float) -> Tuple[bool, str]:
        """检查是否有足够的资金或持仓来完成交易。"""
        portfolio = self.context.portfolio
        pm = self.context.position_manager
        rule = self.context.config.get('account', {}).get('trading_rule', 'T+1')

        if order.side == OrderSide.BUY:
            # 计算订单所需的总现金
            cash_needed = price * order.amount + commission

            # 检查此买单是否会平掉一个已有的空头仓位
            short_pos = pm.get_position(order.symbol, PositionDirection.SHORT)
            
            margin_to_be_released = 0
            if short_pos and short_pos.total_amount > 0:
                # 检查T+1规则下的可平仓位
                available_to_cover = short_pos.available_amount if rule == 'T+1' else short_pos.total_amount
                amount_to_cover = min(order.amount, available_to_cover)
                
                if amount_to_cover < order.amount and (order.amount - amount_to_cover) > 0:
                    # 这是“平空转多”订单，但T+1导致无法全部平仓，检查是否允许只平部分
                    # 简化处理：我们要求要平的仓位必须足够
                    if order.amount > available_to_cover:
                         return False, f"T+1规则限制, 可用空头持仓不足 (可用: {available_to_cover}, 欲平: {order.amount})"

                # 计算与这部分被平掉的仓位相关的保证金
                if short_pos.total_amount > 0:
                    margin_to_be_released = (short_pos.margin / short_pos.total_amount) * amount_to_cover

            # 总购买力 = 当前可用现金 + 因平仓而即将释放的保证金
            total_buying_power = portfolio.available_cash + margin_to_be_released

            if total_buying_power >= cash_needed:
                return True, ""
            else:
                return False, f"购买力不足 (需要: {cash_needed:,.2f}, 可用购买力: {total_buying_power:,.2f})"

        # SELL
        long_pos = pm.get_position(order.symbol, PositionDirection.LONG)
        
        available_to_sell_long = 0
        if long_pos and long_pos.total_amount > 0:
            available_to_sell_long = long_pos.available_amount

        if order.amount <= available_to_sell_long:
            # 纯粹卖出现有的多头仓位
            return True, ""

        # 如果订单数量超过了可卖出的多头数量，则意味着需要开空仓
        amount_to_open_short = order.amount - available_to_sell_long

        if self.trading_mode == 'long_short':
            margin_needed = price * amount_to_open_short * self.margin_rate
            if portfolio.available_cash >= margin_needed:
                return True, ""
            else:
                return False, f"开空仓保证金不足 (需要: {margin_needed:,.2f}, 可用: {portfolio.available_cash:,.2f})"
        else:
            # 只做多模式下，持仓不足
            return False, f"持仓不足 (欲卖: {order.amount}, 可用: {available_to_sell_long})"

    def _finalize_trade(self, order: Order, price: float, commission: float, dt: datetime):
        """最终完成交易，更新订单状态、账户现金和持仓。"""
        order.fill(price, commission, dt)
        self.context.order_manager.add_filled_order_to_history(order)

        pm = self.context.position_manager
        portfolio = self.context.portfolio

        gross_value = price * order.amount
        realized_pnl = pm.process_trade(order, price, dt, self.trading_mode)

        if order.side == OrderSide.BUY:
            # 开多仓或平空仓，都是现金支出
            portfolio.cash -= gross_value + commission
        else: # SELL
            # 卖出（平多仓或开空仓），都是现金流入
            portfolio.cash += gross_value - commission

        # 交易完成后，全面更新所有财务指标
        portfolio.update_financials(pm)

        # 根据是否产生实际盈亏来决定日志内容
        if realized_pnl != 0:
            self.context.logger.info(
                f"✅ 成交[{order.side.value.upper()}] {order.symbol} 数量:{order.amount} "
                f"价格:{price:.2f} | 实现盈亏: {realized_pnl - commission:.2f}"
            )
        else:
            self.context.logger.info(
                f"✅ 成交[{order.side.value.upper()}] {order.symbol} 数量:{order.amount} 价格:{price:.2f}"
            )

    def settle(self):
        """
        执行每日结算 (End-of-Day Settlement)。

        此方法在每个交易日收盘后由 `Scheduler` 调用，用于处理所有日终任务，
        确保账户状态为第二天开盘做好准备。

        结算流程:
        1.  **订单清理**:
            - 取消所有当天未成交的、非持久性的挂单（日内订单）。

        2.  **持仓估值 (Mark-to-Market)**:
            - 遍历所有持仓。
            - 获取每个持仓标的当天的收盘价。
            - 更新持仓的市值 (`market_value`) 和每日未实现盈亏 (`unrealized_pnl`)。

        3.  **账户快照**:
            - 记录当天收盘后的持仓快照 (`daily_snapshots`)。
            - 计算并记录当天的账户总净值 (`portfolio.history`)。

        4.  **T+1 规则处理**:
            - 对于遵循 T+1 规则的市场，将今天新开的仓位转换为明天可卖出的
              “可用持仓” (`available_amount`)。
        """
        self.context.logger.info("开始每日结算...")
        # 1. 取消所有当天未成交的、非历史的订单
        for order in self.context.order_manager.get_open_orders():
            if not order.is_immediate: # 通常日内循环后剩下的都是历史挂单
                order.expire()

        self.context.order_manager.clear_today_orders()
        
        # 2. 结算所有持仓
        pm = self.context.position_manager
        date_str = self.context.current_dt.strftime('%Y-%m-%d')
        snapshot_entries: List[Dict] = []

        for pos in pm.get_all_positions():
            price_data = self.context.data_provider.get_current_price(
                pos.symbol, self.context.current_dt
            )
            if (price_data and
                'current_price' in price_data and
                price_data['current_price'] is not None):
                close_price = price_data['current_price']
                settle_entry = pos.settle_day(close_price, date_str)
                if settle_entry:
                    snapshot_entries.append(settle_entry)
            else:
                self.context.logger.warning(f"无法获取 {pos.symbol} 在 {date_str} 的收盘价用于结算。")

            # T+1 规则结算：将今天开的仓位变为明天可用的仓位
            if self.context.config.get('account', {}).get('trading_rule', 'T+1') == 'T+1':
                pos.settle_t1()

        # 记录每日持仓快照，并调用新的 record_history 方法
        pm.daily_snapshots = [s for s in pm.daily_snapshots if s.get('date') != date_str]
        pm.record_daily_snapshot(date_str, snapshot_entries)
        self.context.portfolio.record_history(self.context.current_dt, pm)
        self.context.logger.info(f"结算完成, 账户净资产: {self.context.portfolio.net_worth:,.2f}")