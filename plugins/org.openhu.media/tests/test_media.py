"""The plugin process with a fake API and the simulated mpv: media source logic (media keys only while the music is
the current source, pause when Android Auto or another source starts), gapless change, a pulled stick, the queue
saved per source, queries and own playlists. Empty files stand in for music (the fake mpv plays any file; without
tags the file names are the titles)."""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAKE_MPV = os.path.normpath(os.path.join(TESTS, "..", "tools", "fake-mpv", "mpv"))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))


class FakeApi:
    connected = True

    def __init__(self):
        self.published = []
        self.emitted = []

    async def publish(self, topic, **data):
        self.published.append((topic, data))

    async def emit(self, topic, **data):
        self.emitted.append((topic, data))

    async def safe(self, coroutine):
        return await coroutine

    def last(self, topic):
        return next((data for name, data in reversed(self.published) if name == topic), None)


@unittest.skipUnless(importlib.util.find_spec("websockets"), "needs python3-websockets (openhu.py)")
class MediaPluginTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, "data")
        self.media = os.path.join(self.tmp.name, "media")
        self.stick = os.path.join(self.media, "sdb1")
        for name in ("01 One.mp3", "02 Two.mp3", "03 Three.mp3"):
            path = os.path.join(self.stick, "Album", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        os.makedirs(self.data)
        with open(os.path.join(self.data, "config.json"), "w") as file:
            json.dump({"mediaRoot": self.media}, file)
        self.environment = dict(os.environ)
        os.environ["FAKE_MPV_DURATION"] = "0.5"
        self.plugin = await self.start()

    async def start(self):
        import media
        self.api = FakeApi()
        plugin = media.MusicPlugin(api=self.api, data_dir=self.data, mpv=FAKE_MPV)
        plugin.player.socket_dir = self.tmp.name
        await plugin.update_sources()
        await plugin.scan_task
        return plugin

    async def asyncTearDown(self):
        await self.plugin.shutdown()
        os.environ.clear()
        os.environ.update(self.environment)
        self.tmp.cleanup()

    def state(self):
        return self.api.last("music.state")

    async def command(self, cmd, **data):
        await self.plugin.on_command("music.command", dict(data, cmd=cmd))

    async def play_album(self, start=0):
        album = self.plugin.library.albums()["items"][0]
        await self.command("playItems", context={"kind": "album", "id": album["id"]}, start=start, mode="order")
        return album

    async def wait(self, condition, timeout=5):
        for _ in range(int(timeout / 0.02)):
            if condition():
                return
            await asyncio.sleep(0.02)
        self.fail("timeout, state %s" % self.state())

    async def test_play_publishes_state_and_media(self):
        await self.play_album()
        state = self.state()
        self.assertEqual((state["state"], state["track"]["title"], state["mode"]), ("playing", "01 One", "order"))
        self.assertEqual(state["sources"][0]["kind"], "usb")
        self.assertEqual(self.api.last("media.metadata")["source"], "music")
        self.assertEqual(self.api.last("media.status"), {"state": "playing", "app": "Music", "position": 0,
                                                         "shuffle": False, "repeat": False, "repeatOne": False,
                                                         "source": "music"})
        # gapless: mpv moves on by itself, the plugin follows
        await self.wait(lambda: self.state()["track"]["title"] == "02 Two")
        await self.command("pause")
        self.assertEqual(self.api.last("media.status")["state"], "paused")
        await self.command("mode", value="shuffle")
        await self.command("repeat")
        status = self.api.last("media.status")
        self.assertEqual((status["shuffle"], status["repeat"], status["repeatOne"]), (True, True, False))

    async def test_media_keys_only_while_music_is_the_source(self):
        await self.play_album()
        await self.plugin.on_action("input.action", {"action": "media.next", "phase": "click"})
        self.assertEqual(self.state()["track"]["title"], "02 Two")
        # releases are ignored
        await self.plugin.on_action("input.action", {"action": "media.next", "phase": "release"})
        self.assertEqual(self.state()["track"]["title"], "02 Two")
        # Android Auto starts its music: paused, the keys are the phone's
        await self.plugin.on_media_status("media.status", {"source": "androidauto", "state": "playing"})
        self.assertEqual(self.state()["state"], "paused")
        await self.plugin.on_action("input.action", {"action": "media.play_pause", "phase": "click"})
        self.assertEqual(self.state()["state"], "paused")
        # own actions always work
        await self.plugin.on_action("input.action", {"action": "music.toggle", "phase": "click"})
        self.assertEqual(self.state()["state"], "playing")
        await self.plugin.on_action("input.action", {"action": "media.pause", "phase": "click"})
        self.assertEqual(self.state()["state"], "paused")

    async def test_another_local_source_pauses(self):
        await self.play_album()
        # its own status does not count
        await self.plugin.on_media_status("media.status", {"source": "music", "state": "playing"})
        self.assertEqual(self.state()["state"], "playing")
        await self.plugin.on_media_status("media.status", {"source": "radio", "state": "playing"})
        self.assertEqual(self.state()["state"], "paused")
        # the radio stopped: the music does not resume by itself
        await self.plugin.on_media_status("media.status", {"source": "radio", "state": "stopped"})
        self.assertEqual(self.state()["state"], "paused")

    async def test_android_auto_pauses(self):
        await self.play_album()
        await self.plugin.on_media_status("media.status", {"source": "androidauto", "state": "playing"})
        self.assertEqual(self.state()["state"], "paused")

    async def test_pause_for_android_auto_can_be_off(self):
        self.plugin.config["pauseForAndroidAuto"] = False
        await self.play_album()
        await self.plugin.on_media_status("media.status", {"source": "androidauto", "state": "playing"})
        self.assertEqual(self.state()["state"], "playing")

    async def test_previous_and_end_of_queue(self):
        await self.play_album(start=2)
        await self.command("previous")
        self.assertEqual(self.state()["track"]["title"], "02 Two")
        await self.command("next")
        await self.wait(lambda: self.state()["state"] == "stopped")
        self.assertEqual(self.state()["track"]["title"], "03 Three")

    async def test_pulled_stick_stops_and_the_queue_comes_back(self):
        await self.play_album(start=1)
        moved = os.path.join(self.tmp.name, "away")
        shutil.move(self.stick, moved)
        await self.plugin.update_sources()
        self.assertEqual((self.state()["state"], self.state()["track"]), ("stopped", None))
        self.assertEqual(self.api.emitted[-1][0], "music.notice")
        self.assertEqual(self.api.last("media.status")["state"], "stopped")
        shutil.move(moved, self.stick)
        await self.plugin.update_sources()
        state = self.state()
        self.assertEqual((state["state"], state["track"]["title"]), ("paused", "02 Two"))
        await self.command("play")
        self.assertEqual(self.state()["state"], "playing")

    async def test_queue_survives_a_restart(self):
        await self.play_album(start=1)
        await self.command("mode", value="random")
        await self.command("pause")
        await self.plugin.shutdown()
        self.plugin = await self.start()
        state = self.state()
        self.assertEqual((state["state"], state["track"]["title"], state["mode"]), ("paused", "02 Two", "random"))

    async def test_queries(self):
        await self.plugin.on_query("music.query", {"id": 7, "cmd": "albums"})
        topic, result = self.api.emitted[-1]
        self.assertEqual((topic, result["id"], result["ok"], result["total"]), ("music.result", 7, True, 1))
        self.assertEqual(result["items"][0]["title"], "Album")
        album = result["items"][0]["id"]
        await self.plugin.on_query("music.query", {"id": 10, "cmd": "album", "album": album})
        result = self.api.emitted[-1][1]
        self.assertEqual((result["id"], result["ok"], result["title"], len(result["tracks"])), (10, True, "Album", 3))
        await self.plugin.on_query("music.query", {"id": 8, "cmd": "folder", "source": "", "path": ""})
        self.assertEqual(self.api.emitted[-1][1]["folders"][0]["title"], "Album")
        await self.play_album()
        await self.plugin.on_query("music.query", {"id": 9, "cmd": "queue"})
        self.assertEqual([item["title"] for item in self.api.emitted[-1][1]["items"]], ["02 Two", "03 Three"])
        await self.plugin.on_query("music.query", {"id": 10, "cmd": "nonsense"})
        self.assertFalse(self.api.emitted[-1][1]["ok"])

    async def test_queue_commands(self):
        await self.play_album()
        upcoming = self.plugin.queue.upcoming()
        await self.command("move", key=upcoming[1][0], to=0)
        self.assertEqual([track for _, track in self.plugin.queue.upcoming()][0], upcoming[1][1])
        await self.command("jump", key=upcoming[0][0])
        self.assertEqual(self.state()["track"]["title"], "02 Two")
        await self.command("enqueue", context={"kind": "track", "id": upcoming[0][1]}, next=True)
        self.assertEqual(self.plugin.queue.peek(), upcoming[0][1])
        await self.command("set", key="columns", value=9)
        self.assertEqual(self.state()["columns"], 6)

    async def test_own_playlists(self):
        album = self.plugin.library.albums()["items"][0]
        await self.command("createPlaylist", id=1, name="Car", context={"kind": "album", "id": album["id"]})
        self.assertTrue(self.api.emitted[-1][1]["ok"], self.api.emitted)
        path = os.path.join(self.stick, "Playlists", "Car.m3u8")
        with open(path) as file:
            self.assertIn("../Album/01 One.mp3", file.read())
        playlist = self.plugin.library.playlists()["items"][0]
        self.assertEqual((playlist["title"], playlist["type"], playlist["count"]), ("Car", "own", 3))
        await self.command("removeFromPlaylist", playlist=playlist["id"], index=0)
        await self.command("movePlaylistItem", playlist=playlist["id"], **{"from": 1, "to": 0})
        self.assertEqual([track["title"] for track in self.plugin.library.playlist(playlist["id"])["tracks"]],
                         ["03 Three", "02 Two"])
        await self.command("renamePlaylist", id=2, playlist=playlist["id"], name="Trip")
        self.assertFalse(os.path.exists(path))
        renamed = self.plugin.library.playlists()["items"]
        self.assertEqual([item["title"] for item in renamed], ["Trip"])
        await self.command("createPlaylist", id=3, name="Trip")
        self.assertFalse(self.api.emitted[-1][1]["ok"])
        await self.command("playItems", context={"kind": "playlist", "id": renamed[0]["id"]})
        self.assertEqual(self.state()["track"]["title"], "03 Three")
        await self.command("deletePlaylist", playlist=renamed[0]["id"])
        self.assertEqual(self.plugin.library.playlists()["items"], [])


if __name__ == "__main__":
    unittest.main()
