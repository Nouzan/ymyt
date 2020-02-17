from typing import Dict, Any, Optional, List

import aiohttp
import asyncio
from datetime import datetime, timedelta

from coinbase import CoinBaseApi
from utils import roll_down_to_hours

class Watcher:
    FIRST_FETCH = 3000                                             # 首次爬取的K线数量
    state = None                                                   # 运行状态
    api = None

    def __init__(self, polling_interval: float=1):
        self.state = {
            'ticker': None,      # 缓存最新成交价
            'candles': {},       # 缓存K线数据
            'start': None,       # 记录起始K线时间戳
            'count': 0,          # 记录已检查的从start开始的完整K线数据数量
            'fetching': False,   # 标记是否正在爬取K线，避免watcher反复创建爬取协程
        }

        self.api = CoinBaseApi()
        self.running = False
        self.task = None
        self.polling_interval = polling_interval

    async def _main(self):
        """
        入口协程
        """
        await self.api.connect()                                   # 连接CoinBase API服务器
        candles = await self.api.fetch_ohlc(                       # 完成首次K线爬取
            'BTC-USD',
            self.FIRST_FETCH
        )

        for t, l, h, o, c, v in candles:                           # 处理K线数据，以Dict[timestamp, ohlc]的格式存储
            self.state['candles'][t] = [t, l, h, o, c, v]
        self.state['start'] = min(candle[0] for candle in candles) # 初始化起始K线时间戳

        await asyncio.gather(
            self._watcher(),                                       # watcher协程
            self._crawler(),                                       # crawler协程
        )
        await self.api.disconnect()

    async def start(self) -> asyncio.Task:
        """
        启动Watcher
        """
        self.running = True
        self.task = asyncio.create_task(self._main())
        return self.task

    async def stop(self):
        """
        关闭Watcher(关闭后返回)
        """
        self.running = False
        await self.task

    def calc_avg(self, data: Dict[int, list], start: int, count: int) -> List[float]:
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
        协程: 用于定时检查目前的运行状态, 包括检查K线缓存是否完整(若不完整则请求)
        """
        while self.running:
            # Polling

            if self.state['ticker']\
                and self.state['count']\
                and self.state['count'] >= 26:
                # 如果已经准备好数据

                avgs = self.calc_avg(self.state['candles'], self.state['start'], self.state['count'])
                now = roll_down_to_hours(datetime.now().timestamp())

                # 显示状态
                print(f"{self.state['ticker']}, {self.state['candles'].get(now)}, {self.state['start'] + 3600 * self.state['count']}, {'牛' if self.state['ticker'] > avgs[0] else '熊'}")
        
            if self.state['start'] is not None and not self.state['fetching']:
                # 如果已完成第一次K线爬取，且未处于爬取状态

                # 跟踪当前已爬取的K线时间戳
                # 算法假设从start ~ start + 3600 * count的时间范围内的K线数据是完整的
                index = self.state['start'] + 3600 * self.state['count']
                hour = timedelta(hours=1)                               # 1小时
                while index < (datetime.now() - hour).timestamp():      # 循环直到爬取到最新K线
                    if index not in self.state['candles']:              # 若该时间戳对应K线不存在，则爬取
                        asyncio.create_task(self._fetch_one(index))     # 启动爬取K线的协程
                        break
                    else:
                        index += 3600
                        self.state['count'] += 1

            await asyncio.sleep(self.polling_interval)

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
            self.state['ticker'] = ticker

            await asyncio.sleep(self.polling_interval)


async def main():
    watcher = Watcher()
    task = await watcher.start()
    await task

if __name__ == "__main__":
    asyncio.run(main())
