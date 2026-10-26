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
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["ui"]["page"], "qml/Main.qml")
        self.assertEqual(manifest["requires"], {"org.beegor.can": "1.0.0"})
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
        with open(os.path.join(PLUGIN, "qml", "Main.qml"), encoding="utf-8") as file:
            qml = file.read()
        for topic in ('"vehicle."', '"can."', '"can.state"', '"can.monitor"',
                      '"speed"', '"engine"', '"climate"', '"fuel"', '"odometer"',
                      '"ignition"', '"lights"'):
            self.assertIn(topic, qml)
        self.assertIn("eventBus.last(topic)", qml)
        self.assertIn("available !== false", qml)


if __name__ == "__main__":
    unittest.main()
