"""Every plugin is translated (tools/openhu-translations --check): every text ID of its QML and process is in
i18n/en.ts and i18n/de.ts and translated in both, the QML has no texts without an ID, the manifest's name and
description are the English texts and the .qm files match the .ts files (when lrelease is installed)."""

import os
import subprocess
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class TranslationsTest(unittest.TestCase):
    def test_complete(self):
        result = subprocess.run([sys.executable, os.path.join(REPO, "tools", "openhu-translations"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
