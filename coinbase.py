import aiohttp
import asyncio

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta


class CoinBaseApi:
    """
    CoinBase API对接库
    [CoinBase API Introdution](https://docs.pro.coinbase.com/#introduction)
    """
    BASE = "https://api.pro.coinbase.com"                      # Coinbase API 根url
    CANDLE_LEN = 300                                           # Coinbase API K线请求上限
    BJ_BIAS = 28800                                            # 北京时间的偏移(+8)
    session: aiohttp.ClientSession() = None

    async def connect(self):                                   # TODO: 可能有更好的写法
        self.session = aiohttp.ClientSession()                 # 创建HTTP Session

    async def disconnect(self):
        await self.session.close()

    async def _fetch(self, uri: str, params: Dict[str, Any]={}) -> Any:
        """
        发起HTTP请求
        """
        assert self.session is not None, "must create session before fetching"
        async with self.session.get(self.BASE + uri, params=params) as res:
            return await res.json()

    async def fetch_ohlc_part(self, symbol: str, end: Optional[int] = None, limit: int = CANDLE_LEN) -> Optional[List[list]]:
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
                res = await self._fetch(
                    f"/products/{symbol}/candles", params={
                    'granularity': 3600,                           # 1小时
                })
            else:
                # 如果指定了末端时间，则以该时间为末端时间发起请求
                end = datetime.fromtimestamp(end - self.BJ_BIAS - 3600)    # TODO: 此处应处理时区问题, 这里的BIAS是北京时间, 要转换为UTC
                hour = timedelta(hours=1)                          # 1小时
                start = end - limit * hour                         # 计算起始时间
                res = await self._fetch(
                    f"/products/{symbol}/candles", params={
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

    async def fetch_ohlc(self, symbol: str, limit: int) -> List[list]:
        """
        获取到当前时间为止的指定数量的K线数据(时间由近到远)
        """
        part = await self.fetch_ohlc_part(symbol)                  # 请求到当前时间为止的CANDLE_LEN(300)个K线
        if part is None : raise Exception("First fetch faild")     # 后续代码都假设第一次请求是成功的，故失败时此处可报错 (TODO: 是否还有更好的解决办法?)

        end = part[-1][0]                                          # 跟踪下一次请求的末端时间
        full = part                                                # 用于放置所有的K线数据
        count = len(part)
        while count < limit:                                       # 迭代直到数量满足要求
            # print(end)
            part = await self.fetch_ohlc_part(symbol, end=end)
            if part is not None:
                count += len(part)
                full += part
                end = part[-1][0]

        return full[0:limit]                                       # 返回指定数量的K线

    async def fetch_ticker(self, symbol: str) -> Optional[float]:
        """
        获取最新成交价
        """
        try:
            res = await self._fetch(f'/products/{symbol}/ticker')
        except asyncio.CancelledError:
            raise
        except Exception as err:
            print(f"Failed to fetch ticker({err})")
            return None

        return float(res['price'])