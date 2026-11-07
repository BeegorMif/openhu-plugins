"""Play queue modes with a fixed seed: order, shuffle (no repeat within a round or across its boundary, inserts
during a round), random (distribution), repeat, history, previous after 3 s, saving."""

import collections
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import playqueue  # noqa: E402
from playqueue import ORDER, RANDOM, REPEAT_ALL, REPEAT_OFF, REPEAT_ONE, SHUFFLE, PlayQueue  # noqa: E402

TRACKS = ["t%02d" % number for number in range(12)]


def play_all(queue, count):
    """count tracks as they play one after the other (auto advance), the current one first."""
    played = [queue.current()]
    for _ in range(count - 1):
        played.append(queue.next(auto=True))
    return played


class OrderTest(unittest.TestCase):
    def test_order_from_start_and_end(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS, start=3)
        self.assertEqual(queue.current(), "t03")
        self.assertEqual(play_all(queue, 9), TRACKS[3:])
        self.assertIsNone(queue.next(auto=True))
        self.assertIsNone(queue.peek())
        # the last one stays current at the end
        self.assertEqual(queue.current(), "t11")

    def test_repeat_all_wraps(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS[:3], start=1)
        queue.set_repeat(REPEAT_ALL)
        self.assertEqual(play_all(queue, 6), ["t01", "t02", "t00", "t01", "t02", "t00"])

    def test_wrapped_with_repeat(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS[:4], start=2)
        self.assertEqual(queue.wrapped(), [])
        queue.set_repeat(REPEAT_ALL)
        # after the end the list again from its start, up to the current one
        self.assertEqual([track for _, track in queue.wrapped()], ["t00", "t01", "t02"])
        self.assertEqual([track for _, track in queue.wrapped(2)], ["t00", "t01"])
        queue.next(auto=True)
        self.assertEqual([track for _, track in queue.upcoming() + queue.wrapped()], ["t00", "t01", "t02", "t03"])
        self.assertEqual(queue.peek(), "t00")
        # a tap on an entry after the end
        key = queue.wrapped()[1][0]
        self.assertEqual(queue.jump(key), "t01")
        self.assertEqual([track for _, track in queue.upcoming()], ["t02", "t03"])

    def test_repeat_one(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS[:3])
        queue.set_repeat(REPEAT_ONE)
        self.assertEqual(queue.peek(), "t00")
        self.assertEqual(play_all(queue, 3), ["t00", "t00", "t00"])
        # next by hand moves on, and wraps around at the end
        self.assertEqual(queue.next(), "t01")
        queue.next()
        self.assertEqual(queue.next(), "t00")

    def test_previous_restarts_after_three_seconds(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS[:3], start=1)
        self.assertEqual(queue.previous(position=3.5), ("t01", True))
        self.assertEqual(queue.previous(position=1.0), ("t00", False))
        # at the start: the same track from its start
        self.assertEqual(queue.previous(position=0.0), ("t00", True))
        queue.set_repeat(REPEAT_ALL)
        self.assertEqual(queue.previous(position=0.0), ("t02", False))

    def test_unavailable_tracks_are_skipped(self):
        gone = {"t01", "t02"}
        queue = PlayQueue(seed=1, available=lambda track: track not in gone)
        queue.set_tracks(TRACKS[:5])
        self.assertEqual(play_all(queue, 3), ["t00", "t03", "t04"])
        self.assertEqual(queue.previous(position=0), ("t03", False))
        self.assertEqual(queue.previous(position=0), ("t00", False))

    def test_play_next_enqueue_move_remove_jump(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(["a", "b", "c"])
        queue.play_next(["x"])
        queue.enqueue(["z"])
        self.assertEqual([track for _, track in queue.upcoming()], ["x", "b", "c", "z"])
        keys = {track: key for key, track in queue.upcoming()}
        self.assertTrue(queue.move(keys["z"], 0))
        self.assertEqual([track for _, track in queue.upcoming()], ["z", "x", "b", "c"])
        self.assertTrue(queue.remove(keys["x"]))
        self.assertFalse(queue.remove(queue.current_key))
        self.assertEqual(queue.jump(keys["c"]), "c")
        self.assertIsNone(queue.next())
        self.assertEqual(queue.items, queue.order)

    def test_save_and_load(self):
        queue = PlayQueue(seed=3)
        queue.set_tracks(TRACKS, start=2, mode=SHUFFLE)
        queue.set_repeat(REPEAT_ALL)
        queue.next()
        queue.next()
        saved = queue.to_dict()
        again = PlayQueue(seed=4)
        self.assertTrue(again.load(saved))
        self.assertEqual((again.current(), again.mode, again.repeat), (queue.current(), SHUFFLE, REPEAT_ALL))
        self.assertEqual(again.upcoming(), queue.upcoming())
        # new entries get new keys
        key = again.enqueue(["new"])[0]
        self.assertNotIn(key, queue.tracks)
        self.assertFalse(PlayQueue().load({"items": []}))
        self.assertFalse(PlayQueue().load({"items": [[1, "a"]], "pos": 5}))


class ShuffleTest(unittest.TestCase):
    def test_round_without_repeats_chosen_first(self):
        for seed in range(30):
            queue = PlayQueue(seed=seed)
            queue.set_tracks(TRACKS, start=5, mode=SHUFFLE)
            played = play_all(queue, len(TRACKS))
            self.assertEqual(played[0], "t05")
            self.assertEqual(sorted(played), TRACKS, "seed %d" % seed)
            self.assertNotEqual(played, ["t05"] + [t for t in TRACKS if t != "t05"], "shuffled")
            # repeat off: the end after one round
            self.assertIsNone(queue.next(auto=True))

    def test_rounds_never_repeat_across_the_boundary(self):
        for seed in range(50):
            queue = PlayQueue(seed=seed)
            queue.set_tracks(TRACKS[:4], start=0, mode=SHUFFLE)
            queue.set_repeat(REPEAT_ALL)
            played = play_all(queue, 4 * 25)
            rounds = [played[index:index + 4] for index in range(0, len(played), 4)]
            for number, tracks in enumerate(rounds):
                self.assertEqual(sorted(tracks), TRACKS[:4], "seed %d round %d" % (seed, number))
                if number:
                    self.assertNotEqual(tracks[0], rounds[number - 1][-1], "seed %d round %d" % (seed, number))
            # the rounds differ (shuffled again)
            self.assertGreater(len({tuple(tracks) for tracks in rounds}), 3)

    def test_two_tracks_alternate(self):
        queue = PlayQueue(seed=7)
        queue.set_tracks(["a", "b"], start=0, mode=SHUFFLE)
        queue.set_repeat(REPEAT_ALL)
        played = play_all(queue, 10)
        self.assertTrue(all(first != second for first, second in zip(played, played[1:])), played)

    def test_peek_matches_next_also_at_the_boundary(self):
        queue = PlayQueue(seed=11)
        queue.set_tracks(TRACKS[:5], start=0, mode=SHUFFLE)
        queue.set_repeat(REPEAT_ALL)
        for _ in range(20):
            expected = queue.peek()
            self.assertEqual(queue.next(auto=True), expected)

    def test_inserts_go_into_the_unplayed_part(self):
        for seed in range(30):
            queue = PlayQueue(seed=seed)
            queue.set_tracks(TRACKS[:8], start=0, mode=SHUFFLE)
            played = play_all(queue, 4)
            queue.enqueue(["new1", "new2", "new3"])
            rest = [queue.next(auto=True) for _ in range(4 + 3)]
            self.assertIsNone(queue.next(auto=True))
            self.assertEqual(sorted(played + rest), sorted(TRACKS[:8] + ["new1", "new2", "new3"]))
            self.assertTrue(set(rest) >= {"new1", "new2", "new3"})
        # spread over the rest, not only at its end
        positions = collections.Counter()
        for seed in range(200):
            queue = PlayQueue(seed=seed)
            queue.set_tracks(TRACKS[:8], start=0, mode=SHUFFLE)
            queue.enqueue(["new"])
            positions[[track for _, track in queue.upcoming()].index("new")] += 1
        self.assertGreater(len(positions), 5)

    def test_play_next_in_shuffle(self):
        queue = PlayQueue(seed=2)
        queue.set_tracks(TRACKS[:6], start=0, mode=SHUFFLE)
        queue.play_next(["x"])
        self.assertEqual(queue.next(auto=True), "x")

    def test_previous_walks_back_into_the_last_round(self):
        queue = PlayQueue(seed=5)
        queue.set_tracks(TRACKS[:3], start=0, mode=SHUFFLE)
        queue.set_repeat(REPEAT_ALL)
        played = play_all(queue, 5)
        back = [queue.previous(position=0)[0] for _ in range(4)]
        self.assertEqual(back, list(reversed(played[:-1])))
        # and forward again the same way
        self.assertEqual([queue.next() for _ in range(4)], played[1:])

    def test_wrapped_is_the_next_round(self):
        queue = PlayQueue(seed=5)
        queue.set_mode(SHUFFLE)
        queue.set_tracks(TRACKS[:5])
        queue.set_repeat(REPEAT_ALL)
        for _ in range(len(queue.upcoming())):
            queue.next(auto=True)
        self.assertEqual(queue.upcoming(), [])
        round_ = [track for _, track in queue.wrapped()]
        self.assertEqual(sorted(round_), TRACKS[:5])
        # the round shown is the one that plays, also when tapped in the middle
        self.assertEqual(queue.peek(), round_[0])
        key = queue.wrapped()[2][0]
        self.assertEqual(queue.jump(key), round_[2])
        self.assertEqual([track for _, track in queue.upcoming()], round_[3:])

    def test_jump_keeps_the_skipped_ones(self):
        queue = PlayQueue(seed=9)
        queue.set_tracks(TRACKS[:6], start=0, mode=SHUFFLE)
        upcoming = queue.upcoming()
        key, track = upcoming[3]
        self.assertEqual(queue.jump(key), track)
        rest = [queue.next(auto=True) for _ in range(4)]
        self.assertEqual(sorted(rest), sorted(t for _, t in upcoming if t != track))

    def test_switching_modes_keeps_the_current_track(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS, start=4)
        queue.cycle_mode()
        self.assertEqual((queue.mode, queue.current()), (SHUFFLE, "t04"))
        queue.cycle_mode()
        self.assertEqual((queue.mode, queue.current()), (RANDOM, "t04"))
        queue.cycle_mode()
        self.assertEqual((queue.mode, queue.current()), (ORDER, "t04"))
        self.assertEqual(queue.next(), "t05")
        self.assertEqual([queue.cycle_repeat() for _ in range(3)], [REPEAT_ALL, REPEAT_ONE, REPEAT_OFF])


class RandomTest(unittest.TestCase):
    def test_uniform_with_repeats(self):
        queue = PlayQueue(seed=42)
        queue.set_tracks(TRACKS[:6], start=0, mode=RANDOM)
        played = play_all(queue, 6001)[1:]
        counts = collections.Counter(played)
        self.assertEqual(set(counts), set(TRACKS[:6]))
        for track, count in counts.items():
            self.assertAlmostEqual(count / 6000, 1 / 6, delta=0.025, msg=track)
        # true random: the same track twice in a row happens
        self.assertTrue(any(first == second for first, second in zip(played, played[1:])))
        # it never ends, not even with repeat off
        self.assertEqual(queue.repeat, REPEAT_OFF)
        self.assertIsNotNone(queue.next(auto=True))

    def test_draws_ahead_and_history(self):
        queue = PlayQueue(seed=8)
        queue.set_tracks(TRACKS, start=0, mode=RANDOM)
        self.assertEqual(len(queue.upcoming()), playqueue.RANDOM_AHEAD)
        ahead = [track for _, track in queue.upcoming()]
        self.assertEqual([queue.peek()], ahead[:1])
        played = play_all(queue, 4)
        self.assertEqual(played[1:], ahead[:3])
        back = [queue.previous(0)[0] for _ in range(3)]
        self.assertEqual(back, list(reversed(played[:-1])))
        self.assertEqual(queue.previous(0), ("t00", True))

    def test_history_is_bounded(self):
        queue = PlayQueue(seed=1)
        queue.set_tracks(TRACKS, start=0, mode=RANDOM)
        for _ in range(playqueue.HISTORY_LIMIT * 2):
            queue.next(auto=True)
        self.assertLessEqual(len(queue.order), playqueue.HISTORY_LIMIT + playqueue.RANDOM_AHEAD + 1)


if __name__ == "__main__":
    unittest.main()
