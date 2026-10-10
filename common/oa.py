"""Small client for the OpenAuto API, used by the plugin processes.

    oa = OpenAuto()
    oa.on("vehicle.*", lambda topic, data: ...)       # events (sync or async callbacks)
    await oa.request("volume.set", value=40)          # methods, raises OpenAutoError
    await oa.publish("vehicle.speed", kmh=50)         # state other plugins/the shell can read
    await oa.emit("radio.command", cmd="tune")        # one-shot event
    await oa.action("media.next")                     # same as a steering wheel button
    await oa.run(on_connect)                          # connects and reconnects forever

Environment (set by OpenAuto): OA_API_URL, OA_PLUGIN_ID, OA_PLUGIN_DIR, OA_DATA_DIR.
"""

import asyncio
import inspect
import json
import logging
import os

import websockets

log = logging.getLogger("oa")

PLUGIN_ID = os.environ.get("OA_PLUGIN_ID", "plugin")
PLUGIN_DIR = os.environ.get("OA_PLUGIN_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("OA_DATA_DIR", os.path.join(os.path.expanduser("~/.openauto/plugin-data"), PLUGIN_ID))


class OpenAutoError(Exception):
    pass


def matches(pattern, topic):
    """Same rules as the shell: "*", "nav.*" or an exact topic."""
    return pattern == "*" or pattern == topic or (pattern.endswith(".*") and topic.startswith(pattern[:-1]))


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def load_config(defaults):
    """defaults merged with DATA_DIR/config.json"""
    config = dict(defaults)
    try:
        with open(os.path.join(DATA_DIR, "config.json")) as file:
            config.update(json.load(file))
    except (OSError, ValueError):
        pass
    return config


def save_config(config):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "config.json")
    with open(path + ".tmp", "w") as file:
        json.dump(config, file, indent=2)
    os.replace(path + ".tmp", path)


class OpenAuto:
    def __init__(self, url=None):
        self.url = url or os.environ.get("OA_API_URL", "ws://127.0.0.1:5520")
        self._ws = None
        self._next_id = 0
        self._pending = {}
        self._handlers = []

    @property
    def connected(self):
        return self._ws is not None

    def on(self, pattern, callback):
        self._handlers.append((pattern, callback))

    async def request(self, method, **params):
        if self._ws is None:
            raise OpenAutoError("not connected")
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._ws.send(json.dumps({"type": "request", "id": request_id, "method": method, "params": params}))
            response = await asyncio.wait_for(future, 10)
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            raise OpenAutoError("%s: %s" % (method, response["error"]))
        return response.get("result")

    async def publish(self, topic, **data):
        return await self.request("bus.publish", topic=topic, data=data)

    async def emit(self, topic, **data):
        return await self.request("bus.emit", topic=topic, data=data)

    async def action(self, name, phase="click"):
        return await self.request("input.action", action=name, phase=phase)

    async def safe(self, coroutine):
        """Await a request, log instead of raising (e.g. while OpenAuto restarts)."""
        try:
            return await coroutine
        except (OpenAutoError, OSError, asyncio.TimeoutError, websockets.WebSocketException) as error:
            log.warning("%s", error)
            return None

    async def run(self, on_connect=None):
        while True:
            try:
                async with websockets.connect(self.url, max_size=None) as ws:
                    self._ws = ws
                    log.info("connected to %s", self.url)
                    topics = sorted({pattern for pattern, _ in self._handlers})
                    if topics:
                        await ws.send(json.dumps({"type": "subscribe", "topics": topics}))
                    if on_connect is not None:
                        asyncio.create_task(self._call(on_connect))
                    async for message in ws:
                        self._dispatch(json.loads(message))
            except (OSError, websockets.WebSocketException) as error:
                log.info("API not reachable (%s), retrying", error)
            finally:
                self._ws = None
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(OpenAutoError("connection lost"))
                self._pending.clear()
            await asyncio.sleep(2)

    def _dispatch(self, message):
        kind = message.get("type")
        if kind == "response":
            future = self._pending.get(message.get("id"))
            if future is not None and not future.done():
                future.set_result(message)
        elif kind == "event":
            topic, data = message.get("topic", ""), message.get("data") or {}
            for pattern, callback in self._handlers:
                if matches(pattern, topic):
                    asyncio.create_task(self._call(callback, topic, data))

    @staticmethod
    async def _call(callback, *args):
        try:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("handler failed")
