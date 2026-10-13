"""Small client for the OpenHU API, used by the plugin processes.

    api = OpenHU()
    api.on("vehicle.*", lambda topic, data: ...)       # events (sync or async callbacks)
    await api.request("volume.set", value=40)          # methods, raises OpenHUError
    await api.publish("vehicle.speed", kmh=50)         # state other plugins/the shell can read
    await api.emit("radio.command", cmd="tune")        # one-shot event
    await api.action("media.next")                     # same as a steering wheel button
    await api.run(on_connect)                          # connects and reconnects forever

Environment (set by OpenHU): OPENHU_API_URL, OPENHU_PLUGIN_ID, OPENHU_PLUGIN_DIR, OPENHU_DATA_DIR.
OPENHU_API_TOKEN (optional, not set by OpenHU): API token, only needed from another computer, e.g. while developing
a plugin against a head unit (OPENHU_API_URL=ws://<head unit>:5520). On the head unit itself no token is needed.
"""

import asyncio
import inspect
import json
import logging
import os

import websockets

log = logging.getLogger("openhu")

PLUGIN_ID = os.environ.get("OPENHU_PLUGIN_ID", "plugin")
PLUGIN_DIR = os.environ.get("OPENHU_PLUGIN_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("OPENHU_DATA_DIR", os.path.join(os.path.expanduser("~/.openhu/plugin-data"), PLUGIN_ID))


class OpenHUError(Exception):
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


class OpenHU:
    def __init__(self, url=None, token=None):
        self.url = url or os.environ.get("OPENHU_API_URL", "ws://127.0.0.1:5520")
        self.token = token or os.environ.get("OPENHU_API_TOKEN")
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
            raise OpenHUError("not connected")
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
            raise OpenHUError("%s: %s" % (method, response["error"]))
        return response.get("result")

    async def publish(self, topic, **data):
        return await self.request("bus.publish", topic=topic, data=data)

    async def emit(self, topic, **data):
        return await self.request("bus.emit", topic=topic, data=data)

    async def action(self, name, phase="click"):
        return await self.request("input.action", action=name, phase=phase)

    async def safe(self, coroutine):
        """Await a request, log instead of raising (e.g. while OpenHU restarts)."""
        try:
            return await coroutine
        except (OpenHUError, OSError, asyncio.TimeoutError, websockets.WebSocketException) as error:
            log.warning("%s", error)
            return None

    async def run(self, on_connect=None):
        while True:
            try:
                async with websockets.connect(self.url, max_size=None) as ws:
                    self._ws = ws
                    log.info("connected to %s", self.url)
                    # answered with {"type":"auth"}; messages are handled in order, so no need to wait for it
                    if self.token:
                        await ws.send(json.dumps({"type": "auth", "token": self.token}))
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
                        future.set_exception(OpenHUError("connection lost"))
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
        elif kind == "error":
            log.warning("API: %s", message.get("error"))

    @staticmethod
    async def _call(callback, *args):
        try:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("handler failed")
