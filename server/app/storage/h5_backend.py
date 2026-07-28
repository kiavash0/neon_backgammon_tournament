"""h5py (.h5) StorageBackend — the demo format called out in SPEC §3/§6.1.

h5py is a poor fit for concurrent read/write of user records, so every
operation is guarded by a single lock (the spec's own caveat: "acceptable
for demo scale" only). Each entity is stored as a JSON-string dataset,
grouped by entity type and keyed by id.
"""

import json
import threading
from dataclasses import asdict

import h5py

from app.storage.base import (
    AdImpression,
    GameMove,
    LedgerEntry,
    Match,
    Room,
    StorageBackend,
    Tournament,
    User,
)

_GROUPS = ("users", "rooms", "tournaments", "matches", "game_moves", "ledger", "ad_impressions")
_STR_DTYPE = h5py.string_dtype(encoding="utf-8")


class H5Backend(StorageBackend):
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        if path == ":memory:":
            self._file = h5py.File("in-memory.h5", mode="w", driver="core", backing_store=False)
        else:
            self._file = h5py.File(path, mode="a")
        with self._lock:
            for name in _GROUPS:
                self._file.require_group(name)

    def close(self) -> None:
        self._file.close()

    def _put(self, group: str, entity_id: str, record: dict) -> None:
        g = self._file[group]
        if entity_id in g:
            del g[entity_id]
        g.create_dataset(entity_id, data=json.dumps(record), dtype=_STR_DTYPE)

    def _get(self, group: str, entity_id: str) -> dict | None:
        g = self._file[group]
        if entity_id not in g:
            return None
        return json.loads(g[entity_id][()])

    def _all(self, group: str) -> list[dict]:
        g = self._file[group]
        return [json.loads(g[key][()]) for key in g]

    # -- users -----------------------------------------------------------

    def create_user(self, user: User) -> User:
        with self._lock:
            self._put("users", user.id, asdict(user))
        return user

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            record = self._get("users", user_id)
        return User(**record) if record else None

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            for record in self._all("users"):
                if record["email"] == email:
                    return User(**record)
        return None

    def update_user(self, user: User) -> User:
        with self._lock:
            self._put("users", user.id, asdict(user))
        return user

    # -- rooms -------------------------------------------------------------

    def create_room(self, room: Room) -> Room:
        with self._lock:
            self._put("rooms", room.id, asdict(room))
        return room

    def get_room(self, room_id: str) -> Room | None:
        with self._lock:
            record = self._get("rooms", room_id)
        return Room(**record) if record else None

    def list_rooms(self, *, capacity: int | None = None, state: str | None = None) -> list[Room]:
        with self._lock:
            records = self._all("rooms")
        rooms = [Room(**r) for r in records]
        if capacity is not None:
            rooms = [r for r in rooms if r.capacity == capacity]
        if state is not None:
            rooms = [r for r in rooms if r.state == state]
        return rooms

    def update_room(self, room: Room) -> Room:
        with self._lock:
            self._put("rooms", room.id, asdict(room))
        return room

    # -- tournaments -------------------------------------------------------

    def create_tournament(self, tournament: Tournament) -> Tournament:
        with self._lock:
            self._put("tournaments", tournament.id, asdict(tournament))
        return tournament

    def get_tournament(self, tournament_id: str) -> Tournament | None:
        with self._lock:
            record = self._get("tournaments", tournament_id)
        return Tournament(**record) if record else None

    def update_tournament(self, tournament: Tournament) -> Tournament:
        with self._lock:
            self._put("tournaments", tournament.id, asdict(tournament))
        return tournament

    def list_tournaments(self, *, status: str | None = None) -> list[Tournament]:
        with self._lock:
            records = self._all("tournaments")
        tournaments = [Tournament(**r) for r in records]
        if status is not None:
            tournaments = [t for t in tournaments if t.status == status]
        return tournaments

    # -- matches -------------------------------------------------------

    def create_match(self, match: Match) -> Match:
        with self._lock:
            self._put("matches", match.id, asdict(match))
        return match

    def get_match(self, match_id: str) -> Match | None:
        with self._lock:
            record = self._get("matches", match_id)
        return Match(**record) if record else None

    def update_match(self, match: Match) -> Match:
        with self._lock:
            self._put("matches", match.id, asdict(match))
        return match

    def list_matches(self, tournament_id: str) -> list[Match]:
        with self._lock:
            records = self._all("matches")
        return [Match(**r) for r in records if r["tournament_id"] == tournament_id]

    # -- game moves --------------------------------------------------------

    def append_game_move(self, move: GameMove) -> GameMove:
        with self._lock:
            self._put("game_moves", move.id, asdict(move))
        return move

    def list_game_moves(self, match_id: str) -> list[GameMove]:
        with self._lock:
            records = self._all("game_moves")
        moves = [GameMove(**r) for r in records if r["match_id"] == match_id]
        return sorted(moves, key=lambda m: m.seq_index)

    # -- ledger --------------------------------------------------------

    def append_ledger_entry(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock:
            self._put("ledger", entry.id, asdict(entry))
        return entry

    def list_ledger_entries(self, user_id: str) -> list[LedgerEntry]:
        with self._lock:
            records = self._all("ledger")
        entries = [LedgerEntry(**r) for r in records if r["user_id"] == user_id]
        return sorted(entries, key=lambda e: e.created_at)

    # -- ad impressions ------------------------------------------------

    def append_ad_impression(self, impression: AdImpression) -> AdImpression:
        with self._lock:
            self._put("ad_impressions", impression.id, asdict(impression))
        return impression

    def list_ad_impressions(self, tournament_id: str) -> list[AdImpression]:
        with self._lock:
            records = self._all("ad_impressions")
        return [AdImpression(**r) for r in records if r["tournament_id"] == tournament_id]
