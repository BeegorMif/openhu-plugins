"""common/openhu.py: the config store client (api.config, load_config/save_config, follow_config), openhu#152."""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

MANIFEST = {"id": "org.test.p", "settings": [
    {"type": "section", "key": "tuner"},
    {"key": "rds", "type": "switch", "default": True},
    {"key": "columns", "type": "number", "default": 4, "min": 3, "max": 6},
]}


class FakeOpenHU:
    """OpenHU's side of plugin.config.*: a store with the declared defaults, checks like OpenHU for "columns"."""

    def __init__(self, stored=None, supported=True):
        self.stored = dict(stored or {})
        self.supported = supported
        self.connected = True
        self.requests = []

    def values(self):
        values = {"rds": True, "columns": 4}
        values.update(self.stored)
        return values

    async def request(self, method, **params):
        import openhu
        self.requests.append((method, params))
        if not self.supported and method.startswith("plugin.config."):
            raise openhu.OpenHUError("%s: unknown method: %s" % (method, method))
        if method == "plugin.config.set":
            for key, value in params["values"].items():
                if key == "columns" and value not in (3, 4, 5, 6):
                    raise openhu.OpenHUError("plugin.config.set: columns: must be 3 to 6")
            self.stored.update(params["values"])
            return {"id": params["id"], "values": {key: self.values()[key] for key in params["values"]}}
        if method == "plugin.config.remove":
            for key in params["keys"]:
                self.stored.pop(key, None)
            return {"id": params["id"], "values": self.values()}
        if method == "plugin.config.get":
            return {"id": params["id"], "values": self.values()}
        raise AssertionError(method)

    async def safe(self, coroutine):
        try:
            return await coroutine
        except Exception:
            return None

    def on_config(self, callback):
        self.config.on_change(callback)


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class ConfigTest(unittest.TestCase):
    def setUp(self):
        import openhu
        self.openhu = openhu
        self.dir = tempfile.TemporaryDirectory()
        self.plugin_dir = os.path.join(self.dir.name, "plugin")
        self.data_dir = os.path.join(self.dir.name, "data")
        os.makedirs(self.plugin_dir)
        os.makedirs(self.data_dir)
        with open(os.path.join(self.plugin_dir, "manifest.json"), "w") as file:
            json.dump(MANIFEST, file)
        self.saved_instance = openhu._instance
        openhu._instance = None

    def tearDown(self):
        self.openhu._instance = self.saved_instance
        self.openhu._saved.clear()
        self.dir.cleanup()

    def write_file(self, data):
        with open(os.path.join(self.data_dir, "config.json"), "w") as file:
            json.dump(data, file)

    def read_file(self):
        with open(os.path.join(self.data_dir, "config.json")) as file:
            return json.load(file)

    def config(self, fake):
        config = self.openhu.Config(fake, "org.test.p", self.data_dir, self.plugin_dir)
        fake.config = config
        return config

    def test_reads_defaults_and_file_without_connection(self):
        self.write_file({"stations": [101.3], "columns": 5})
        fake = FakeOpenHU()
        fake.connected = False
        config = self.config(fake)
        self.assertEqual(config["rds"], True)
        self.assertEqual(config["columns"], 5)
        self.assertEqual(config.get("stations"), [101.3])
        self.assertNotIn("tuner", config)
        self.assertEqual(config.topic, "plugin.config.org.test.p")

    def test_changes_go_through_openhu(self):
        fake = FakeOpenHU()
        config = self.config(fake)
        self.assertEqual(asyncio.run(config.set("columns", 5)), 5)
        asyncio.run(config.update({"stations": [1, 2]}))
        self.assertEqual(fake.stored, {"columns": 5, "stations": [1, 2]})
        self.assertEqual(config["stations"], [1, 2])
        with self.assertRaises(self.openhu.OpenHUError):
            asyncio.run(config.set("columns", 9))
        asyncio.run(config.remove("columns"))
        self.assertEqual(config["columns"], 4)
        # the plugin never writes the file itself
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "config.json")))

    def test_offline_changes_are_sent_at_the_connect(self):
        fake = FakeOpenHU(stored={"columns": 6})
        fake.connected = False
        config = self.config(fake)
        asyncio.run(config.set("stations", [99.5]))
        self.assertEqual(config["stations"], [99.5])
        self.assertEqual(fake.requests, [])
        fake.connected = True
        asyncio.run(config._connected())
        self.assertEqual(fake.stored["stations"], [99.5])
        # and OpenHU's values afterwards (changed in the settings while the plugin was not connected)
        self.assertEqual(config["columns"], 6)

    def test_callbacks_for_changes_from_outside(self):
        fake = FakeOpenHU()
        config = self.config(fake)
        calls = []
        config.on_change(lambda values, changed: calls.append((values["columns"], changed)))
        asyncio.run(config._on_topic(config.topic, {"values": {"rds": True, "columns": 6}, "changed": ["columns"]}))
        self.assertEqual(calls, [(6, ["columns"])])
        # the echo of an own change: nothing changed
        asyncio.run(config.set("rds", False))
        asyncio.run(config._on_topic(config.topic, {"values": {"rds": False, "columns": 6}}))
        self.assertEqual(len(calls), 1)

    def test_openhu_without_store_writes_the_file(self):
        fake = FakeOpenHU(supported=False)
        config = self.config(fake)
        asyncio.run(config.set("stations", [1]))
        self.assertEqual(self.read_file()["stations"], [1])
        asyncio.run(config._connected())
        self.assertEqual(self.read_file()["rds"], True)

    def test_load_and_save_config_through_the_store(self):
        self.write_file({"stations": [101.3]})
        fake = FakeOpenHU(stored={"stations": [101.3]})
        api = self.openhu.OpenHU(plugin_id="org.test.p", data_dir=self.data_dir, plugin_dir=self.plugin_dir)
        api.request = fake.request
        api._ws = object()  # connected
        defaults = {"stations": [], "presets": {"fm": []}, "rds": True}
        config = self.openhu.load_config(defaults, self.data_dir)
        self.assertEqual(config["stations"], [101.3])
        self.assertEqual(config["columns"], 4)

        async def change():
            config["presets"]["fm"].append(87.6)
            config["columns"] = 5
            del config["stations"]
            self.openhu.save_config(config, self.data_dir)
            await asyncio.sleep(0.05)
        asyncio.run(change())
        # only what changed: not rds (unchanged default), the nested list change, the removed key
        sets = [params["values"] for method, params in fake.requests if method == "plugin.config.set"]
        self.assertEqual(sets, [{"presets": {"fm": [87.6]}, "columns": 5}])
        removes = [params["keys"] for method, params in fake.requests if method == "plugin.config.remove"]
        self.assertEqual(removes, [["stations"]])

    def test_refused_setting_does_not_lose_other_keys(self):
        fake = FakeOpenHU()
        api = self.openhu.OpenHU(plugin_id="org.test.p", data_dir=self.data_dir, plugin_dir=self.plugin_dir)
        api.request = fake.request
        api._ws = object()
        api.safe = fake.safe
        config = self.openhu.load_config({}, self.data_dir)

        async def change():
            config["columns"] = 9
            config["stations"] = [1]
            self.openhu.save_config(config, self.data_dir)
            await asyncio.sleep(0.05)
        asyncio.run(change())
        self.assertEqual(fake.stored, {"stations": [1]})
        # OpenHU's value again
        self.assertEqual(api.config["columns"], 4)

    def test_save_config_without_openhu_writes_the_file(self):
        config = self.openhu.load_config({"a": 1}, self.data_dir)
        config["a"] = 2
        self.openhu.save_config(config, self.data_dir)
        self.assertEqual(self.read_file(), {"a": 2})

    def test_follow_config(self):
        fake = FakeOpenHU()
        api = self.openhu.OpenHU(plugin_id="org.test.p", data_dir=self.data_dir, plugin_dir=self.plugin_dir)
        api.request = fake.request
        api._ws = object()
        config = self.openhu.load_config({"rds": True}, self.data_dir)
        seen = []
        self.openhu.follow_config(api, config, seen.append, self.data_dir)
        asyncio.run(api.config._on_topic(api.config.topic, {"values": {"rds": False, "columns": 4}}))
        self.assertEqual((config["rds"], seen), (False, [["rds"]]))

        # a later save does not send the followed value back
        async def save():
            self.openhu.save_config(config, self.data_dir)
            await asyncio.sleep(0.05)
        asyncio.run(save())
        self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
