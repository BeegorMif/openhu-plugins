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

    api.config["ppm"]                                  # the plugin's config store in OpenHU (openhu#152), at once:
    api.config.get("stations", [])                     # manifest defaults + config.json, no connection needed
    await api.config.set("frequency", 101.3)           # through OpenHU (checks declared settings); offline: sent later
    await api.config.update({"band": "fm"})            # several keys, all or none
    await api.config.remove("oldKey")                  # free key deleted, a setting back to its default
    api.on_config(lambda values, changed: ...)         # changed in Settings → Apps or by another client

    config = load_config(DEFAULTS)                     # older style, still fine: a dict of the store's values,
    save_config(config)                                # sends what changed since the last save

Environment (set by OpenHU): OPENHU_API_URL, OPENHU_PLUGIN_ID, OPENHU_PLUGIN_DIR, OPENHU_DATA_DIR, OPENHU_LANGUAGE,
OPENHU_PLUGIN_TOKEN (the process logs in with it, so its values count as the plugin's: only plugins that declare
"androidAuto" in their manifest feed Android Auto, openhu#123).
OPENHU_API_TOKEN (optional, not set by OpenHU): API token, only needed from another computer, e.g. while developing
a plugin against a head unit (OPENHU_API_URL=ws://<head unit>:5520). On the head unit itself no token is needed.
"""

import asyncio
import copy
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


_MISSING = object()
# the OpenHU of the process: load_config/save_config go through its config store
_instance = None
# what load_config/save_config saw last, per data dir: save_config sends only what changed since then
_saved = {}


def read_json(path):
    try:
        with open(path) as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as file:
        json.dump(data, file, indent=2)
    os.replace(path + ".tmp", path)


def setting_defaults(plugin_dir=None):
    """key -> default of the settings declared in manifest.json (without sections)."""
    manifest = read_json(os.path.join(plugin_dir or PLUGIN_DIR, "manifest.json"))
    settings = manifest.get("settings") if isinstance(manifest.get("settings"), list) else []
    return {entry["key"]: entry["default"] for entry in settings
            if isinstance(entry, dict) and entry.get("type") != "section" and "key" in entry and "default" in entry}


def _store_for(data_dir):
    if _instance is not None and os.path.abspath(data_dir or DATA_DIR) == os.path.abspath(_instance.config.data_dir):
        return _instance.config
    return None


def load_config(defaults, data_dir=None):
    """defaults merged with the config store (the manifest's setting defaults and config.json, or the values OpenHU
    published). A plain dict: change it and call save_config(), or use api.config."""
    data_dir = data_dir or DATA_DIR
    store = _store_for(data_dir)
    config = copy.deepcopy(dict(defaults))
    if store is not None:
        config.update(copy.deepcopy(store.as_dict()))
    else:
        config.update(setting_defaults())
        config.update(read_json(os.path.join(data_dir, "config.json")))
    _saved[os.path.abspath(data_dir)] = copy.deepcopy(config)
    return config


def save_config(config, data_dir=None):
    """Stores what changed since the last load_config/save_config: through OpenHU's config store when this process
    has an OpenHU (sent once it is connected), otherwise into config.json."""
    data_dir = data_dir or DATA_DIR
    key = os.path.abspath(data_dir)
    saved = _saved.get(key, {})
    changes = {name: copy.deepcopy(value) for name, value in config.items() if saved.get(name, _MISSING) != value}
    removed = [name for name in saved if name not in config]
    _saved[key] = copy.deepcopy(dict(config))
    store = _store_for(data_dir)
    if store is not None:
        store.queue(changes, removed)
        return
    write_json(os.path.join(data_dir, "config.json"), config)


def follow_config(api, config, on_change=None, data_dir=None):
    """Keeps a dict from load_config() current: values changed from outside (Settings → Apps, another client) are
    written into it, then on_change(changed keys) is called (sync or async). Call before api.run()."""
    key = os.path.abspath(data_dir or DATA_DIR)

    async def changed(values, keys):
        saved = _saved.setdefault(key, {})
        for name in keys:
            if name in values:
                config[name] = copy.deepcopy(values[name])
                saved[name] = copy.deepcopy(values[name])
            else:
                config.pop(name, None)
                saved.pop(name, None)
        if on_change is not None:
            result = on_change(keys)
            if inspect.isawaitable(result):
                await result
    api.on_config(changed)


class Config:
    """The plugin's config store in OpenHU (openhu#152, openhu/docs/plugins.md#config-store): one JSON object, declared
    keys are the settings of manifest.json (shown in Settings → Apps, checked by OpenHU), all other keys are free.

    Readable at once (the manifest's defaults and config.json, no connection needed) and kept current from the topic
    plugin.config.<id>. Changes go through OpenHU; made while not connected, they apply locally and are sent once the
    connection is there. Against an OpenHU without the store, config.json is written directly."""

    def __init__(self, api, plugin_id=None, data_dir=None, plugin_dir=None):
        self._api = api
        self.plugin_id = plugin_id or PLUGIN_ID
        self.data_dir = data_dir or DATA_DIR
        self.plugin_dir = plugin_dir or PLUGIN_DIR
        self.defaults = setting_defaults(self.plugin_dir)
        self._values = dict(copy.deepcopy(self.defaults))
        self._values.update(read_json(os.path.join(self.data_dir, "config.json")))
        self._pending = {}  # key -> value, or _MISSING for a removed key
        self._callbacks = []
        self._supported = None  # False: OpenHU has no config store (plugin.config.* unknown)

    @property
    def topic(self):
        return "plugin.config." + self.plugin_id

    # --- reading ---

    def __getitem__(self, key):
        return self._values[key]

    def __contains__(self, key):
        return key in self._values

    def __iter__(self):
        return iter(dict(self._values))

    def __len__(self):
        return len(self._values)

    def get(self, key, default=None):
        return self._values.get(key, default)

    def keys(self):
        return list(self._values)

    def items(self):
        return list(self._values.items())

    def as_dict(self):
        return dict(self._values)

    def on_change(self, callback):
        """callback(values, changed) (sync or async) when values change from outside: Settings → Apps, another
        client, the file changed by hand. Not for the process's own changes."""
        self._callbacks.append(callback)

    # --- changing ---

    async def set(self, key, value):
        """Sets one key; returns the value as stored (a setting converted to its type). Raises OpenHUError for a value
        that a declared setting does not take."""
        return (await self.update({key: value}))[key]

    async def update(self, changes):
        """Sets several keys, all or none; returns them as stored."""
        changes = copy.deepcopy(dict(changes))
        if self._api.connected and self._supported is not False:
            try:
                result = await self._api.request("plugin.config.set", id=self.plugin_id, values=changes)
                self._values.update(result.get("values", {}))
                return result.get("values", {})
            except OpenHUError as error:
                if "unknown method" not in str(error):
                    raise
                self._supported = False
        self.queue(changes, [])
        return changes

    async def remove(self, *keys):
        """A free key is deleted, a declared setting goes back to its default."""
        if self._api.connected and self._supported is not False:
            try:
                result = await self._api.request("plugin.config.remove", id=self.plugin_id, keys=list(keys))
                self._values = result.get("values", self._values)
                return
            except OpenHUError as error:
                if "unknown method" not in str(error):
                    raise
                self._supported = False
        self.queue({}, list(keys))

    def queue(self, changes, removed):
        """Applies changes locally and sends them when possible (save_config, changes while not connected)."""
        for key, value in changes.items():
            self._values[key] = copy.deepcopy(value)
            self._pending[key] = copy.deepcopy(value)
        for key in removed:
            self._values.pop(key, None)
            if key in self.defaults:
                self._values[key] = copy.deepcopy(self.defaults[key])
            self._pending[key] = _MISSING
        if self._supported is False:
            self._write_file()
            return
        if self._api.connected:
            try:
                asyncio.get_running_loop().create_task(self.flush())
            except RuntimeError:
                pass  # no loop yet: sent at the connect

    async def flush(self):
        """Sends the queued changes (also called on every connect)."""
        if not self._pending or not self._api.connected:
            return
        pending, self._pending = self._pending, {}
        changes = {key: value for key, value in pending.items() if value is not _MISSING}
        removed = [key for key, value in pending.items() if value is _MISSING]
        try:
            if self._supported is not False:
                if changes:
                    await self._api.request("plugin.config.set", id=self.plugin_id, values=changes)
                if removed:
                    await self._api.request("plugin.config.remove", id=self.plugin_id, keys=removed)
                return
        except OpenHUError as error:
            if "unknown method" in str(error):
                self._supported = False
            elif "connection lost" in str(error) or "not connected" in str(error):
                # again at the next connect
                for key, value in pending.items():
                    self._pending.setdefault(key, value)
                return
            else:
                # refused (a setting the plugin set to a value OpenHU does not take): key by key, so the other keys
                # (e.g. the plugin's stations) are not lost with it; OpenHU keeps its value for the refused one
                for key, value in changes.items():
                    try:
                        await self._api.request("plugin.config.set", id=self.plugin_id, values={key: value})
                    except OpenHUError as refused:
                        log.warning("config: %s", refused)
                if removed:
                    await self._api.safe(self._api.request("plugin.config.remove", id=self.plugin_id, keys=removed))
                await self._sync()
                return
        self._write_file()

    async def _connected(self):
        await self.flush()
        await self._sync()

    async def _sync(self):
        """Takes OpenHU's values (the store may have changed while the process was not connected)."""
        if self._supported is False:
            return
        try:
            result = await self._api.request("plugin.config.get", id=self.plugin_id)
        except OpenHUError as error:
            if "unknown method" in str(error):
                self._supported = False
                self._write_file()
            return
        await self._take(result.get("values", {}))

    async def _on_topic(self, topic, data):
        # local changes still to be sent win until they are
        if not self._pending and isinstance(data.get("values"), dict):
            await self._take(data["values"])

    async def _take(self, values):
        changed = sorted(key for key in set(values) | set(self._values)
                         if values.get(key, _MISSING) != self._values.get(key, _MISSING))
        self._values = dict(values)
        if not changed:
            return
        for callback in list(self._callbacks):
            try:
                result = callback(dict(values), changed)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("config callback failed")

    def _write_file(self):
        # OpenHU without a config store: the file as before
        write_json(os.path.join(self.data_dir, "config.json"), self._values)


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
    def __init__(self, url=None, token=None, plugin_id=None, data_dir=None, plugin_dir=None):
        global _instance
        self.url = url or os.environ.get("OPENHU_API_URL", "ws://127.0.0.1:5520")
        self.token = token or os.environ.get("OPENHU_API_TOKEN")
        self.plugin_token = os.environ.get("OPENHU_PLUGIN_TOKEN")
        self._ws = None
        self._next_id = 0
        self._pending = {}
        self._handlers = []
        self.config = Config(self, plugin_id, data_dir, plugin_dir)
        self.on(self.config.topic, self.config._on_topic)
        if _instance is None:
            _instance = self

    def on_config(self, callback):
        """callback(values, changed) when the config store changes from outside (see Config.on_change)."""
        self.config.on_change(callback)

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
                    if self.plugin_token:
                        await ws.send(json.dumps({"type": "auth", "pluginToken": self.plugin_token}))
                    elif self.token:
                        await ws.send(json.dumps({"type": "auth", "token": self.token}))
                    topics = sorted({pattern for pattern, _ in self._handlers})
                    if topics:
                        await ws.send(json.dumps({"type": "subscribe", "topics": topics}))
                    asyncio.create_task(self._call(self.config._connected))
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
