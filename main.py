from typing import List

from fastapi import FastAPI, Query, Cookie, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import random
import asyncio

from ymyt import Watcher

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="media"), name="media")
templates = Jinja2Templates(directory="templates")
watcher = Watcher()

class Candle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float

class Avg(BaseModel):
    time: str
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
    return watcher.state['candles']

@app.get("/api/avgs/")
def get_avgs():
    return []

@app.post("/api/datafeed/")
def feed_data():
    return []