"""The play queue of the music player, without I/O (tests/test_playqueue.py; a seed makes it reproducible).

Every entry of the queue has its own key (the same track can be in it twice). The queue keeps
    items  the keys in the order of the source (album, folder, playlist, sort order of the songs)
    order  the keys in the order they play: in "order" the same as items; in "shuffle" the current round, a random
           permutation; in "random" the timeline of the draws (the played ones and RANDOM_AHEAD drawn in advance)
    pos    the index of the current entry in order

Modes:
    order    the order of the source
    shuffle  a random permutation without repeats: the chosen track first, no track twice until all have played.
             The next round is shuffled again, and the track that played last never starts it. Tracks added during
             a round go to random places in the part that has not played yet. Previous walks back through the
             history, also into earlier rounds.
    random   true random: every next track is drawn uniformly from all tracks (repeats are possible)
Repeat: off, all, one (one: the track again when it ends on its own; next/previous still move on).
Previous after more than RESTART_SECONDS goes back to the start of the track.
"""

import random

ORDER, SHUFFLE, RANDOM = "order", "shuffle", "random"
MODES = (ORDER, SHUFFLE, RANDOM)
REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = "off", "all", "one"
REPEATS = (REPEAT_OFF, REPEAT_ALL, REPEAT_ONE)
RESTART_SECONDS = 3
RANDOM_AHEAD = 10
HISTORY_LIMIT = 500


class PlayQueue:
    def __init__(self, seed=None, available=None):
        self.rng = random.Random(seed)
        # track -> bool: tracks of a stick that is not plugged in are skipped
        self.available = available or (lambda track: True)
        self.tracks = {}
        self.items = []
        self.order = []
        self.pos = -1
        self.mode = ORDER
        self.repeat = REPEAT_OFF
        # shuffle: keys of earlier rounds, oldest first (previous walks back into them)
        self.history = []
        # shuffle at the end of a round: the next round, decided once (peek and next agree)
        self.next_round = None
        self.next_key = 1
        # counts every change of the queue (the page reloads "Up next" when it changes)
        self.version = 0

    # --- reading ---------------------------------------------------------------------

    @property
    def current_key(self):
        return self.order[self.pos] if 0 <= self.pos < len(self.order) else None

    def current(self):
        return self.tracks.get(self.current_key)

    def track(self, key):
        return self.tracks.get(key)

    def __len__(self):
        return len(self.items)

    def upcoming(self, limit=None):
        """[(key, track)] that play after the current one, in their order (random: the ones drawn in advance)."""
        keys = self.order[self.pos + 1:] if self.pos >= 0 else list(self.order)
        if limit is not None:
            keys = keys[:limit]
        return [(key, self.tracks[key]) for key in keys]

    def played_count(self):
        """How many entries of order played before the current one (for "3 / 12")."""
        return max(self.pos, 0)

    # --- building ------------------------------------------------------------------------

    def _changed(self):
        self.version += 1

    def _add(self, tracks):
        keys = []
        for track in tracks:
            key = self.next_key
            self.next_key += 1
            self.tracks[key] = track
            keys.append(key)
        return keys

    def _ok(self, key):
        return key in self.tracks and self.available(self.tracks[key])

    def _pool(self):
        return [key for key in self.items if self._ok(key)]

    def _shuffled(self, keys):
        keys = list(keys)
        self.rng.shuffle(keys)
        return keys

    def _build(self, current):
        """order and pos for the mode, current (a key or None) as the current entry."""
        self.next_round = None
        if self.mode == ORDER:
            self.order = list(self.items)
            self.pos = self.order.index(current) if current in self.order else (0 if self.order else -1)
        elif self.mode == SHUFFLE:
            rest = self._shuffled(key for key in self.items if key != current)
            self.order = ([current] if current is not None else []) + rest
            self.pos = 0 if self.order else -1
        else:
            if current is None:
                pool = self._pool()
                current = self.rng.choice(pool) if pool else None
            self.order = [current] if current is not None else []
            self.pos = 0 if self.order else -1
            self._fill_random()

    def _fill_random(self):
        if self.mode != RANDOM or self.pos < 0:
            return
        pool = self._pool()
        while pool and len(self.order) - self.pos - 1 < RANDOM_AHEAD:
            self.order.append(self.rng.choice(pool))
        if self.pos > HISTORY_LIMIT:
            drop = self.pos - HISTORY_LIMIT
            self.order = self.order[drop:]
            self.pos -= drop

    def set_tracks(self, tracks, start=0, mode=None):
        """A new queue (play an album, a folder, ...): start is the index of the track that plays first (None in
        shuffle/random: a random one), mode switches the mode with it (e.g. "Shuffle all")."""
        self.tracks, self.items, self.history = {}, [], []
        self.items = self._add(tracks)
        if mode in MODES:
            self.mode = mode
        current = None
        if self.items:
            if start is None:
                pool = self._pool() or self.items
                current = self.rng.choice(pool) if self.mode != ORDER else pool[0]
            else:
                current = self.items[max(0, min(int(start), len(self.items) - 1))]
        self._build(current)
        self._changed()

    def clear(self):
        self.tracks, self.items, self.order, self.history = {}, [], [], []
        self.pos = -1
        self.next_round = None
        self._changed()

    def set_mode(self, mode):
        if mode not in MODES or mode == self.mode:
            return False
        current = self.current_key
        self.mode = mode
        self.history = []
        self._build(current)
        self._changed()
        return True

    def cycle_mode(self):
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])
        return self.mode

    def set_repeat(self, repeat):
        if repeat not in REPEATS or repeat == self.repeat:
            return False
        self.repeat = repeat
        self._changed()
        return True

    def cycle_repeat(self):
        self.set_repeat(REPEATS[(REPEATS.index(self.repeat) + 1) % len(REPEATS)])
        return self.repeat

    # --- moving through the queue -------------------------------------------------------

    def _new_round(self):
        """The next shuffle round: all tracks, the current one (the last that played) not first."""
        if self.next_round is None:
            keys = self._shuffled(self.items)
            last = self.current_key
            if len(keys) > 1 and keys[0] == last:
                other = self.rng.randrange(1, len(keys))
                keys[0], keys[other] = keys[other], keys[0]
            self.next_round = keys
        return self.next_round

    def _step(self, auto, commit):
        """Key of the entry after the current one (None: the end); commit moves there."""
        if self.pos < 0 or not self.order:
            return None
        if auto and self.repeat == REPEAT_ONE and self._ok(self.current_key):
            return self.current_key
        if self.mode == RANDOM:
            self._fill_random()
        for index in range(self.pos + 1, len(self.order)):
            if self._ok(self.order[index]):
                if commit:
                    self.pos = index
                    self._fill_random()
                    self._changed()
                return self.order[index]
        # the end of the list (random never gets here while a track is available); repeat one wraps around like
        # repeat all for next by hand
        if self.repeat == REPEAT_OFF:
            return None
        if self.mode == ORDER:
            for index in range(0, self.pos + 1):
                if self._ok(self.order[index]):
                    if commit:
                        self.pos = index
                        self._changed()
                    return self.order[index]
            return None
        if self.mode == SHUFFLE:
            keys = self._new_round()
            for index, key in enumerate(keys):
                if self._ok(key):
                    if commit:
                        self.history = (self.history + self.order)[-HISTORY_LIMIT:]
                        self.order = keys
                        self.pos = index
                        self.next_round = None
                        self._changed()
                    return key
        return None

    def peek(self):
        """The track that plays when the current one ends on its own (preloaded for gapless playback)."""
        return self.tracks.get(self._step(auto=True, commit=False))

    def next(self, auto=False):
        """Moves to the next track and returns it (None at the end); auto: the current one ended on its own."""
        return self.tracks.get(self._step(auto, commit=True))

    def previous(self, position=0.0):
        """-> (track, restart). After more than RESTART_SECONDS (position) or at the start the same track from its
        start (restart True), otherwise the one that played before."""
        if self.current_key is None:
            return None, False
        if position > RESTART_SECONDS:
            return self.current(), True
        for index in range(self.pos - 1, -1, -1):
            if self._ok(self.order[index]):
                self.pos = index
                self._changed()
                return self.current(), False
        if self.mode == SHUFFLE:
            while self.history:
                key = self.history.pop()
                if self._ok(key):
                    # back into the round before: it becomes the start of this round's timeline
                    self.order.insert(0, key)
                    self.pos = 0
                    self.next_round = None
                    self._changed()
                    return self.current(), False
        if self.mode == ORDER and self.repeat != REPEAT_OFF:
            for index in range(len(self.order) - 1, self.pos, -1):
                if self._ok(self.order[index]):
                    self.pos = index
                    self._changed()
                    return self.current(), False
        return self.current(), True

    def jump(self, key):
        """Plays an entry of the queue now (a tap in "Up next"). In shuffle and random the entries before it stay
        unplayed; in order it is the position in the list."""
        if key not in self.tracks or key not in self.order:
            return None
        if self.mode == ORDER:
            self.pos = self.order.index(key)
        else:
            index = self.order.index(key, self.pos + 1) if key in self.order[self.pos + 1:] else self.order.index(key)
            self.order.pop(index)
            if index < self.pos:
                self.pos -= 1
            self.order.insert(self.pos + 1, key)
            self.pos += 1
            self._fill_random()
        self.next_round = None
        self._changed()
        return self.current()

    # --- changing the queue --------------------------------------------------------------

    def play_next(self, tracks):
        """Tracks right after the current one (in every mode); keys."""
        keys = self._add(tracks)
        if not keys:
            return keys
        current = self.current_key
        at = self.items.index(current) + 1 if current in self.items else len(self.items)
        self.items[at:at] = keys
        if self.pos < 0:
            self._build(keys[0])
        else:
            self.order[self.pos + 1:self.pos + 1] = keys
        self.next_round = None
        self._changed()
        return keys

    def enqueue(self, tracks):
        """Tracks at the end of the queue; in shuffle at random places of the part that has not played yet."""
        keys = self._add(tracks)
        if not keys:
            return keys
        self.items.extend(keys)
        if self.pos < 0:
            self._build(keys[0])
        elif self.mode == ORDER:
            self.order.extend(keys)
        elif self.mode == SHUFFLE:
            for key in keys:
                self.order.insert(self.rng.randint(self.pos + 1, len(self.order)), key)
        self.next_round = None
        self._changed()
        return keys

    def move(self, key, to):
        """Moves an entry of "Up next" to place to (0: right after the current one)."""
        upcoming = self.order[self.pos + 1:]
        if key not in upcoming:
            return False
        upcoming.remove(key)
        to = max(0, min(int(to), len(upcoming)))
        upcoming.insert(to, key)
        self.order[self.pos + 1:] = upcoming
        if self.mode == ORDER:
            self.items = list(self.order)
        self.next_round = None
        self._changed()
        return True

    def remove(self, key):
        """Removes an entry (not the current one)."""
        if key not in self.tracks or key == self.current_key:
            return False
        while key in self.order:
            index = self.order.index(key)
            self.order.pop(index)
            if index < self.pos:
                self.pos -= 1
        self.items.remove(key)
        self.history = [other for other in self.history if other != key]
        del self.tracks[key]
        self.next_round = None
        self._fill_random()
        self._changed()
        return True

    # --- saving ----------------------------------------------------------------------

    def to_dict(self):
        return {"items": [[key, self.tracks[key]] for key in self.items], "order": list(self.order),
                "pos": self.pos, "mode": self.mode, "repeat": self.repeat, "history": list(self.history),
                "nextKey": self.next_key}

    def load(self, data):
        """Restores a saved queue (to_dict); False if it is not usable."""
        try:
            tracks = {int(key): track for key, track in data["items"]}
            items = [int(key) for key, _ in data["items"]]
            order = [int(key) for key in data.get("order", items)]
            pos = int(data.get("pos", 0))
        except (KeyError, TypeError, ValueError):
            return False
        if not items or any(key not in tracks for key in order) or not 0 <= pos < len(order):
            return False
        self.tracks, self.items, self.order, self.pos = tracks, items, order, pos
        self.mode = data.get("mode") if data.get("mode") in MODES else ORDER
        self.repeat = data.get("repeat") if data.get("repeat") in REPEATS else REPEAT_OFF
        self.history = [int(key) for key in data.get("history", []) if int(key) in tracks]
        self.next_key = max([int(data.get("nextKey", 0))] + [key + 1 for key in tracks])
        self.next_round = None
        self._fill_random()
        self._changed()
        return True
