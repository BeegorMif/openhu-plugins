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


if __name__ == "__main__":
    unittest.main()
