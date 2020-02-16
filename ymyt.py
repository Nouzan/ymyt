from typing import Dict, Any, Optional, List

import aiohttp
import asyncio
from datetime import datetime, timedelta

from functools import partial

BASE = "https://api.pro.coinbase.com"                          # Coinbase API 根url
CANDLE_LEN = 300                                               # Coinbase API K线请求上限
hour = timedelta(hours=1)                                      # 1小时
BIAS = 28800                                                   # 北京时间的偏移(+8)
FIRST_FETCH = 3000                                             # 首次爬取的K线数量

STATE = None                                                   # 运行状态


async def fetch(session: aiohttp.ClientSession, url: str, params: Dict[str, Any]={}) -> Any:
    """
    发起HTTP请求
    """
    async with session.get(url, params=params) as res:
        return await res.json()

async def fetch_ohlc_part(session: aiohttp.ClientSession, symbol: str, end: Optional[int] = None, limit: int = CANDLE_LEN) -> Optional[List[list]]:
    """
    获取不超过300个K线数据(时间由近到远)
    :param session: aiohttp.ClientSession
    :param symbol: 指定爬取的交易对/标的
    :param end: 一个unix 时间戳, 指定爬取K线范围的末端时间(不包含该时间); 若未指定末端时间，则为当前时间
    :param limit: 指定爬取的K线总数
    """
    try:
        if end is None:
            # 如果没有指定末端时间，则默认末端时间为当前时间
            res = await fetch(session,
                BASE + f"/products/{symbol}/candles", params={
                'granularity': 3600,                           # 1小时
            })
        else:
            # 如果指定了末端时间，则以该时间为末端时间发起请求
            end = datetime.fromtimestamp(end - BIAS - 3600)    # TODO: 此处应处理时区问题, 这里的BIAS是北京时间, 要转换为UTC
            start = end - limit * hour                         # 计算起始时间
            res = await fetch(session,
                BASE + f"/products/{symbol}/candles", params={
                'granularity': 3600,
                'start': start.isoformat(),                    # API接收ISO格式的时间戳
                'end': end.isoformat(),
            })
        return res if type(res) == list else None              # 若返回的不是K线列表，则返回None
    except asyncio.CancelledError:
        raise
    except Exception as err:                                   # 出错则返回None
        print(f'Failed to fetch ohlc part({err})')
        await asyncio.sleep(1)
        return None

async def fetch_ohlc(session: aiohttp.ClientSession, symbol: str, limit: int) -> List[list]:
    """
    获取到当前时间为止的指定数量的K线数据(时间由近到远)
    """
    part = await fetch_ohlc_part(session, symbol)              # 请求到当前时间为止的CANDLE_LEN(300)个K线
    if part is None : raise Exception("First fetch faild")     # 后续代码都假设第一次请求是成功的，故失败时此处可报错 (TODO: 是否还有更好的解决办法?)

    end = part[-1][0]                                          # 跟踪下一次请求的末端时间
    full = part                                                # 用于放置所有的K线数据
    count = len(part)
    while count < limit:                                       # 迭代直到数量满足要求
        # print(end)
        part = await fetch_ohlc_part(session, symbol, end=end)
        if part is not None:
            count += len(part)
            full += part
            end = part[-1][0]

    return full[0:limit]                                       # 返回指定数量的K线

async def fetch_ticker(session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
    """
    获取最新成交价
    """
    try:
        res = await fetch(session, BASE + f'/products/{symbol}/ticker')
    except asyncio.CancelledError:
        raise
    except Exception as err:
        print(f"Failed to fetch ticker({err})")
        return None

    return float(res['price'])

async def timer(coroutine, interval: float=1) -> None:
    """
    协程: 实现一个定时器
    """
    while True:                                                # TODO: 提供停止功能
        await coroutine()
        await asyncio.sleep(interval)

def roll_down_to_hours(timestamp: int) -> int:
    """
    将timestamp截取到小时
    """
    return timestamp - timestamp % 3600

def calc_avg(data: Dict[int, list], start: int, count: int) -> List[float]:
    """
    计算一目均衡图中的基准线
    """
    ohlcs = [data[start + 3600 * i] for i in range(count)]     # 读取已缓存的K线数据, 并转换为K线列表
    ohlcs.reverse()                                            # 使K线变为按时间由近到远排序

    avgs = []
    for i in range(len(ohlcs) - 26 + 1):                       # 计算一目均衡图中的基准线
        M = max([ohlc[2] for ohlc in ohlcs[i:i+26]])
        m = min([ohlc[1] for ohlc in ohlcs[i:i+26]])
        avg = (M + m) / 2
        avgs.append(avg)
    return avgs

async def watcher(session: aiohttp.ClientSession, state: dict, interval: float=1) -> None:
    """
    协程: 用于定时检查目前的运行状态, 包括检查K线缓存是否完整(若不完整则请求)
    """
    while True:
        if state['ticker']\
            and state['count']\
            and state['count'] >= 26:
            # 如果已经准备好数据

            avgs = calc_avg(state['candles'], state['start'], state['count'])
            now = roll_down_to_hours(datetime.now().timestamp())

            # 显示状态
            print(f"{state['ticker']}, {state['candles'].get(now)}, {state['start'] + 3600 * state['count']}, {'牛' if state['ticker'] > avgs[0] else '熊'}")
    
        if state['start'] is not None and not state['fetching']:
            # 如果已完成第一次K线爬取，且未处于爬取状态

            # 跟踪当前已爬取的K线时间戳
            # 算法假设从start ~ start + 3600 * count的时间范围内的K线数据是完整的
            index = state['start'] + 3600 * state['count']

            while index < (datetime.now() - hour).timestamp(): # 循环直到爬取到最新K线
                if index not in state['candles']:              # 若该时间戳对应K线不存在，则爬取

                    async def fetch_one() -> None:
                        """
                        协程: 爬取一个K线
                        """
                        state['fetching'] = True
                        candle = await fetch_ohlc_part(session, 'BTC-USD', end=index + 60, limit=1)
                        state['fetching'] = False
                        if candle:
                            state['candles'][index] = candle[0]

                    asyncio.create_task(fetch_one())           # 启动爬取K线的协程
                    break
                else:
                    index += 3600
                    state['count'] += 1

        await asyncio.sleep(interval)

def crawler(session: aiohttp.ClientSession, state: dict) -> callable:
    """
    创建一个爬取K线数据、最新成交价的Polling协程
    """
    async def handle() -> None:
        """
        Polling
        """
        ticker = await fetch_ticker(session, 'BTC-USD')
        now = datetime.now()
        last_candle = await fetch_ohlc_part(session, 'BTC-USD', end=(now + hour).timestamp(), limit=1)

        if last_candle:
            last_candle = last_candle[0]
            state['candles'][last_candle[0]] = last_candle
        state['ticker'] = ticker

    return handle

async def main():
    """
    一目均衡图计算协程入口函数
    """
    global STATE
    # 管理程序的执行状态
    state = {
        'ticker': None,      # 缓存最新成交价
        'candles': {},       # 缓存K线数据
        'start': None,       # 记录起始K线时间戳
        'count': 0,          # 记录已检查的从start开始的完整K线数据数量
        'fetching': False,   # 标记是否正在爬取K线，避免watcher反复创建爬取协程
    }

    STATE = state

    try:
        async with aiohttp.ClientSession() as session:             # 创建HTTP Session
            task = asyncio.create_task(watcher(session, state))           # 启动watcher协程

            candles = await fetch_ohlc(session, 'BTC-USD', FIRST_FETCH)   # 完成首次K线爬取
            for t, l, h, o, c, v in candles:                       # 处理K线数据，以Dict[timestamp, ohlc]的格式存储
                state['candles'][t] = [t, l, h, o, c, v]

            state['start'] = min(candle[0] for candle in candles)  # 初始化起始K线时间戳
            await timer(crawler(session, state))                   # 启动定时爬取协程
    except asyncio.CancelledError:
        print("即将停止协程")
        await asyncio.sleep(1)
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())




# K线、基准线

# K线
# time: ISO
# open: float
# high: float
# low: float
# close: float

# 基准线
# time: ISO
# value: float