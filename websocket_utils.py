import asyncio
import json
from typing import Set
from fastapi import WebSocket

active_websockets: Set[WebSocket] = set()
main_loop = None

async def broadcast_location(data):
    if not active_websockets:
        return
    msg = json.dumps(data)
    await asyncio.gather(*(ws.send_text(msg) for ws in active_websockets))

def broadcast_location_sync(data):
    try:
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_location(data), main_loop)
        else:
            print("⚠️ Main event loop not running")
    except Exception as e:
        print(f"Broadcast error: {e}")
