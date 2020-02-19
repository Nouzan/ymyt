from typing import Dict, Any, Optional, List, Tuple
import asyncio

def roll_down_to_hours(timestamp: int) -> int:
    """
    将timestamp截取到小时
    """
    return timestamp - timestamp % 3600

def max_min_avg(ohlcs, rng: int, high = lambda o: o[2], low = lambda o: o[1], time = lambda o: o[0]) -> List[Tuple[int, float]]:
    """
    计算前移rng范围内的最大值最小值的平均值
    """
    assert len(ohlcs) >= rng, f"长度小于{rng}"
    avgs = []
    for i in range(len(ohlcs) - rng + 1):                       # 计算一目均衡图中的基准线
        M = max([high(ohlc) for ohlc in ohlcs[i:i + rng]])
        m = min([low(ohlc) for ohlc in ohlcs[i:i + rng]])
        avg = (M + m) / 2
        avgs.append((time(ohlcs[i]), avg))
    return avgs

def move(lines, rng: int, time = lambda l: l[0], value = lambda l: l[1], scale: int=3600) -> List[Tuple[int, float]]:
    """
    时间移动操作，+为向将来平移|rng|，-为向过去平移|rng|
    """
    return [(time(line) + rng * scale, value(line)) for line in lines]