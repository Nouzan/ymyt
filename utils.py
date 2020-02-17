import asyncio

def roll_down_to_hours(timestamp: int) -> int:
    """
    将timestamp截取到小时
    """
    return timestamp - timestamp % 3600