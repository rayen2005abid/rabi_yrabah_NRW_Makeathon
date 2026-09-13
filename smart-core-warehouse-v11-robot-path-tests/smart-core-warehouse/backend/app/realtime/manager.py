from __future__ import annotations
import asyncio
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active:list[WebSocket]=[]
        self.loop:asyncio.AbstractEventLoop|None=None
    async def connect(self, ws:WebSocket):
        await ws.accept(); self.active.append(ws); self.loop=asyncio.get_running_loop()
        await ws.send_json({'type':'CONNECTED','payload':{'channel':'warehouse'}})
    def disconnect(self, ws:WebSocket):
        if ws in self.active: self.active.remove(ws)
    async def broadcast(self, event:dict):
        stale=[]
        for ws in list(self.active):
            try: await ws.send_json(event)
            except Exception: stale.append(ws)
        for ws in stale: self.disconnect(ws)
    def publish_sync(self,event:dict):
        loop=self.loop
        if loop and loop.is_running() and self.active:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self.broadcast(event)))
manager=ConnectionManager()
