"""The mpv player against the simulated mpv (tools/fake-mpv): load with the next track preloaded, the gapless
change ("advanced"), the end, pause, seek, broken files and the end of mpv with the plugin."""

import asyncio
import json
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAKE_MPV = os.path.normpath(os.path.join(TESTS, "..", "tools", "fake-mpv", "mpv"))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
from player import MPV_ARGS, Player  # noqa: E402


class PlayerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.files = []
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            path = os.path.join(self.tmp.name, name)
            open(path, "w").close()
            self.files.append(path)
        self.log = os.path.join(self.tmp.name, "commands.log")
        env = dict(os.environ, FAKE_MPV_DURATION="0.4", FAKE_MPV_LOG=self.log)
        self.events = []
        self.player = Player(mpv=FAKE_MPV, on_event=self.on_event, socket_dir=self.tmp.name, env=env)

    async def asyncTearDown(self):
        await self.player.close()
        self.tmp.cleanup()

    def on_event(self, name, data):
        self.events.append((name, data))

    async def wait_for(self, name, timeout=5):
        for _ in range(int(timeout / 0.02)):
            if any(event == name for event, _ in self.events):
                return [data for event, data in self.events if event == name]
            await asyncio.sleep(0.02)
        self.fail("no %s event: %s" % (name, self.events))

    def commands(self):
        with open(self.log) as file:
            return [json.loads(line) for line in file]

    def test_arguments(self):
        for argument in ("--idle=yes", "--no-video", "--no-terminal", "--gapless-audio=yes"):
            self.assertIn(argument, MPV_ARGS)

    async def test_gapless_change_and_end(self):
        await self.player.load(self.files[0], self.files[1])
        self.assertIn(["loadfile", self.files[0], "replace"], self.commands())
        self.assertIn(["loadfile", self.files[1], "append"], self.commands())
        advanced = await self.wait_for("advanced")
        self.assertEqual(advanced[0]["path"], self.files[1])
        self.assertEqual(self.player.current, self.files[1])
        self.assertIn(["playlist-remove", 0], self.commands())
        # mpv has only the current one again
        self.assertEqual(await self.player.get("playlist-count"), 1)
        await self.player.set_next(self.files[2])
        self.assertEqual(await self.player.get("playlist-count"), 2)
        # replaced by another next one
        await self.player.set_next(self.files[0])
        self.assertEqual(await self.player.get("playlist-count"), 2)
        await self.player.set_next(None)
        self.assertEqual(await self.player.get("playlist-count"), 1)
        await self.wait_for("ended")
        self.assertIsNone(self.player.current)

    async def test_pause_seek_position(self):
        await self.player.load(self.files[0], position=0.2, paused=True)
        await asyncio.sleep(0.1)
        self.assertTrue(self.player.paused)
        self.assertAlmostEqual(await self.player.position(), 0.2, delta=0.05)
        await self.player.seek(0.1)
        self.assertAlmostEqual(await self.player.position(), 0.1, delta=0.05)
        await self.player.set_paused(False)
        await asyncio.sleep(0.15)
        self.assertGreater(await self.player.position(), 0.15)
        self.assertEqual((await self.wait_for("pause"))[-1], {"paused": False})
        await self.player.stop()
        self.assertIsNone(await self.player.get("path"))

    async def test_broken_file(self):
        broken = os.path.join(self.tmp.name, "x.broken")
        open(broken, "w").close()
        await self.player.load(broken)
        errors = await self.wait_for("error")
        self.assertEqual(errors[0]["path"], broken)
        # a broken preloaded one after the current one
        self.events.clear()
        await self.player.load(self.files[0], broken)
        errors = await self.wait_for("error")
        self.assertEqual(errors[0]["path"], broken)
        self.assertNotIn("advanced", [event for event, _ in self.events])

    async def test_close_ends_mpv(self):
        await self.player.load(self.files[0])
        process = self.player.process
        await self.player.close()
        self.assertIsNotNone(process.returncode)
        self.assertFalse(self.player.running)
        # starts again on the next command
        await self.player.load(self.files[1])
        self.assertTrue(self.player.running)


if __name__ == "__main__":
    unittest.main()
