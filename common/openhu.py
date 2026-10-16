"""Small client for the OpenHU API, used by the plugin processes.

    api = OpenHU()
    api.on("vehicle.*", lambda topic, data: ...)       # events (sync or async callbacks)
    await api.request("volume.set", value=40)          # methods, raises OpenHUError
    await api.publish("vehicle.speed", kmh=50)         # state other plugins/the shell can read
    await api.emit("radio.command", cmd="tune")        # one-shot event
    await api.action("media.next")                     # same as a steering wheel button
    await api.run(on_connect)                          # connects and reconnects forever

    texts = Texts()                                     # texts of the process in the shell's language
    texts.follow(api, on_change)                       # ...also after a switch
    texts.tr("org.example.speed.error.no_sensor")      # i18n/<language>.ts, like qsTrId() in QML

Environment (set by OpenHU): OPENHU_API_URL, OPENHU_PLUGIN_ID, OPENHU_PLUGIN_DIR, OPENHU_DATA_DIR, OPENHU_LANGUAGE.
OPENHU_API_TOKEN (optional, not set by OpenHU): API token, only needed from another computer, e.g. while developing
a plugin against a head unit (OPENHU_API_URL=ws://<head unit>:5520). On the head unit itself no token is needed.
"""

import asyncio
import inspect
import json
import logging
import os
import re
import xml.etree.ElementTree as ElementTree

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


def load_ts(path):
    """Text ID -> translation of a Qt .ts file (lrelease -idbased); untranslated and removed entries are left out."""
    texts = {}
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return texts
    for message in root.iter("message"):
        translation = message.find("translation")
        if message.get("id") and translation is not None and translation.text \
                and translation.get("type") not in ("unfinished", "vanished", "obsolete"):
            texts[message.get("id")] = translation.text
    return texts


class Text:
    """A text ID with its arguments, translated each time it is shown (str()). Keep messages as Text (e.g. an error
    in the published state), so they follow a language switch when they are published again."""

    def __init__(self, texts, text_id, *args):
        self.texts, self.id, self.args = texts, text_id, args

    def __str__(self):
        return self.texts.tr(self.id, *self.args)

    def __repr__(self):
        return "Text(%r)" % str(self)


class Texts:
    """Texts of a plugin process in the language of the shell. They live in the same files as the texts of the
    plugin's QML, i18n/<language>.ts (IDs "<plugin id>.<area>.<key>", openhu/docs/translations.md), arguments are
    %1, %2, ... like qsTrId(...).arg(...). An ID without a translation comes back as the ID, like in QML; a language
    without a file falls back to English."""

    def __init__(self, directory=None, language=None):
        self.directory = directory or os.path.join(PLUGIN_DIR, "i18n")
        self.language = None
        self.texts = {}
        self.set_language(language or os.environ.get("OPENHU_LANGUAGE") or "en")

    def set_language(self, language):
        """Loads the texts of a language; True if it changed."""
        if language == self.language:
            return False
        self.language = language
        path = os.path.join(self.directory, language + ".ts")
        self.texts = load_ts(path if os.path.isfile(path) else os.path.join(self.directory, "en.ts"))
        return True

    def tr(self, text_id, *args):
        text = self.texts.get(text_id, text_id)
        return re.sub(r"%(\d+)", lambda m: str(args[int(m.group(1)) - 1]) if 0 < int(m.group(1)) <= len(args)
                      else m.group(0), text)

    def text(self, text_id, *args):
        """A Text: translated when it is shown, in the language of that moment."""
        return Text(self, text_id, *args)

    def follow(self, api, on_change=None):
        """Follows a language switch of the shell (topic ui.language), then calls on_change() (sync or async), e.g.
        to publish the state again with the new texts. Call before api.run()."""
        async def on_language(topic, data):
            if self.set_language(data.get("language") or "en") and on_change is not None:
                result = on_change()
                if inspect.isawaitable(result):
                    await result
        api.on("ui.language", on_language)


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
