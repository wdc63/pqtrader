# qtrader/analysis/integrated_server.py

import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from flask import Flask, render_template, jsonify, request, send_file, Response
from flask_socketio import SocketIO
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from jinja2 import Environment, FileSystemLoader, select_autoescape
from ..core.context import Context
from ..core.workspace_manager import WorkspaceManager
import pandas as pd
import numpy as np
import empyrical as em
import json
import math
from datetime import datetime

class WorkspaceFileHandler(FileSystemEventHandler):
    """
    监听工作区文件变化，用于触发服务器端数据更新。

    Attributes:
        server (IntegratedServer): 集成服务器实例。
        last_update (float): 上次更新的时间戳。
        update_cooldown (float): 更新冷却时间，防止过于频繁的触发。
    """
    
    def __init__(self, server):
        self.server = server
        self.last_update = time.time()
        self.update_cooldown = 0.5
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        filename = Path(event.src_path).name
        monitored_files = [
            'backtest.log', 'equity.csv', 'daily_positions.csv',
            'orders.csv', 'pnl_pairs.csv', 'state.pkl'
        ]
        if filename in monitored_files:
            current_time = time.time()
            if current_time - self.last_update > self.update_cooldown:
                self.last_update = current_time
                self.server.trigger_update()


class IntegratedServer:
    """
    提供回测和实时交易监控的集成Web服务器。

    该服务器使用 Flask 和 SocketIO 构建，提供以下功能:
    - 实时展示回测或交易过程中的各项指标。
    - 通过Web界面控制策略引擎（暂停、恢复、停止）。
    - 生成静态HTML回测报告。
    - 监控工作区文件变化，自动刷新前端数据。
    """
    
    def __init__(
        self, 
        context: Context, 
        workspace_manager: WorkspaceManager,
        config: Dict[str, Any]
    ):
        self.context = context
        self.workspace_manager = workspace_manager
        self.config = config
        
        template_folder_path = Path(__file__).parent / 'templates'

        self.app = Flask(
            __name__,
            template_folder=str(template_folder_path),
            static_folder=str(Path(__file__).parent / 'static')
        )
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(template_folder_path)),
            autoescape=select_autoescape(['html', 'xml'])
        )

        self.observer = Observer()
        self.file_handler = WorkspaceFileHandler(self)
        
        self.server_thread: Optional[threading.Thread] = None
        self.update_lock = threading.Lock()
        self.should_update = False
        
        self._setup_routes()
        self._setup_socketio()

    def generate_final_report(self, output_path: str, context: Context):
        """
        生成最终的静态HTML回测报告。

        Args:
            output_path (str): 报告输出路径。
            context (Context): 包含所有回测数据的上下文对象。
        """
        original_context = self.context
        self.context = context
        
        try:
            # 收集所有数据
            overview_data = self._collect_overview_data()
            performance_data = self._collect_performance_data()
            positions_data = self._collect_positions_data()
            orders_data = self._collect_orders_data()
            logs_data = self._collect_logs_data()
            snapshots_data = self._collect_snapshots_data()

            def clean_data(obj):
                """
                使用自定义JSON编码器递归清理数据，处理特殊类型。
                """
                json_str = json.dumps(obj, cls=CustomJSONEncoder, ensure_ascii=False)
                return json.loads(json_str)

            # 清理所有数据
            overview_data = clean_data(overview_data)
            performance_data = clean_data(performance_data)
            positions_data = clean_data(positions_data)
            orders_data = clean_data(orders_data)
            logs_data = clean_data(logs_data)
            snapshots_data = clean_data(snapshots_data)

            # 加载模板
            template = self.jinja_env.get_template('integrated_monitor.html')

            # 渲染 HTML
            html_content = template.render(
                is_static_report=True,
                strategy_name=context.strategy_name,
                start_date=context.start_date,
                end_date=context.end_date,
                initial_cash=f"{context.config.get('account', {}).get('initial_cash', 0):,}",
                overview=overview_data,
                performance=performance_data,
                positions=positions_data,
                orders=orders_data,
                logs=logs_data,
                snapshots=snapshots_data,
            )

            # 保存文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.context.logger.info(f"回测报告已生成: {output_path}")

        except Exception as e:
            self.context.logger.error(f"生成报告失败: {e}", exc_info=True)
        finally:
            self.context = original_context

    def _setup_routes(self):
        """设置 Flask Web 服务的路由。"""
        
        @self.app.route('/')
        def index():
            """渲染主监控页面。"""
            return render_template(
                'integrated_monitor.html',
                is_static_report=False,
                strategy_name=self.context.strategy_name or "Loading...",
                start_date=self.context.start_date or "-",
                end_date=self.context.end_date or "-",
                initial_cash="Loading..."
            )
        
        @self.app.route('/api/initial_data')
        def get_initial_data():
            """提供API端点，用于获取所有模块的初始数据。"""
            try:
                data = {
                    'overview': self._collect_overview_data(),
                    'performance': self._collect_performance_data(),
                    'positions': self._collect_positions_data(),
                    'orders': self._collect_orders_data(),
                    'logs': self._collect_logs_data(),
                    'snapshots': self._collect_snapshots_data(),
                    'timestamp': time.time()
                }
                json_str = json.dumps(data, cls=CustomJSONEncoder, ensure_ascii=False)
                return Response(json_str, content_type='application/json; charset=utf-8')
            except Exception as e:
                self.context.logger.error(f"获取初始数据失败: {e}", exc_info=True)
                # 在异常情况下，也使用自定义Encoder返回一个安全的回退数据结构
                fallback_data = {
                    'overview': {},
                    'performance': {'trade_metrics': [], 'pnl_pairs': []},
                    'positions': {'daily_positions': []},
                    'orders': {'orders': []},
                    'logs': [{'message': f'Error fetching data: {e}'}],
                    'snapshots': {'code': '', 'config': '', 'data_provider': ''},
                    'timestamp': time.time()
                }
                
                # 即使是回退数据，也要通过我们的Encoder进行序列化，以防万一
                json_str = json.dumps(fallback_data, cls=CustomJSONEncoder, ensure_ascii=False)
                return Response(json_str, status=200, content_type='application/json; charset=utf-8')

        @self.app.route('/api/download/<filename>')
        def download_file(filename):
            """提供API端点，用于下载工作区文件。"""
            try:
                file_path = self.workspace_manager.workspace_dir / filename
                if file_path.exists():
                    return send_file(str(file_path), as_attachment=True)
                return jsonify({'error': 'File not found'}), 404
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/control', methods=['POST'])
        def control():
            """提供API端点，用于控制回测引擎（暂停、恢复、停止）。"""
            try:
                data = request.get_json()
                action = data.get('action')
                
                if action == 'pause':
                    self.context.engine.pause()
                    self.trigger_update()
                    return jsonify({'status': 'paused'})
                elif action == 'resume':
                    self.context.engine.resume_running()
                    self.trigger_update()
                    return jsonify({'status': 'resumed'})
                elif action == 'stop':
                    self.context.engine.stop()
                    self.trigger_update()
                    return jsonify({'status': 'stopped'})
                elif action == 'shutdown_server':
                    self.stop()
                    return jsonify({'status': 'server_shutdown'})
                
                return jsonify({'error': 'Unknown action'}), 400
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    
    def _setup_socketio(self):
        """设置 SocketIO 事件处理器。"""
        
        @self.socketio.on('connect')
        def handle_connect():
            self.context.logger.debug("前端已连接")
            self.trigger_update()
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            self.context.logger.debug("前端已断开")
    
    def start(self):
        """启动集成监控服务器和文件系统观察器。"""
        port = self.config.get('port', 8050)
        
        workspace_dir = str(self.workspace_manager.workspace_dir)
        self.observer.schedule(self.file_handler, workspace_dir, recursive=False)
        self.observer.start()
        self.context.logger.info(f"文件监控已启动: {workspace_dir}")
        
        self.server_thread = threading.Thread(
            target=lambda: self.socketio.run(
                self.app,
                host='0.0.0.0',
                port=port,
                debug=False,
                use_reloader=False,
                log_output=False
            ), daemon=True
        )
        self.server_thread.start()
        self.context.logger.info(f"监控服务器已启动: http://localhost:{port}")
    
    def stop(self):
        """停止集成监控服务器和文件系统观察器。"""
        try:
            self.observer.stop()
            self.observer.join()
            self.context.logger.info("监控服务器已停止")
        except Exception as e:
            self.context.logger.error(f"停止服务器失败: {e}")
    
    def trigger_update(self):
        """触发向前端的异步数据更新。"""
        with self.update_lock:
            if not self.should_update:
                self.should_update = True
                threading.Thread(target=self._do_update, daemon=True).start()
    
    def _do_update(self):
        """执行实际的数据收集和发送更新。"""
        time.sleep(0.05)
        
        with self.update_lock:
            if not self.should_update:
                return
            self.should_update = False
        
        try:
            data = {
                'overview': self._collect_overview_data(),
                'performance': self._collect_performance_data(),
                'positions': self._collect_positions_data(),
                'orders': self._collect_orders_data(),
                'logs': self._collect_logs_data(),
                'snapshots': self._collect_snapshots_data(),
                'timestamp': time.time()
            }
            
            # 序列化数据以处理特殊类型
            json_str = json.dumps(data, cls=CustomJSONEncoder, ensure_ascii=False)
            clean_data = json.loads(json_str)
            
            self.socketio.emit('update', clean_data)
        except Exception as e:
            if self.context and self.context.logger:
                self.context.logger.warning(f"更新数据失败: {e}", exc_info=True)
    
    def _collect_overview_data(self) -> Dict[str, Any]:
        """收集核心概览数据，包括投资组合价值、基准、图表等。"""
        try:
            portfolio = self.context.portfolio
            positions_value = sum(
                pos.market_value for pos in self.context.position_manager.get_all_positions()
            )
            portfolio_returns = portfolio.returns

            benchmark_returns = self.context.benchmark_manager.get_current_returns()
            benchmark_value = self.context.benchmark_manager.get_current_value()
            benchmark_name = self.context.benchmark_manager.benchmark_name
            
            history_df = self.context.portfolio.history.copy()
            equity_df = pd.DataFrame(history_df)
            benchmark_df = pd.DataFrame(self.context.benchmark_manager.get_benchmark_data())
            
            chart_data = {}
            if not equity_df.empty:
                dates = equity_df['date'].tolist()
                strategy_values = equity_df['total_value'].round(2).tolist()
                if not benchmark_df.empty:
                    benchmark_map = {row['date']: row['value'] for _, row in benchmark_df.iterrows()}
                else:
                    benchmark_map = {}
                
                benchmark_values = [
                    round(benchmark_map.get(d, portfolio.initial_cash), 2) for d in dates
                ]
                chart_data = {
                    "dates": dates, "strategy_values": strategy_values,
                    "benchmark_values": benchmark_values, "initial_cash": portfolio.initial_cash,
                }
            
            intraday_equity_data = {}
            intraday_benchmark_data = {}
            # 获取当日的初始资金，用于计算日内收益率
            if portfolio.history:
                initial_cash_today = portfolio.history[-1]['total_value']
            else:
                initial_cash_today = portfolio.initial_cash
            
            intraday_enabled = self.context.config.get('engine', {}).get('enable_intraday_statistics', False)
            
            if intraday_enabled and self.context.intraday_equity_history:
                intraday_history = self.context.intraday_equity_history.copy()
                intraday_df = pd.DataFrame(intraday_history)
                if not intraday_df.empty and initial_cash_today > 0:
                    values = intraday_df['total_value'].round(2).tolist()
                    returns_series = (intraday_df['total_value'] / initial_cash_today - 1) * 100
                    returns = returns_series.round(2).tolist()
                    intraday_equity_data = {
                        "times": intraday_df['time'].tolist(),
                        "values": values,
                        "returns": returns,
                    }
                    if portfolio_returns:
                        portfolio_returns = round((1+portfolio_returns) * (1+returns[-1]/100)-1,4)
                    else:
                        portfolio_returns = round(returns[-1]/100,4)

                if self.context.intraday_benchmark_history:
                    benchmark_history = self.context.intraday_benchmark_history.copy()
                    benchmark_df = pd.DataFrame(benchmark_history)
                    if not benchmark_df.empty and initial_cash_today > 0:
                        values = benchmark_df['value'].round(2).tolist()
                        returns_series = (benchmark_df['value'] / initial_cash_today - 1) * 100
                        returns = returns_series.round(2).tolist()
                        intraday_benchmark_data = {
                            "times": benchmark_df['time'].tolist(),
                            "values": values,
                            "returns": returns,
                        }
                        if benchmark_returns:
                            benchmark_returns = round((1+benchmark_returns) * (1+returns[-1]/100)-1,4)
                        else:
                            benchmark_returns = round(returns[-1]/100,4)

            return {
                'strategy_name': self.context.strategy_name,
                'mode': self.context.mode,
                'market_phase': self.context.market_phase,
                'strategy_error_today': self.context.strategy_error_today,
                
                'frequency': self.context.frequency,
                'current_dt': self.context.current_dt.isoformat() if self.context.current_dt else None,
                'is_running': self.context.is_running,
                'is_paused': self.context.is_paused,
                'start_date': self.context.start_date, 'end_date': self.context.end_date,
                'portfolio': {
                    'total_value': round(portfolio.cash + positions_value, 2),
                    'cash': portfolio.cash,
                    'positions_value': positions_value,
                    'returns': portfolio_returns,
                    'initial_cash': portfolio.initial_cash,
                    'margin': portfolio.margin,
                    'available_cash': portfolio.available_cash,
                },
                'benchmark': {
                    'returns': benchmark_returns,
                    'value': benchmark_value,
                    'name': benchmark_name
                },
                'equity_curve': chart_data,
                'intraday_equity': {
                    'enabled': intraday_enabled,
                    'data': intraday_equity_data,
                    'benchmark_data': intraday_benchmark_data,
                    'current_date': self.context.current_dt.strftime('%Y-%m-%d') if self.context.current_dt else None,
                    'initial_cash_today': initial_cash_today,
                },
                'risk_metrics': self._calculate_risk_metrics(),
            }
        
        except Exception as e:
            self.context.logger.warning(f"收集概览数据失败: {e}")
            return {}
    
    def _collect_performance_data(self) -> Dict[str, Any]:
        """收集交易性能指标和盈亏对数据。"""
        try:
            from ..analysis.performance import PerformanceAnalyzer
            analyzer = PerformanceAnalyzer(self.context)
            return {
                'trade_metrics': analyzer.summary,
                'pnl_pairs': analyzer.pnl_df.to_dict('records') if not analyzer.pnl_df.empty else [],
            }
        except Exception as e:
            self.context.logger.warning(f"收集性能数据失败: {e}")
            return {'trade_metrics': [], 'pnl_pairs': []}
    
    def _collect_positions_data(self) -> Dict[str, Any]:
        """收集每日和盘中的持仓数据。"""
        try:
            # 1. 获取历史每日持仓快照
            # 从 position_manager 复制一份历史快照，以免修改原始数据
            position_snapshots = [s for s in (self.context.position_manager.daily_snapshots or [])]

            # 如果开启盘中统计且正在运行，则生成并附加实时持仓快照
            settle_time_str = self.context.config.get('lifecycle', {}).get('hooks', {}).get(
                'broker_settle', '15:30:00'
            )
            settle_time = datetime.strptime(settle_time_str, "%H:%M:%S").time()
            intraday_enabled = self.context.config.get('engine', {}).get('enable_intraday_statistics', False)
            if intraday_enabled and self.context.is_running and self.context.current_dt and (self.context.current_dt.time() < settle_time):
                live_positions = []
                current_dt = self.context.current_dt
                date_str = current_dt.strftime('%Y-%m-%d')
                
                for pos in self.context.position_manager.get_all_positions():
                    if pos.total_amount == 0: continue
                    
                    # 为了计算实时市值和盈亏，需要获取最新价格
                    price_data = self.context.data_provider.get_current_price(pos.symbol, current_dt)
                    current_price = price_data['current_price'] if (price_data and price_data.get('current_price')) else pos.current_price
                    
                    # 计算当日盈亏 (当前价 vs 昨日结算价)
                    from ..trading.position import PositionDirection
                    # 根据持仓方向计算当日盈亏
                    direction_multiplier = 1 if pos.direction == PositionDirection.LONG else -1
                    daily_pnl = (current_price - pos.last_settle_price) * pos.total_amount * direction_multiplier
                    base_value = abs(pos.last_settle_price * pos.total_amount)
                    daily_pnl_ratio = (daily_pnl / base_value) if base_value > 0 else 0.0

                    live_positions.append({
                        "date": date_str, "symbol": pos.symbol, "symbol_name": pos.symbol_name,
                        "direction": pos.direction.value,
                        "amount": pos.total_amount,
                        "close_price": current_price,
                        "market_value": abs(pos.total_amount * current_price),
                        "daily_pnl": daily_pnl,
                        "daily_pnl_ratio": daily_pnl_ratio
                    })
                
                # 如果存在实时持仓，将其作为今日的快照
                # 如果今天已经有快照（例如，盘后恢复），则替换它
                if live_positions:
                    # 移除今天可能已存在的旧快照
                    position_snapshots = [s for s in position_snapshots if s['date'] != date_str]
                    position_snapshots.append({"date": date_str, "positions": live_positions})

            # 基于 portfolio 历史构建最终输出，并为每天增加现金条目
            portfolio_history = self.context.portfolio.history
            if not portfolio_history and not position_snapshots:
                return {'daily_positions': []}

            # 将股票持仓快照按日期分组，方便查找
            positions_by_date = {s['date']: s['positions'] for s in position_snapshots}
            
            # 使用 portfolio 历史作为基础，因为它包含了每日的现金信息
            new_daily_snapshots = []
            
            # 复制一份 history 以免修改原始数据
            history_to_process = [h for h in portfolio_history]
            
            # 如果有今日仓位（盘中模式或停止的报告），且 portfolio.history 中还没有今天的数据点，
            today_str = None
            if self.context.current_dt:
                today_str = self.context.current_dt.strftime('%Y-%m-%d')
            if today_str and positions_by_date.get(today_str, None):
                if not any(h['date'] == today_str for h in history_to_process):
                    history_to_process.append({
                        'date': today_str,
                        'cash': self.context.portfolio.cash
                    })

            for daily_record in history_to_process:
                date_str = daily_record['date']
                cash_value = daily_record['cash']
                
                # 获取当天的股票持仓，如果当天没有股票持仓则返回空列表
                stock_positions = positions_by_date.get(date_str, [])
                
                # 创建现金持仓条目
                cash_entry = {
                    "date": date_str,
                    "symbol": "-",
                    "symbol_name": "现金",
                    "direction": "-",
                    "amount": "-",
                    "close_price": "-",
                    "market_value": cash_value,
                    "daily_pnl": "-",
                    "daily_pnl_ratio": "-"
                }
                
                # 合并当天的股票持仓和现金持仓（现金在后）
                all_entries_for_day = stock_positions + [cash_entry]
                
                new_daily_snapshots.append({
                    "date": date_str,
                    "positions": all_entries_for_day
                })

            # 按日期倒序排列，最新的在前面
            return {'daily_positions': sorted(new_daily_snapshots, key=lambda x: x['date'], reverse=True)}
        
        except Exception as e:
            self.context.logger.warning(f"从Context收集持仓数据失败: {e}", exc_info=True)
            return {'daily_positions': []}

    def _collect_orders_data(self) -> Dict[str, Any]:
        """收集所有订单数据。"""
        try:
            orders = self.context.order_manager.get_all_orders().copy()
            all_orders = [
                order for order in orders
                if order.status.value != 'rejected'
            ]
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
            # 按创建时间倒序排列
            if orders_data:
                orders_data.sort(key=lambda x: x['created_time'] or '', reverse=True)
            return {'orders': orders_data}
        
        except Exception as e:
            self.context.logger.warning(f"从Context收集订单数据失败: {e}")
            return {'orders': []}

    def _collect_logs_data(self) -> Dict[str, Any]:
        """收集日志数据，优先从内存缓冲区读取。"""
        try:
            return {'logs': self.context.log_buffer or []}
        except Exception:
            # 如果内存缓冲区不可用，则回退到读取文件
            logs, log_file = [], self.workspace_manager.log_file
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f.readlines()[-1000:]:
                            logs.append({'message': line.strip()})
                except Exception as e:
                    pass
            return {'logs': logs}

    def _collect_snapshots_data(self) -> Dict[str, Any]:
        """收集策略代码、配置和数据提供者的快照。"""
        data = {'code': "", 'config': "", 'data_provider': ""}
        files = {
            "code": "snapshot_code.py", "config": "snapshot_config.yaml",
            "data_provider": "snapshot_data_provider.py"
        }
        for key, filename in files.items():
            file_path = self.workspace_manager.workspace_dir / filename
            if file_path.exists():
                try:
                    data[key] = file_path.read_text(encoding='utf-8')
                except Exception:
                    pass
        return data
    
    def _read_positions_csv(self) -> List[Dict]:
        csv_file = self.workspace_manager.positions_csv
        if csv_file.exists() and csv_file.stat().st_size > 0:
            try:
                df = pd.read_csv(csv_file)
                result = []
                for date, date_df in df.groupby('date'):
                    result.append({'date': date, 'positions': date_df.to_dict('records')})
                return sorted(result, key=lambda x: x['date'], reverse=True)
            except Exception:
                pass
        return []
    
    def _read_orders_csv(self) -> List[Dict]:
        csv_file = self.workspace_manager.orders_csv
        if csv_file.exists() and csv_file.stat().st_size > 0:
            try:
                df = pd.read_csv(csv_file).sort_values(by='created_time', ascending=False)
                return df.to_dict('records')
            except Exception:
                pass
        return []

    def _calculate_risk_metrics(self) -> List[Dict[str, Any]]:
        """
        计算投资组合的风险指标。

        采用渐进式计算，以在回测早期提供更好的用户体验。
        """
        default_metrics = [
                {"key": "年化收益率", "value": "0.00%", "raw": 0},
                {"key": "累计收益率", "value": "0.00%", "raw": 0},
                {"key": "基准年化收益率", "value": "0.00%", "raw": 0},
                {"key": "年化波动率", "value": "N/A", "raw": 0},
                {"key": "夏普比率", "value": "N/A", "raw": 0},
                {"key": "最大回撤", "value": "0.00%", "raw": 0},
                {"key": "卡玛比率", "value": "N/A", "raw": 0},
                {"key": "阿尔法", "value": "N/A", "raw": 0},
                {"key": "贝塔", "value": "N/A", "raw": 0},
            ]
        try:
            history = self.context.portfolio.history.copy()
            history_df = pd.DataFrame(self.context.portfolio.history)
            
            # --- 第1天或之前：返回带占位符的默认指标列表 ---
            if len(history_df) < 2:
                return default_metrics

            returns = history_df['total_value'].pct_change().dropna()
            benchmark_df = pd.DataFrame(self.context.benchmark_manager.get_benchmark_data())
            
            returns.index = pd.to_datetime(history_df['date'].iloc[1:])
            
            if not benchmark_df.empty and 'value' in benchmark_df.columns:
                benchmark_returns = benchmark_df['value'].pct_change().dropna()
                benchmark_returns.index = pd.to_datetime(benchmark_df['date'].iloc[1:])
                returns, benchmark_returns = returns.align(benchmark_returns, join='inner')
            else:
                benchmark_returns = pd.Series()

            metrics = []

            # --- 第2天：只有1个收益率数据点 ---
            if len(returns) < 2:
                metrics.append({"key": "年化收益率", "value": f"{em.annual_return(returns):.2%}", "raw": em.annual_return(returns)})
                metrics.append({"key": "累计收益率", "value": f"{em.cum_returns_final(returns):.2%}", "raw": em.cum_returns_final(returns)})
                if not benchmark_returns.empty:
                    metrics.append({"key": "基准年化收益率", "value": f"{em.annual_return(benchmark_returns):.2%}", "raw": em.annual_return(benchmark_returns)})
                else:
                    metrics.append({"key": "基准年化收益率", "value": "0.00%", "raw": 0})
                metrics.append({"key": "年化波动率", "value": "N/A", "raw": 0})
                metrics.append({"key": "夏普比率", "value": "N/A", "raw": 0})
                metrics.append({"key": "最大回撤", "value": f"{em.max_drawdown(returns):.2%}", "raw": em.max_drawdown(returns)})
                metrics.append({"key": "卡玛比率", "value": "N/A", "raw": 0})
                metrics.append({"key": "阿尔法", "value": "N/A", "raw": 0})
                metrics.append({"key": "贝塔", "value": "N/A", "raw": 0})
                return metrics

            # --- 第3天及以后：有足够的收益率数据点 ---
            annual_volatility = em.annual_volatility(returns)
            max_dd = em.max_drawdown(returns)

            metrics.append({"key": "年化收益率", "value": f"{em.annual_return(returns):.2%}", "raw": em.annual_return(returns)})
            metrics.append({"key": "累计收益率", "value": f"{em.cum_returns_final(returns):.2%}", "raw": em.cum_returns_final(returns)})
            if not benchmark_returns.empty:
                metrics.append({"key": "基准年化收益率", "value": f"{em.annual_return(benchmark_returns):.2%}", "raw": em.annual_return(benchmark_returns)})
            else:
                metrics.append({"key": "基准年化收益率", "value": "0.00%", "raw": 0})
            metrics.append({"key": "年化波动率", "value": f"{annual_volatility:.2%}", "raw": annual_volatility})

            # 仅在波动率不为零时计算夏普比率，避免除零错误
            # 仅在波动率不为零时计算夏普比率，避免除零错误
            sharpe = em.sharpe_ratio(returns) if annual_volatility > 1e-6 else 0
            metrics.append({"key": "夏普比率", "value": f"{sharpe:.2f}" if annual_volatility > 1e-6 else "N/A", "raw": sharpe})
            
            metrics.append({"key": "最大回撤", "value": f"{max_dd:.2%}", "raw": max_dd})

            calmar = em.calmar_ratio(returns) if max_dd != 0 else 0
            metrics.append({"key": "卡玛比率", "value": f"{calmar:.2f}" if max_dd != 0 else "N/A", "raw": calmar})

            if not benchmark_returns.empty:
                try: 
                    alpha_val = em.alpha(returns, benchmark_returns)
                    metrics.append({"key": "阿尔法", "value": f"{alpha_val:.3f}", "raw": alpha_val})
                except Exception: metrics.append({"key": "阿尔法", "value": "N/A", "raw": 0})
                try: 
                    beta_val = em.beta(returns, benchmark_returns)
                    metrics.append({"key": "贝塔", "value": f"{beta_val:.3f}", "raw": beta_val})
                except Exception: metrics.append({"key": "贝塔", "value": "N/A", "raw": 0})
            else:
                metrics.append({"key": "阿尔法", "value": "N/A", "raw": 0})
                metrics.append({"key": "贝塔", "value": "N/A", "raw": 0})
            
            return metrics
            
        except Exception as e:
            self.context.logger.warning(f"计算风险指标时发生错误: {e}", exc_info=True)
            # 在任何未知异常下，返回安全的默认值
            return default_metrics

class CustomJSONEncoder(json.JSONEncoder):
    """
    自定义 JSON 编码器，用于序列化 pandas 和 numpy 的特殊数据类型。
    """
    
    def default(self, obj):
        try:
            if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                return None
            if isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat() if obj else None
            elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif pd.isna(obj):
                return None
            return super().default(obj)
        except:
            return str(obj)