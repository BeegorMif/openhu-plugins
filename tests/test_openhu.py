"""common/openhu.py: texts of the plugin processes (Texts, i18n/<language>.ts)."""

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="%s">
<context>
    <name></name>
%s</context>
</TS>
"""


def message(text_id, text, kind=None):
    attribute = ' type="%s"' % kind if kind else ""
    return ('    <message id="%s">\n        <source></source>\n        <translation%s>%s</translation>\n'
            '    </message>\n' % (text_id, attribute, text))


class Api:
    def __init__(self):
        self.handlers = {}

    def on(self, pattern, callback):
        self.handlers[pattern] = callback


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class TextsTest(unittest.TestCase):
    def setUp(self):
        import openhu
        self.openhu = openhu
        self.dir = tempfile.TemporaryDirectory()
        self.write("en", message("x.main.hello", "Hello %1, %2 &amp; %1") + message("x.main.only_en", "Only")
                   + message("x.main.todo", "", "unfinished") + message("x.main.old", "Old", "vanished"))
        self.write("de", message("x.main.hello", "Hallo %1, %2 &amp; %1"))

    def tearDown(self):
        self.dir.cleanup()

    def write(self, language, messages):
        with open(os.path.join(self.dir.name, language + ".ts"), "w", encoding="utf-8") as file:
            file.write(TS % (language, messages))

    def test_translate(self):
        texts = self.openhu.Texts(self.dir.name, "en")
        self.assertEqual(texts.tr("x.main.hello", "A", 2), "Hello A, 2 & A")
        # like qsTrId: an ID without a translation shows as the ID, also untranslated and removed ones
        self.assertEqual(texts.tr("x.main.missing"), "x.main.missing")
        self.assertEqual(texts.tr("x.main.todo"), "x.main.todo")
        self.assertEqual(texts.tr("x.main.old"), "x.main.old")
        # missing arguments stay visible
        self.assertEqual(texts.tr("x.main.hello", "A"), "Hello A, %2 & A")

    def test_language(self):
        texts = self.openhu.Texts(self.dir.name, "de")
        self.assertEqual(texts.tr("x.main.hello", "A", "B"), "Hallo A, B & A")
        self.assertEqual(texts.tr("x.main.only_en"), "x.main.only_en")
        # no file for the language: English
        self.assertTrue(texts.set_language("fr"))
        self.assertEqual(texts.tr("x.main.only_en"), "Only")

    def test_environment(self):
        os.environ["OPENHU_LANGUAGE"] = "de"
        try:
            self.assertEqual(self.openhu.Texts(self.dir.name).language, "de")
        finally:
            del os.environ["OPENHU_LANGUAGE"]
        self.assertEqual(self.openhu.Texts(self.dir.name).language, "en")

    def test_text_follows_switch(self):
        texts = self.openhu.Texts(self.dir.name, "en")
        text = texts.text("x.main.hello", "A", "B")
        self.assertEqual(str(text), "Hello A, B & A")
        self.assertEqual("%s" % text, "Hello A, B & A")
        texts.set_language("de")
        self.assertEqual(str(text), "Hallo A, B & A")

    def test_follow(self):
        texts = self.openhu.Texts(self.dir.name, "en")
        api, changes = Api(), []

        async def on_change():
            changes.append(texts.language)

        texts.follow(api, on_change)
        handler = api.handlers["ui.language"]
        asyncio.run(handler("ui.language", {"language": "de", "available": ["en", "de"]}))
        asyncio.run(handler("ui.language", {"language": "de"}))  # unchanged: no new publish
        self.assertEqual(changes, ["de"])
        self.assertEqual(texts.tr("x.main.hello", 1, 2), "Hallo 1, 2 & 1")



@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class LoginTest(unittest.TestCase):
    """The first message: the plugin token if OpenHU started the process (openhu#123), else the API token."""

    def first_message(self, environment):
        import json
        import openhu
        import websockets
        received = []

        async def main():
            async def handler(ws, *args):
                received.append(json.loads(await ws.recv()))

            async with websockets.serve(handler, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                old = {key: os.environ.get(key) for key in environment}
                os.environ.update({key: value for key, value in environment.items() if value is not None})
                try:
                    api = openhu.OpenHU("ws://127.0.0.1:%d" % port)
                finally:
                    for key, value in old.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
                task = asyncio.create_task(api.run())
                for _ in range(100):
                    if received:
                        break
                    await asyncio.sleep(0.02)
                task.cancel()

        asyncio.run(main())
        return received[0] if received else None

    def test_plugin_token(self):
        self.assertEqual(self.first_message({"OPENHU_PLUGIN_TOKEN": "p", "OPENHU_API_TOKEN": "t"}),
                         {"type": "auth", "pluginToken": "p"})

    def test_api_token(self):
        self.assertEqual(self.first_message({"OPENHU_PLUGIN_TOKEN": None, "OPENHU_API_TOKEN": "t"}),
                         {"type": "auth", "token": "t"})

if __name__ == "__main__":
    unittest.main()
