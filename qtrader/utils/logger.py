# qtrader/utils/logger.py

import logging
import sys
from typing import Dict, Any, Optional
from datetime import datetime

class ContextFilter(logging.Filter):
    """
    一个自定义的日志过滤器，用于将 `Context` 中的模拟时间（`current_dt`）
    动态注入到每条日志记录中。
    """
    def __init__(self, context, name=''):
        super().__init__(name)
        self.context = context

    def filter(self, record):
        """
        为日志记录动态附加 `sim_time` 属性。
        """
        sim_dt = getattr(self.context, 'current_dt', None)
        
        if sim_dt:
            record.sim_time = sim_dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            # 如果不存在模拟时间（如初始化阶段），则使用占位符以保持格式对齐。
            record.sim_time = ' ' * 19
        return True


class InMemoryLogHandler(logging.Handler):
    """
    一个自定义的日志处理器，将格式化后的日志记录存入内存缓冲区
    （`Context.log_buffer`），以便于在Web监控界面上实时展示。
    """
    def __init__(self, context, capacity: int):
        super().__init__()
        self.context = context
        self.capacity = capacity

    def emit(self, record: logging.LogRecord):
        """
        处理日志记录，将其格式化为字典并添加到内存缓冲区。
        """
        if self.context is None:
            return
        
        entry = {
            "exec_time": datetime.fromtimestamp(record.created).isoformat(timespec='seconds'),
            "sim_time": getattr(record, 'sim_time', ''),
            "level": record.levelname,
            "message": record.getMessage()
        }
        
        self.context.log_buffer.append(entry)
        overflow = len(self.context.log_buffer) - self.capacity
        if overflow > 0:
            del self.context.log_buffer[:overflow]


def setup_logger(config: Dict[str, Any], context=None) -> logging.Logger:
    """
    配置并返回一个 `qtrader` 专用的日志记录器（Logger）。

    该函数根据提供的配置，设置日志级别、格式化程序以及多个处理器
    （控制台、文件、内存），并应用 `ContextFilter` 来实现双时间戳日志
    （物理执行时间 和 策略模拟时间）。

    Args:
        config (Dict[str, Any]): 日志配置字典。
        context (Optional[Context]): 全局上下文对象，用于注入模拟时间。

    Returns:
        logging.Logger: 配置完成的日志记录器实例。
    """
    logger = logging.getLogger("qtrader")
    logger.propagate = False

    if logger.hasHandlers():
        logger.handlers.clear()

    level = getattr(logging, config.get('level', 'INFO').upper(), logging.INFO)
    logger.setLevel(level)

    # 定义包含物理执行时间 (asctime) 和模拟时间 (sim_time) 的日志格式
    log_format = '[Exec: %(asctime)s] [Sim: %(sim_time)s] - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # 添加上下文过滤器，用于注入模拟时间
    if context:
        context_filter = ContextFilter(context)
        logger.addFilter(context_filter)

    # --- 配置控制台处理器 ---
    if config.get('console_output', True):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    # --- 配置文​​件处理器 ---
    log_file = config.get('file')
    if log_file:
        try:
            fh = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            logger.error(f"无法创建日志文件 {log_file}: {e}")

    # --- 配置内存处理器 (用于Web UI) ---
    buffer_size = config.get('buffer_size', 1000)
    if context is not None:
        context.log_buffer_limit = buffer_size
        memory_handler = InMemoryLogHandler(context, buffer_size)
        memory_handler.setLevel(level)
        # 内存处理器直接生成字典，不需要 Formatter
        logger.addHandler(memory_handler)

    return logger