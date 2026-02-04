# qtrader/core/config.py

import yaml
import logging
from typing import Dict, Any
from pydantic import ValidationError
from ..configs.config_schema import MinimalQTraderConfig

def load_config(config_path: str) -> Dict[str, Any]:
    """
    从指定路径加载YAML配置文件。

    Args:
        config_path: YAML配置文件的路径。

    Returns:
        包含配置信息的字典。
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"错误: 配置文件 {config_path} 未找到。")
        raise
    except yaml.YAMLError as e:
        logging.error(f"错误: 解析配置文件 {config_path} 失败: {e}")
        raise

    try:
        MinimalQTraderConfig.model_validate(config_dict)
        logging.debug(f"配置文件 {config_path} 加载并验证成功。")
        return config_dict
    except ValidationError as e:
        logging.error(f"错误: 配置文件 {config_path} 内容不符合规范。\n{e}")
        raise