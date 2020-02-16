from typing import List

from fastapi import FastAPI, Query, Cookie, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND

import random
import asyncio

import ymyt

app = FastAPI()

class Candle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float

class Avg(BaseModel):
    time: str
    value: float

YMYT_TASK = None

@app.get("/start/")
async def start():
    global YMYT_TASK
    YMYT_TASK = asyncio.create_task(ymyt.main())
    return "协程已启动"

@app.get("/stop/")
async def start():
    global YMYT_TASK
    YMYT_TASK.cancel()
    return "已发送取消请求"

@app.get("/api/candles/")
def get_candles():
    return ymyt.STATE['candles']

@app.get("/api/avgs/")
def get_avgs():
    return []

@app.post("/api/datafeed/")
def feed_data():
    return []