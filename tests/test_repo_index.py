"""tools/openhu-repo-index: one archive for "all", one per architecture for plugins with native programs."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "openhu-repo-index")


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as file:
        file.write(text)
    os.chmod(path, mode)


class RepoIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = self.temp.name
        write(os.path.join(self.repo, "repo.json"), json.dumps({"name": "Test"}))
        write(os.path.join(self.repo, "common", "openhu.py"), "# shared\n")
        plain = os.path.join(self.repo, "plugins", "org.example.plain")
        write(os.path.join(plain, "manifest.json"), json.dumps(
            {"id": "org.example.plain", "name": "Plain", "version": "1.0.0", "api": 2, "arch": ["all"]}))
        write(os.path.join(plain, "bin", "plain.py"), "print()\n", 0o755)
        native = os.path.join(self.repo, "plugins", "org.example.native")
        write(os.path.join(native, "manifest.json"), json.dumps(
            {"id": "org.example.native", "name": "Native", "version": "1.2.0", "api": 2, "arch": ["amd64", "arm64"],
             "shared": ["openhu.py"], "packages": ["librtlsdr0"], "androidAuto": {"services": ["radio"]},
             "requires": {"org.example.plain": "1.0.0"}, "recommends": ["org.example.other"]}))
        write(os.path.join(native, "bin", "main.py"), "print()\n", 0o755)
        write(os.path.join(native, "native", "build.sh"), "#!/bin/sh\n", 0o755)
        write(os.path.join(native, "tests", "test_x.py"), "\n")
        for arch in ("amd64", "arm64"):
            write(os.path.join(native, "bin", arch, "tool"), "#!/bin/sh\necho %s\n" % arch, 0o755)
            write(os.path.join(native, "bin", arch, "build-info.json"), json.dumps({"sources": ["tool-1.tar.gz"]}))
        write(os.path.join(self.repo, "dist", "sources", "tool-1.tar.gz"), "source")
        write(os.path.join(self.repo, "dist", "sources", "tool-0.tar.gz"), "old source")

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL] + list(args) + [self.repo], capture_output=True, text=True)

    def members(self, archive):
        with tarfile.open(os.path.join(self.repo, archive)) as tar:
            return {member.name: member for member in tar.getmembers()}

    def test_archives_per_architecture(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.repo, "index.json")) as file:
            index = {entry["id"]: entry for entry in json.load(file)["plugins"]}

        plain = index["org.example.plain"]
        self.assertEqual(plain["archive"], "dist/org.example.plain-1.0.0.tar.gz")
        self.assertNotIn("archives", plain)

        native = index["org.example.native"]
        self.assertNotIn("archive", native)
        self.assertEqual(native["arch"], ["amd64", "arm64"])
        self.assertEqual(native["packages"], ["librtlsdr0"])
        self.assertEqual(native["androidAuto"], {"services": ["radio"]})
        self.assertNotIn("androidAuto", plain)
        self.assertEqual(native["requires"], {"org.example.plain": "1.0.0"})
        self.assertEqual(native["recommends"], ["org.example.other"])
        self.assertNotIn("requires", plain)
        self.assertEqual(sorted(native["archives"]), ["amd64", "arm64"])
        for arch, other in (("amd64", "arm64"), ("arm64", "amd64")):
            entry = native["archives"][arch]
            self.assertEqual(entry["archive"], "dist/org.example.native-1.2.0-%s.tar.gz" % arch)
            with open(os.path.join(self.repo, entry["archive"]), "rb") as file:
                data = file.read()
            self.assertEqual((entry["sha256"], entry["size"]), (hashlib.sha256(data).hexdigest(), len(data)))
            members = self.members(entry["archive"])
            self.assertIn("org.example.native/bin/%s/tool" % arch, members)
            self.assertEqual(members["org.example.native/bin/%s/tool" % arch].mode, 0o755)
            self.assertFalse([name for name in members if "/bin/%s/" % other in name])
            self.assertIn("org.example.native/lib/openhu.py", members)
            self.assertIn("org.example.native/native/build.sh", members)
            self.assertFalse([name for name in members if "/tests/" in name])
        # source archives of the binaries stay, others go
        self.assertEqual(os.listdir(os.path.join(self.repo, "dist", "sources")), ["tool-1.tar.gz"])

        # reproducible: the same archives again
        before = native["archives"]["arm64"]["sha256"]
        self.assertEqual(self.run_tool().returncode, 0)
        with open(os.path.join(self.repo, "index.json")) as file:
            index = {entry["id"]: entry for entry in json.load(file)["plugins"]}
        self.assertEqual(index["org.example.native"]["archives"]["arm64"]["sha256"], before)

    def test_missing_native_build_fails(self):
        native = os.path.join(self.repo, "plugins", "org.example.native", "bin", "arm64")
        for name in os.listdir(native):
            os.remove(os.path.join(native, name))
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bin/arm64/ is empty", result.stderr)

    def test_missing_sources_fail(self):
        os.remove(os.path.join(self.repo, "dist", "sources", "tool-1.tar.gz"))
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dist/sources/tool-1.tar.gz missing", result.stderr)

    def test_native_arches(self):
        result = self.run_tool("--native-arches")
        self.assertEqual(result.stdout.split("\n"), ["org.example.native amd64", "org.example.native arm64", ""])


if __name__ == "__main__":
    unittest.main()
