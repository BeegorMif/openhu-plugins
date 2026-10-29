"""Manifest, translation and topic contract tests for the digital instrument cluster."""

import json
import os
import unittest
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "org.beegor.cluster")


class ClusterPluginTest(unittest.TestCase):
    def test_manifest_registers_a_page_and_requires_can(self):
        with open(os.path.join(PLUGIN, "manifest.json"), encoding="utf-8") as file:
            manifest = json.load(file)
        self.assertEqual(manifest["id"], "org.beegor.cluster")
        self.assertEqual(manifest["version"], "1.0.1")
        self.assertEqual(manifest["ui"]["page"], "qml/Main.qml")
        self.assertIn("org.beegor.can", manifest["requires"])
        required_version = tuple(
            int(part)
            for part in manifest["requires"]["org.beegor.can"].split(".")
        )
        self.assertGreaterEqual(required_version, (1, 0, 0))
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, manifest["ui"]["page"])))
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, manifest["ui"]["icon"])))

    def test_translations_have_same_complete_ids(self):
        messages = {}
        for language in ("en", "de"):
            path = os.path.join(PLUGIN, "i18n", language + ".ts")
            root = ET.parse(path).getroot()
            self.assertEqual(root.get("language"), language)
            translations = {}
            for message in root.iter("message"):
                translation = message.find("translation")
                translations[message.get("id")] = translation.text if translation is not None else None
            self.assertTrue(all(translations.values()), "%s has empty translations" % language)
            messages[language] = translations
        self.assertEqual(set(messages["en"]), set(messages["de"]))
        self.assertIn("org.beegor.cluster.name", messages["en"])
        self.assertIn("org.beegor.cluster.description", messages["en"])

    def test_page_subscribes_to_live_and_raw_topics(self):
        with open(
            os.path.join(PLUGIN, "qml", "Main.qml"),
            encoding="utf-8",
        ) as file:
            qml = file.read()

        # Live topic subscriptions and cached event data.
        for topic in (
            '"vehicle."',
            '"can."',
            '"can.state"',
            '"can.monitor"',
            '"cluster.state"',
            '"cluster.data"',
        ):
            self.assertIn(topic, qml)
        self.assertIn("eventBus.last(topic)", qml)
        self.assertIn("function onEvent(topic, data)", qml)
        self.assertIn("available !== false", qml)

        # The dashboard is data-driven: fields and source topics come
        # from the configured display items, not hardcoded QML topic names.
        self.assertIn("page.enabledDisplayItems", qml)
        self.assertIn("item.topic", qml)
        self.assertIn("item.field", qml)
        self.assertIn("function configuredValue(item)", qml)
        # Raw CAN monitoring is supported.
        self.assertIn('"can.monitor"', qml)
        self.assertIn("page.monitor", qml)


if __name__ == "__main__":
    unittest.main()
