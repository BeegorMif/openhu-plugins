"""The library scan with generated audio files (tools/make-test-music.py: ffmpeg tones, mutagen tags, embedded and
folder covers), the incremental rescan, sources and the queries of the page."""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
import library  # noqa: E402


def load_maker():
    spec = importlib.util.spec_from_file_location("make_test_music",
                                                  os.path.join(TESTS, "..", "tools", "make-test-music.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HAVE_TOOLS = bool(importlib.util.find_spec("mutagen")) and bool(shutil.which("ffmpeg"))
MUSIC = None


def setUpModule():
    global MUSIC
    if HAVE_TOOLS:
        MUSIC = tempfile.mkdtemp(prefix="openhu-music-test-")
        load_maker().make(os.path.join(MUSIC, "media", "sdb1"), seconds=1, size=48)


def tearDownModule():
    if MUSIC:
        shutil.rmtree(MUSIC, ignore_errors=True)


class SourcesTest(unittest.TestCase):
    def test_sources_with_uuid_label_and_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "media")
            for name in ("sdb1", "sdc1", ".hidden"):
                os.makedirs(os.path.join(media, name))
            disk = os.path.join(tmp, "disk")
            os.makedirs(os.path.join(disk, "by-uuid"))
            os.makedirs(os.path.join(disk, "by-label"))
            open(os.path.join(tmp, "sdb1"), "w").close()
            os.symlink(os.path.join(tmp, "sdb1"), os.path.join(disk, "by-uuid", "1234-ABCD"))
            os.symlink(os.path.join(tmp, "sdb1"), os.path.join(disk, "by-label", "MY\\x20MUSIC"))
            local = os.path.join(tmp, "Music")
            os.makedirs(local)
            folder = os.path.join(tmp, "extra")
            os.makedirs(folder)
            devices = {os.path.join(media, "sdb1"): os.path.join(tmp, "sdb1")}
            sources = library.find_sources(media, local, [folder, folder, os.path.join(tmp, "gone")], devices, disk)
            self.assertEqual([(source.key, source.name, source.kind, source.stick) for source in sources],
                             [("uuid-1234-ABCD", "MY MUSIC", "usb", "sdb1"), ("usb-sdc1", "sdc1", "usb", "sdc1"),
                              ("local", "", "local", None), (sources[3].key, "extra", "folder", None)])
            self.assertTrue(sources[3].key.startswith("folder-"))

    def test_ids(self):
        self.assertEqual(library.split_id(library.track_id("uuid-1", "Music/a:b.mp3")), ("uuid-1", "Music/a:b.mp3"))
        self.assertEqual(library.parse_album_id(library.album_id("A", "B")), ("A", "B"))
        self.assertIsNone(library.parse_album_id("nonsense"))


@unittest.skipUnless(HAVE_TOOLS, "needs python3-mutagen and ffmpeg")
class ScanTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.stick_dir = os.path.join(self.data.name, "stick")
        shutil.copytree(os.path.join(MUSIC, "media", "sdb1"), self.stick_dir)
        self.library = library.Library(self.data.name)
        self.source = library.Source("uuid-TEST", "TESTSTICK", self.stick_dir, library.USB, stick="sdb1")
        self.library.set_sources([self.source])
        self.progress = []
        self.files, self.read = self.library.scan(self.source, lambda done, total: self.progress.append((done, total)))

    def tearDown(self):
        self.library.close()
        self.data.cleanup()

    def test_tags_of_every_format(self):
        self.assertEqual((self.files, self.read), (11, 11))
        self.assertEqual(self.progress[-1], (11, 11))
        rows = {track["title"]: track for track in self.library.songs(limit=50)["items"]}
        for title, artist, album, number in [("First Light", "Aurora Lane", "Northern Lights", 1),
                                             ("Low Tide", "Aurora Lane", "Harbour", 1),
                                             ("Overpass", "The Pebbles", "Road Songs", 2),
                                             ("Coast Road", "Marlo Vance", "Summer Drive", 1),
                                             ("Dunes", "Kit Harrow", "Summer Drive", 2)]:
            self.assertEqual((rows[title]["artist"], rows[title]["album"], rows[title]["track"]),
                             (artist, album, number), title)
            self.assertAlmostEqual(rows[title]["duration"], 1.0, delta=0.2)
        # without tags: the file name is the title, the folder the album
        self.assertEqual((rows["untagged recording"]["artist"], rows["untagged recording"]["album"]), ("", "Loose"))
        self.assertEqual(rows["First Light"]["year"], 2021)

    def test_covers_embedded_and_from_the_folder(self):
        rows = {track["title"]: track for track in self.library.songs(limit=50)["items"]}
        for title in ("First Light", "Low Tide", "Dunes", "Mile Marker"):
            cover = rows[title]["cover"]
            self.assertTrue(cover.startswith("file://" + self.library.cover_dir), title)
            with open(cover[len("file://"):], "rb") as file:
                self.assertEqual(file.read(8), b"\x89PNG\r\n\x1a\n")
        self.assertEqual(rows["Coast Road"]["cover"], "")
        # the same picture once in the cache
        self.assertEqual(rows["First Light"]["cover"], rows["Green Sky"]["cover"])
        url = self.library.cover_data_url(rows["First Light"]["coverName"])
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertLessEqual(len(url), library.MAX_COVER_URL_BYTES * 4 // 3 + 100)

    def test_rescan_reads_only_changed_files(self):
        self.assertEqual(self.library.scan(self.source), (11, 0))
        path = os.path.join(self.stick_dir, "Music", "Aurora Lane", "Harbour", "02 Lighthouse.flac")
        import mutagen
        audio = mutagen.File(path)
        audio["title"] = "Lighthouse (Live)"
        audio.save()
        os.utime(path, (time.time() + 5, time.time() + 5))
        os.remove(os.path.join(self.stick_dir, "Music", "Loose", "untagged recording.wav"))
        self.assertEqual(self.library.scan(self.source), (10, 1))
        titles = [track["title"] for track in self.library.songs(limit=50)["items"]]
        self.assertIn("Lighthouse (Live)", titles)
        self.assertNotIn("untagged recording", titles)

    def test_albums_artists_and_songs(self):
        albums = self.library.albums()
        self.assertEqual(albums["total"], 6)
        self.assertEqual([item["title"] for item in albums["items"]],
                         ["Echo", "Harbour", "Loose", "Northern Lights", "Road Songs", "Summer Drive"])
        summer = next(item for item in albums["items"] if item["title"] == "Summer Drive")
        self.assertEqual((summer["subtitle"], summer["count"]), ("Various Artists", 2))
        album = self.library.album(summer["id"])
        self.assertEqual([track["title"] for track in album["tracks"]], ["Coast Road", "Dunes"])
        artists = self.library.artists()
        self.assertEqual([item["title"] for item in artists["items"]],
                         ["Aurora Lane", "Quiet Hours", "The Pebbles", "Various Artists", ""])
        aurora = artists["items"][0]
        self.assertEqual((aurora["albums"], aurora["count"], len(aurora["covers"])), (2, 5, 2))
        artist = self.library.artist("Aurora Lane")
        self.assertEqual([item["title"] for item in artist["items"]], ["Northern Lights", "Harbour"])
        by_artist = [track["title"] for track in self.library.songs("artist", limit=3)["items"]]
        self.assertEqual(by_artist, ["Low Tide", "Lighthouse", "First Light"])
        page = self.library.songs("title", offset=2, limit=2)
        self.assertEqual((page["total"], len(page["items"])), (11, 2))
        self.assertEqual(len(self.library.song_ids("added")), 11)

    def test_folders(self):
        top = self.library.folder("", "")
        self.assertEqual([crumb["title"] for crumb in top["crumbs"]], ["TESTSTICK"])
        self.assertEqual([item["title"] for item in top["folders"]], ["Music"])
        music = self.library.folder(self.source.key, "Music")
        self.assertEqual([item["title"] for item in music["folders"]],
                         ["Aurora Lane", "Compilations", "Loose", "The Pebbles"])
        aurora = music["folders"][0]
        self.assertEqual((aurora["count"], len(aurora["covers"])), (5, 2))
        loose = self.library.folder(self.source.key, "Music/Loose")
        self.assertEqual([item["title"] for item in loose["folders"]], ["Deep"])
        self.assertEqual([track["title"] for track in loose["files"]], ["untagged recording"])
        self.assertEqual([crumb["path"] for crumb in loose["crumbs"]], ["", "Music", "Music/Loose"])
        self.assertEqual(len(self.library.folder_tracks(self.source.key, "Music/Loose")), 2)
        deep = self.library.folder(self.source.key, "Music/Loose/Deep/Nested/Folder")
        self.assertEqual([track["title"] for track in deep["files"]], ["Echo"])

    def test_playlists_found_on_the_stick(self):
        found = self.library.playlists()
        self.assertEqual(sorted((item["title"], item["type"], item["count"]) for item in found["items"]),
                         [("Evening", "pls", 2), ("Road trip", "m3u", 3)])
        road = next(item for item in found["items"] if item["title"] == "Road trip")
        playlist = self.library.playlist(road["id"])
        self.assertEqual([(track["title"], track["available"]) for track in playlist["tracks"]],
                         [("Mile Marker", True), ("Green Sky", True), ("Gone - Missing", False)])
        self.assertEqual(len(road["covers"]), 2)

    def test_unplugged_source(self):
        track = self.library.songs(limit=1)["items"][0]["id"]
        self.assertTrue(self.library.available(track))
        self.library.set_sources([])
        self.assertFalse(self.library.available(track))
        self.assertEqual(self.library.count(), 0)
        self.assertFalse(self.library.track(track)["available"])
        self.assertEqual(self.library.tracks(["nope:x.mp3"])[0]["available"], False)
        self.assertEqual(json.loads(json.dumps(self.library.folder("", ""))), {"source": "", "path": "", "crumbs": [],
                                                                                  "folders": [], "files": []})


if __name__ == "__main__":
    unittest.main()
