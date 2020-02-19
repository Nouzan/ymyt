from typing import Dict, Any, Optional, List, Tuple

import aiohttp
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta

from coinbase import CoinBaseApi
from utils import roll_down_to_hours, max_min_avg, move

class Watcher:
    FIRST_FETCH = 3000                                             # 首次爬取的K线数量
    LISTENER_MAX_SIZE = 3000                                       # 监听器注册队列的最大长度
    QUEUE_MAX_SIZE = 100                                           # 每个监听器的消息队列的最大长度

    state = None                                                   # 运行状态
    api = None

    def __init__(self, polling_interval: float=1):
        self.state = {
            'ticker': None,                                        # 缓存最新成交价
            'candles': {},                                         # 缓存K线数据 { t: [t, l, h, o, c, v] }
            'sorted_candles': [],                                  # 已排序的K线数据(时间递增)
            'calcs': (),                                           # 缓存基准线数据
            'start': None,                                         # 记录起始K线时间戳
            # 'count': 0,                                            # 记录已检查的从start开始的完整K线数据数量
            'lastest_t': None,                                     # 最新K线时间戳
            'fetching': False,                                     # 标记是否正在爬取K线，避免watcher反复创建爬取协程
            'last_ticker': None,                                   # 缓存上一次成交价
        }

        # self.ticker_updated_event = asyncio.Event()                # 标记ticker是否更新 TODO: 目前的实现方式是有缺陷的
        self.api = CoinBaseApi()                                   # 数据API绑定
        self.running = False                                       # 运行标志
        self.task = None                                           # _main()协程自绑定
        self.polling_interval = polling_interval                   # 定义轮询时间间隔
        self.listener_queues = asyncio.Queue(                      # 监听器注册队列
            maxsize=self.LISTENER_MAX_SIZE
        )
        self.listeners = []                                        # 监听器列表

    async def _main(self):
        """
        入口协程
        """
        await asyncio.gather(
            # self._watcher(),                                     # _watcher协程(现在不再单独执行，与_crawler一起执行)
            self._crawler(),                                       # _crawler协程
        )
        await self.api.disconnect()

    async def _init(self):
        """
        初始化
        """
        await self.api.connect()                                   # 连接CoinBase API服务器
        candles = await self.api.fetch_ohlc(                       # 完成首次K线爬取
            'BTC-USD',
            self.FIRST_FETCH
        )

        for t, l, h, o, c, v in candles:                           # 处理K线数据，以Dict[timestamp, ohlc]的格式存储
            self.state['candles'][t] = [t, l, h, o, c, v]
        self.state['start'] = min(candle[0] for candle in candles) # 初始化起始K线时间戳

    async def start(self) -> asyncio.Task:
        """
        启动Watcher
        """
        self.running = True
        await self._init()
        self.task = asyncio.create_task(self._main())
        return self.task

    async def stop(self):
        """
        关闭Watcher(关闭后返回)
        """
        self.running = False
        await self.task

    def _get_ohlcs_for_calc(self) -> List[list]:
        ohlcs = deepcopy(self.state['sorted_candles'])             # 读取已缓存的K线数据, 并转换为K线列表
        if ohlcs[-1][0] + 3600 in self.state['candles']:           # 边界情况
            ohlcs.append(self.state['candles'][ohlcs[-1][0] + 3600])
        ohlcs.reverse()                                            # 使K线变为按时间由近到远排序
        return ohlcs

    def calc(self) -> Tuple[List[Tuple[int, float]]]:
        """
        计算一目均衡图中的转折线, 基准线, 延迟线, 先行线A与先行线B
        """
        ohlcs = self._get_ohlcs_for_calc()
        turns = max_min_avg(ohlcs, 9)
        bases = max_min_avg(ohlcs, 26)
        delays = move(ohlcs, -26, value=lambda o: o[4])
        _turn_base_avgs = [ (z[0][0], (z[0][1] + z[1][1]) / 2) for z in zip(turns, bases)]
        antes_1 = move(_turn_base_avgs, 26)
        _max_min_avg52s = max_min_avg(ohlcs, 52)
        antes_2 = move(_max_min_avg52s, 26)
        return turns, bases, delays, antes_1, antes_2

    async def subscribe(self) -> asyncio.Queue:
        """
        协程: 向Watcher注册一个监听者消息队列
        """
        await self.listener_queues.put(None)
        queue = asyncio.Queue(maxsize=self.QUEUE_MAX_SIZE)
        self.listeners.append(queue)
        return queue

    async def unsubscribe(self, queue):
        """
        协程: 向Watcher注销一个监听者消息队列
        """
        if queue in self.listeners:
            self.listeners.remove(queue)
            await self.listener_queues.get()

    async def _fetch_one(self, index) -> None:
        """
        协程: 爬取一个K线
        """
        self.state['fetching'] = True
        candle = await self.api.fetch_ohlc_part('BTC-USD', end=index + 60, limit=1)
        self.state['fetching'] = False
        if candle:
            self.state['candles'][index] = candle[0]

    async def _watcher(self) -> None:
        """
        协程: 用于检查目前的运行状态, 包括检查K线缓存是否完整(若不完整则请求)
        """
        if self.state['ticker'] and len(self.state['sorted_candles']) >= 52:
            # 如果已经准备好数据

            calcs = self.calc()
            self.state['calcs'] = calcs
            now = roll_down_to_hours(datetime.now().timestamp())

            # 显示状态
            # print(f"{self.state['ticker']}, {self.state['candles'].get(now)}, {self.state['sorted_candles'][-1]}, {len(self.listeners)}")

        if self.state['start'] is not None and not self.state['fetching']:
            # 如果已完成第一次K线爬取，且未处于爬取状态

            # 跟踪当前已爬取的K线时间戳
            # 算法假设从start ~ start + 3600 * count的时间范围内的K线数据是完整的
            index = self.state['start'] + 3600 * len(self.state['sorted_candles'])
            hour = timedelta(hours=1)                               # 1小时
            while index < (datetime.now() - hour).timestamp():      # 循环检查直到最新K线
                if index not in self.state['candles']:              # 若该时间戳对应K线不存在，则爬取
                    asyncio.create_task(self._fetch_one(index))     # 启动爬取K线的协程
                    break
                else:
                    self.state['sorted_candles'].append(self.state['candles'][index])
                    index += 3600

        if self.state['ticker'] != self.state['last_ticker'] and len(self.state['candles']) > 0 and self.state['lastest_t']:
            self.state['last_ticker'] = self.state['ticker']

            candle_len = len(self.state['sorted_candles'])
            last_candle = self.state['candles'][self.state['lastest_t']]
            if last_candle[0] == self.state['sorted_candles'][-1][0]:
                candle_len -= 1
            for queue in self.listeners:
                asyncio.create_task(queue.put({
                    'ticker': self.state['ticker'],
                    'candles': candle_len,
                    'last_candle': last_candle,
                    'calcs': self.state['calcs'],
                }))
            # self.ticker_updated_event.set()
        # else:
        #     self.ticker_updated_event.clear()

    # async def wait_for_ticker(self) -> None:
    #     await self.ticker_updated_event.wait()
    #     # print("ticker update!")
    #     self.ticker_updated_event.clear()

    def get_candles(self) -> List[list]:
        candles = deepcopy(self.state['sorted_candles'])
        last_candle = self.state['candles'][self.state['lastest_t']]
        candles.append(last_candle)
        return candles

    def get_calcs(self) -> Tuple[List[Tuple[int, float]]]:
        calcs = deepcopy(self.state['calcs'])
        return calcs

    async def next(self, queue: asyncio.Queue) -> Tuple[List[list], Tuple[List[Tuple[int, float]]]]:
        if queue in self.listeners:
            update = await queue.get()
            queue.task_done()
            return (
                self.state['sorted_candles'][:update['candles']] + [update['last_candle']],
                update['calcs'],
            )
        else:
            return None

    async def _crawler(self) -> None:
        """
        协程: 创建一个爬取K线数据、最新成交价的Polling协程
        """
        while self.running:
            # Polling

            ticker = await self.api.fetch_ticker('BTC-USD')
            now = datetime.now()
            hour = timedelta(hours=1)                                   # 1小时
            last_candle = await self.api.fetch_ohlc_part('BTC-USD', end=(now + hour).timestamp(), limit=1)

            if last_candle:
                last_candle = last_candle[0]
                self.state['candles'][last_candle[0]] = last_candle
                self.state['lastest_t'] = last_candle[0]

            if ticker:
                self.state['ticker'] = ticker
                if self.state['lastest_t']:
                    # 用最新ticker更新K线数据
                    assert self.state['lastest_t'] in self.state['candles'], "最新K线时间必然已被保存！"
                    candle = self.state['candles'][self.state['lastest_t']]
                    candle[4] = ticker
                    if candle[1] > ticker:
                        candle[1] = ticker

                    if candle[2] < ticker:
                        candle[2] = ticker
            asyncio.create_task(self._watcher())                        # 此处启动_watcher协程
            await asyncio.sleep(self.polling_interval)

async def main():
    watcher = Watcher()
    task = await watcher.start()
    await task

if __name__ == "__main__":
    asyncio.run(main())
