# qtrader/utils/helpers.py

import uuid

def generate_order_id() -> str:
    """
    生成一个全局唯一的订单ID。

    基于 UUID4 算法，这能确保在高并发场景下ID的唯一性。

    Returns:
        str: 一个字符串形式的唯一ID。
    """
    return str(uuid.uuid4())