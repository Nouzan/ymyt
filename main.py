from typing import List

from fastapi import FastAPI, Query, Cookie, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.websockets import WebSocket

import random
from datetime import datetime
import asyncio

from ymyt import Watcher

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="media"), name="media")
templates = Jinja2Templates(directory="templates")
watcher = Watcher()

class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float

class Avg(BaseModel):
    time: int
    value: float

@app.on_event("startup")
async def startup_event():
    await watcher.start()
    print("协程已启动")

@app.on_event("shutdown")
async def shutdown_event():
    await watcher.stop()
    print("协程已关闭")

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/candles/")
def get_candles():
    candles = watcher.state['candles']
    candles = [Candle(
        time=candles[t][0],
        open=candles[t][3],
        high=candles[t][2],
        low=candles[t][1],
        close=candles[t][4],
    ) for t in sorted(candles)]
    return candles

@app.get("/api/avgs/")
def get_avgs():
    avgs = watcher.state['avgs']
    avgs = [Avg(
        time=avg[0],
        value=avg[1]
    ) for avg in sorted(avgs, key=lambda avg: avg[0])]
    return avgs

async def send_datas(websocket, candles, avgs):
    # candles = watcher.state['candles']
    candles = [Candle(
        time=candle[0],
        open=candle[3],
        high=candle[2],
        low=candle[1],
        close=candle[4],
    ).json() for candle in sorted(candles)]

    await websocket.send_json({
        'type': 'candles',
        'data': candles
    })

    # avgs = watcher.state['avgs']
    avgs = [Avg(
        time=avg[0],
        value=avg[1]
    ).json() for avg in sorted(avgs, key=lambda avg: avg[0])]

    await websocket.send_json({
        'type': 'avgs',
        'data': avgs
    })

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_text()
    candles = watcher.get_candles()
    avgs = watcher.get_avgs()
    queue = await watcher.subscribe()
    try:
        await send_datas(websocket, candles, avgs)
        if data == 'subscribe':
            while True:
                candles, avgs = await watcher.next(queue)
                await send_datas(websocket, candles, avgs)
    except Exception as err:
        print(err)
        pass
    finally:
        await watcher.unsubscribe(queue)
