"""App-lifespan connection pooling, isolated by event loop and closed on shutdown."""
import asyncio
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary
import httpx

_clients=WeakKeyDictionary()

@asynccontextmanager
async def provider_lifespan():
    loop=asyncio.get_running_loop()
    if loop in _clients:
        yield
        return
    async with httpx.AsyncClient(timeout=90,limits=httpx.Limits(max_connections=8,max_keepalive_connections=4,keepalive_expiry=60)) as client:
        _clients[loop]=client
        try:yield
        finally:
            if _clients.get(loop) is client:_clients.pop(loop,None)

@asynccontextmanager
async def provider_client(timeout=90):
    client=_clients.get(asyncio.get_running_loop())
    if client is not None and not client.is_closed:
        yield client
    else:
        # Scripts/tests without an ASGI lifespan own and close their connection.
        async with httpx.AsyncClient(timeout=timeout) as standalone:yield standalone
