import aiohttp
import asyncio
from datetime import datetime, timedelta

BASE = "https://api.pro.coinbase.com"
CANDLE_LEN = 300
hour = timedelta(hours=1)
BIAS = 28800 + 3600
FIRST_FETCH = 3000

async def timer(corofunc, interval=1):       # Polling: 优点: 1. 还算及时, 频率可控; 2. 实现简单; 问题: 1. 有可能不及时; 2. 有可能存在浪费; 事件源是被动的, Http协议
    while True:                              # 事件源是主动的, 我们就变为监听方, 假如我们收到一个事件, 则它必然恰好就在刚刚发生: 无确认的监听
        await corofunc()                     # 不能使用请求-响应模型, 长连接模型(半双工的连接), Websocket / TCP
        await asyncio.sleep(interval)


def roll_down_to_hours(timestamp):
    return timestamp - timestamp % 3600

async def fetch(session, url, params={}):
    async with session.get(url, params=params) as res:
        return await res.json()

async def fetch_part(session, symbol: str, end: int = None, limit: int = CANDLE_LEN):
    try:
        if end is None:
            res = await fetch(session, BASE + f"/products/{symbol}/candles?granularity=3600")
        else:
            end = datetime.fromtimestamp(end - BIAS)
            start = end - limit * hour
            res = await fetch(session, BASE + f"/products/{symbol}/candles?granularity=3600&start={start.isoformat()}&end={end.isoformat()}")
        return res if type(res) == list else None
    except Exception as err:
        print(err)
        return None

async def fetch_ohlc(session, symbol: str, limit: int):
    part = await fetch_part(session, symbol) # 最末尾的300个
    if part is None : raise Exception("First fetch faild")
    end = part[-1][0] # 下一次请求到end为止
    full = part
    count = len(part)
    while count < limit:
        print(end)
        part = await fetch_part(session, symbol, end=end)
        if part is not None:  # 失败或超时重传
            count += len(part)
            full += part
            end = part[-1][0]
        else:
            print("Retry...")

    return full[0:limit]

async def fetch_ticker(session, symbol: str):
    res = await fetch(session, BASE + f'/products/{symbol}/ticker')
    return float(res['price'])

def calc_avg(data, start, count):
    avgs = []
    ohlcs = [data[start + 3600 * i] for i in range(count)]
    ohlcs.reverse()

    for i in range(len(ohlcs) - 26 + 1):
        M = max([ohlc[2] for ohlc in ohlcs[i:i+26]])
        m = min([ohlc[1] for ohlc in ohlcs[i:i+26]])
        avg = (M + m) / 2
        avgs.append(avg)
    return avgs

async def watcher(state, session, interval=1):
    while True:
        if state['ticker'] and state['count'] and state['count'] >= 26:
            avgs = calc_avg(state['candles'], state['start'], state['count'])
            now = roll_down_to_hours(datetime.now().timestamp())
            print(f"{state['ticker']}, {state['candles'].get(now)}, {state['start'] + 3600 * state['count']}, {'牛' if state['ticker'] > avgs[0] else '熊'}")
    
        if state['start'] is not None and not state['fetching']:
            index = state['start'] + 3600 * state['count'] # START + 0
            while index < (datetime.now() - hour).timestamp():
                if index not in state['candles']:
                    async def fetch_one():
                        state['fetching'] = True
                        candle = await fetch_part(session, 'BTC-USD', end=index + 60, limit=1)
                        state['fetching'] = False
                        state['candles'][index] = candle[0]
                    asyncio.create_task(fetch_one())
                    break
                else:
                    index += 3600
                    state['count'] += 1

        await asyncio.sleep(interval)

def crawler(state, session):
    async def handle():
        ticker = await fetch_ticker(session, 'BTC-USD')
        now = datetime.now()
        if now.timestamp() % 3600 == 0:
            last_candle = await fetch_part(session, 'BTC-USD', end=now.timestamp() - 60, limit=1)
        else:
            last_candle = await fetch_part(session, 'BTC-USD', end=(now + hour).timestamp(), limit=1)
        last_candle = last_candle[0]
        state['ticker'] = ticker
        state['candles'][last_candle[0]] = last_candle

    return handle

async def main():
    state = {
        'ticker': None,
        'candles': {},
        'start': None,
        'count': 0,
        'fetching': False,
    }

    # 事件处理程序: 状态, 事件 + 状态 -> 状态

    async with aiohttp.ClientSession() as session:
        asyncio.create_task(watcher(state, session))
        candles = await fetch_ohlc(session, 'BTC-USD', 3000) # first fecth
        for t, l, h, o, c, v in candles:
            state['candles'][t] = [t, l, h, o, c, v]
        state['start'] = min(candle[0] for candle in candles)
        await timer(crawler(state, session))


if __name__ == "__main__":
    asyncio.run(main())