"""Playlist files: reading M3U, M3U8, PLS and XSPF (relative, absolute, Windows and file:// paths, case on FAT,
URLs ignored), writing own playlists directly and through openhu-cli on read-only sticks."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import playlists  # noqa: E402


class PlaylistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "stick")
        for path in ("Music/Artist/Album/01 Intro.mp3", "Music/Artist/Album/02 Song.flac", "Music/Other/a.ogg",
                     "Playlists/.keep"):
            full = os.path.join(self.root, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w").close()
        self.intro = os.path.join(self.root, "Music", "Artist", "Album", "01 Intro.mp3")
        self.song = os.path.join(self.root, "Music", "Artist", "Album", "02 Song.flac")
        self.other = os.path.join(self.root, "Music", "Other", "a.ogg")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = os.path.join(self.root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(text.encode(encoding))
        return path

    def test_kinds(self):
        self.assertEqual([playlists.kind_of(name) for name in ("a.M3U", "b.m3u8", "c.pls", "d.XSPF", "e.txt")],
                         ["m3u", "m3u", "pls", "xspf", None])

    def test_m3u_relative_absolute_windows_case_and_urls(self):
        path = self.write("Music/mix.m3u", "\n".join([
            "#EXTM3U",
            "#EXTINF:12,Artist - Intro",
            "Artist/Album/01 Intro.mp3",
            "ARTIST\\ALBUM\\02 SONG.FLAC",          # Windows, other case (FAT)
            "/media/usb0/Music/Other/a.ogg",       # absolute path of another computer
            "D:\\Music\\Other\\A.OGG",             # drive letter
            self.intro,                            # absolute and there
            "http://example.org/stream.mp3",       # URL: ignored
            "missing.mp3",
            "",
        ]), encoding="latin-1")
        entries = playlists.read(path, self.root)
        self.assertEqual([found for found, _, _ in entries],
                         [self.intro, self.song, self.other, self.other, self.intro, None, None])
        self.assertEqual(entries[0][2], "Artist - Intro")
        self.assertTrue(playlists.is_url(entries[5][1]))

    def test_m3u8_utf8_with_bom(self):
        os.rename(self.other, os.path.join(self.root, "Music", "Other", "Café.ogg"))
        path = self.write("Music/Other/ü.m3u8", "\ufeff#EXTM3U\n#EXTINF:-1,Café\nCafé.ogg\n")
        entries = playlists.read(path, self.root)
        self.assertEqual(entries, [(os.path.join(self.root, "Music", "Other", "Café.ogg"), "Café.ogg", "Café")])

    def test_pls(self):
        path = self.write("list.pls", "[playlist]\nFile2=Music/Artist/Album/02 Song.flac\nTitle2=Song\n"
                                      "File1=Music\\Other\\a.ogg\nFile3=https://radio.example/x\n"
                                      "NumberOfEntries=3\nVersion=2\n")
        entries = playlists.read(path, self.root)
        self.assertEqual([found for found, _, _ in entries], [self.other, self.song, None])
        self.assertEqual(entries[1][2], "Song")

    def test_xspf(self):
        path = self.write("Playlists/list.xspf", """<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
  <trackList>
    <track><location>../Music/Artist/Album/01%20Intro.mp3</location><title>Intro</title><creator>Artist</creator></track>
    <track><location>file://SONG</location></track>
    <track><location>http://example.org/a.mp3</location></track>
  </trackList>
</playlist>""".replace("SONG", self.song.replace(" ", "%20")))
        entries = playlists.read(path, self.root)
        self.assertEqual([found for found, _, _ in entries], [self.intro, self.song, None])
        self.assertEqual(entries[0][2], "Artist - Intro")
        self.assertEqual(playlists.parse_xspf("<not xml"), [])

    def test_xspf_relative_url_is_unquoted(self):
        path = self.write("Music/x.xspf", '<playlist xmlns="http://xspf.org/ns/0/"><trackList><track>'
                                          '<location>Artist/Album/02%20Song.flac</location></track></trackList></playlist>')
        # relative locations are URLs too: %20 is a space
        self.assertEqual(playlists.read(path, self.root)[0][0], self.song)

    def test_write_m3u8_directly_and_read_back(self):
        path = playlists.own_path(self.root, "Car mix")
        text = playlists.format_m3u8([(playlists.relative(path, self.song), 201.4, "Artist - Song"),
                                      (playlists.relative(path, self.other), 0, "")])
        self.assertEqual(text, "#EXTM3U\n#EXTINF:201,Artist - Song\n../Music/Artist/Album/02 Song.flac\n"
                               "#EXTINF:-1,\n../Music/Other/a.ogg\n")
        self.assertEqual(playlists.write(self.root, "Car mix", text), "direct")
        self.assertTrue(playlists.is_own(self.root, path))
        self.assertFalse(playlists.is_own(self.root, os.path.join(self.root, "Music", "mix.m3u8")))
        self.assertEqual([found for found, _, _ in playlists.read(path, self.root)], [self.song, self.other])
        self.assertFalse(os.path.exists(os.path.join(self.root, "Playlists", ".openhu-write.tmp")))
        self.assertTrue(playlists.delete(self.root, "Car mix"))
        self.assertFalse(os.path.exists(path))

    def test_names(self):
        for name in ("", " ", ".hidden", "a/b", "a\\b", "a:b", 'a"b', "a?", "a*", "x" * 200, "tab\there"):
            with self.assertRaises(playlists.PlaylistError, msg=name):
                playlists.valid_name(name)
        self.assertEqual(playlists.valid_name(" Sommer 2026 "), "Sommer 2026")

    def test_read_only_stick_goes_through_openhu_cli(self):
        calls = []

        def run(args, input=None, **kwargs):
            calls.append((args, input))
            return subprocess.CompletedProcess(args, 0, b'{"written": true}', b"")

        self.write("Playlists/Other.m3u8", "#EXTM3U\n")
        os.chmod(os.path.join(self.root, "Playlists"), 0o555)
        try:
            if os.access(os.path.join(self.root, "Playlists"), os.W_OK):
                self.skipTest("running as root: the folder stays writable")
            text = "#EXTM3U\n../Music/Other/a.ogg\n"
            self.assertEqual(playlists.write(self.root, "Car", text, stick="sdb1", run=run), "usb")
            self.assertEqual(calls, [(["pkexec", "openhu-cli", "usb", "write", "sdb1", "Playlists/Car.m3u8"],
                                      text.encode())])
            # an error of openhu-cli comes back as PlaylistError with its last line
            with self.assertRaises(playlists.PlaylistError) as error:
                playlists.write(self.root, "Car", text, stick="sdb1",
                                run=lambda args, **kwargs: subprocess.CompletedProcess(args, 1, b"", b"x\nstick full"))
            self.assertEqual(str(error.exception), "stick full")
            # without a stick name (a read-only folder) it fails
            with self.assertRaises(playlists.PlaylistError):
                playlists.write(self.root, "Car", text, run=run)
            self.assertFalse(playlists.delete(self.root, "Other"))
        finally:
            os.chmod(os.path.join(self.root, "Playlists"), 0o755)


if __name__ == "__main__":
    unittest.main()
