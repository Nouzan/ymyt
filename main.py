import aiohttp
import asyncio
from datetime import datetime, timedelta

BASE = "https://api.pro.coinbase.com"
CANDLE_LEN = 300
hour = timedelta(hours=1)
BIAS = 28800 + 3600

async def fetch(session, url, params={}):
    async with session.get(url, params=params) as res:
        return await res.json()

async def fetch_part(session, symbol: str, end: int = None):
    if end is None:
        return await fetch(session, BASE + f"/products/{symbol}/candles?granularity=3600")
    else:
        end = datetime.fromtimestamp(end - BIAS)
        start = end - CANDLE_LEN * hour
        return await fetch(session, BASE + f"/products/{symbol}/candles?granularity=3600&start={start.isoformat()}&end={end.isoformat()}")

async def fetch_ohlc(session, symbol: str, limit: int):
    part = await fetch_part(session, symbol) # 最末尾的300个
    end = part[-1][0] # 下一次请求到end为止
    full = part
    count = len(part)
    while count < limit:
        # print(end)
        part = await fetch_part(session, symbol, end=end)
        count += len(part)
        full += part
        end = part[-1][0]

    return full[len(full) - limit:]

async def fetch_ticker(session, symbol: str):
    res = await fetch(session, BASE + f'/products/{symbol}/ticker')
    return float(res['price'])

def calc_avg(data):
    avgs = []
    for i in range(len(data) - 26 + 1):
        M = max([ohlc[2] for ohlc in data[i:i+26]])
        m = min([ohlc[1] for ohlc in data[i:i+26]])
        avg = (M + m) / 2
        avgs.append(avg)
    return avgs

async def main():
    async with aiohttp.ClientSession() as session:
        data = await fetch_ohlc(session, 'BTC-USD', 2600)
        ticker = await fetch_ticker(session, 'BTC-USD')
    avgs = calc_avg(data)

    if ticker > avgs[0]:
        print('牛')
    else:
        print('熊')

if __name__ == "__main__":
    asyncio.run(main())