"""SQLite StorageBackend. Recommended default for local dev (SPEC §3):
much friendlier for concurrent CRUD during testing than the h5py backend.
"""

import json
import sqlite3
import threading

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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    dob TEXT NOT NULL,
    country TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    current_room_id TEXT
);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    capacity INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    player_ids TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournaments (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    status TEXT NOT NULL,
    bracket TEXT NOT NULL,
    winner_user_id TEXT,
    prize_usd_est REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    player_white_id TEXT,
    player_black_id TEXT,
    status TEXT NOT NULL,
    winner_id TEXT,
    game_state TEXT,
    bracket_slot INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_moves (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    seq_index INTEGER NOT NULL,
    move TEXT NOT NULL,
    roll_index INTEGER NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    tournament_id TEXT,
    created_at TEXT NOT NULL,
    meta TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_impressions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    tournament_id TEXT,
    match_id TEXT,
    network TEXT NOT NULL,
    format TEXT NOT NULL,
    est_revenue_usd REAL NOT NULL,
    ts TEXT NOT NULL
);
"""


class SqliteBackend(StorageBackend):
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- users -----------------------------------------------------------

    def create_user(self, user: User) -> User:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (id, email, password_hash, display_name, dob, country,"
                " created_at, is_deleted, failed_login_attempts, locked_until, current_room_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user.id,
                    user.email,
                    user.password_hash,
                    user.display_name,
                    user.dob,
                    user.country,
                    user.created_at,
                    int(user.is_deleted),
                    user.failed_login_attempts,
                    user.locked_until,
                    user.current_room_id,
                ),
            )
            self._conn.commit()
        return user

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _row_to_user(row) if row else None

    def update_user(self, user: User) -> User:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET email=?, password_hash=?, display_name=?, dob=?, country=?,"
                " is_deleted=?, failed_login_attempts=?, locked_until=?, current_room_id=?"
                " WHERE id=?",
                (
                    user.email,
                    user.password_hash,
                    user.display_name,
                    user.dob,
                    user.country,
                    int(user.is_deleted),
                    user.failed_login_attempts,
                    user.locked_until,
                    user.current_room_id,
                    user.id,
                ),
            )
            self._conn.commit()
        return user

    # -- rooms -------------------------------------------------------------

    def create_room(self, room: Room) -> Room:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rooms (id, capacity, state, created_at, player_ids)"
                " VALUES (?, ?, ?, ?, ?)",
                (room.id, room.capacity, room.state, room.created_at, json.dumps(room.player_ids)),
            )
            self._conn.commit()
        return room

    def get_room(self, room_id: str) -> Room | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        return _row_to_room(row) if row else None

    def list_rooms(self, *, capacity: int | None = None, state: str | None = None) -> list[Room]:
        query = "SELECT * FROM rooms WHERE 1=1"
        params: list = []
        if capacity is not None:
            query += " AND capacity = ?"
            params.append(capacity)
        if state is not None:
            query += " AND state = ?"
            params.append(state)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_room(r) for r in rows]

    def update_room(self, room: Room) -> Room:
        with self._lock:
            self._conn.execute(
                "UPDATE rooms SET capacity=?, state=?, player_ids=? WHERE id=?",
                (room.capacity, room.state, json.dumps(room.player_ids), room.id),
            )
            self._conn.commit()
        return room

    # -- tournaments -------------------------------------------------------

    def create_tournament(self, tournament: Tournament) -> Tournament:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tournaments (id, room_id, capacity, status, bracket,"
                " winner_user_id, prize_usd_est, created_at, finished_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tournament.id,
                    tournament.room_id,
                    tournament.capacity,
                    tournament.status,
                    json.dumps(tournament.bracket),
                    tournament.winner_user_id,
                    tournament.prize_usd_est,
                    tournament.created_at,
                    tournament.finished_at,
                ),
            )
            self._conn.commit()
        return tournament

    def get_tournament(self, tournament_id: str) -> Tournament | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tournaments WHERE id = ?", (tournament_id,)
            ).fetchone()
        return _row_to_tournament(row) if row else None

    def list_tournaments(self, *, status: str | None = None) -> list[Tournament]:
        query = "SELECT * FROM tournaments WHERE 1=1"
        params: list = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_tournament(r) for r in rows]

    def update_tournament(self, tournament: Tournament) -> Tournament:
        with self._lock:
            self._conn.execute(
                "UPDATE tournaments SET status=?, bracket=?, winner_user_id=?, prize_usd_est=?,"
                " finished_at=? WHERE id=?",
                (
                    tournament.status,
                    json.dumps(tournament.bracket),
                    tournament.winner_user_id,
                    tournament.prize_usd_est,
                    tournament.finished_at,
                    tournament.id,
                ),
            )
            self._conn.commit()
        return tournament

    # -- matches -------------------------------------------------------

    def create_match(self, match: Match) -> Match:
        with self._lock:
            self._conn.execute(
                "INSERT INTO matches (id, tournament_id, round_number, player_white_id,"
                " player_black_id, status, winner_id, game_state, bracket_slot)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    match.id,
                    match.tournament_id,
                    match.round_number,
                    match.player_white_id,
                    match.player_black_id,
                    match.status,
                    match.winner_id,
                    json.dumps(match.game_state) if match.game_state is not None else None,
                    match.bracket_slot,
                ),
            )
            self._conn.commit()
        return match

    def get_match(self, match_id: str) -> Match | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return _row_to_match(row) if row else None

    def update_match(self, match: Match) -> Match:
        with self._lock:
            self._conn.execute(
                "UPDATE matches SET status=?, winner_id=?, game_state=? WHERE id=?",
                (
                    match.status,
                    match.winner_id,
                    json.dumps(match.game_state) if match.game_state is not None else None,
                    match.id,
                ),
            )
            self._conn.commit()
        return match

    def list_matches(self, tournament_id: str) -> list[Match]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM matches WHERE tournament_id = ?", (tournament_id,)
            ).fetchall()
        return [_row_to_match(r) for r in rows]

    # -- game moves --------------------------------------------------------

    def append_game_move(self, move: GameMove) -> GameMove:
        with self._lock:
            self._conn.execute(
                "INSERT INTO game_moves (id, match_id, seq_index, move, roll_index, ts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    move.id,
                    move.match_id,
                    move.seq_index,
                    json.dumps(move.move),
                    move.roll_index,
                    move.ts,
                ),
            )
            self._conn.commit()
        return move

    def list_game_moves(self, match_id: str) -> list[GameMove]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM game_moves WHERE match_id = ? ORDER BY seq_index",
                (match_id,),
            ).fetchall()
        return [
            GameMove(
                id=r["id"],
                match_id=r["match_id"],
                seq_index=r["seq_index"],
                move=json.loads(r["move"]),
                roll_index=r["roll_index"],
                ts=r["ts"],
            )
            for r in rows
        ]

    # -- ledger --------------------------------------------------------

    def append_ledger_entry(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ledger (id, user_id, entry_type, amount_usd, tournament_id,"
                " created_at, meta) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.user_id,
                    entry.entry_type,
                    entry.amount_usd,
                    entry.tournament_id,
                    entry.created_at,
                    json.dumps(entry.meta),
                ),
            )
            self._conn.commit()
        return entry

    def list_ledger_entries(self, user_id: str) -> list[LedgerEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ledger WHERE user_id = ? ORDER BY created_at", (user_id,)
            ).fetchall()
        return [
            LedgerEntry(
                id=r["id"],
                user_id=r["user_id"],
                entry_type=r["entry_type"],
                amount_usd=r["amount_usd"],
                tournament_id=r["tournament_id"],
                created_at=r["created_at"],
                meta=json.loads(r["meta"]),
            )
            for r in rows
        ]

    # -- ad impressions ------------------------------------------------

    def append_ad_impression(self, impression: AdImpression) -> AdImpression:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ad_impressions (id, user_id, tournament_id, match_id, network,"
                " format, est_revenue_usd, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    impression.id,
                    impression.user_id,
                    impression.tournament_id,
                    impression.match_id,
                    impression.network,
                    impression.format,
                    impression.est_revenue_usd,
                    impression.ts,
                ),
            )
            self._conn.commit()
        return impression

    def list_ad_impressions(self, tournament_id: str) -> list[AdImpression]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ad_impressions WHERE tournament_id = ?", (tournament_id,)
            ).fetchall()
        return [
            AdImpression(
                id=r["id"],
                user_id=r["user_id"],
                tournament_id=r["tournament_id"],
                match_id=r["match_id"],
                network=r["network"],
                format=r["format"],
                est_revenue_usd=r["est_revenue_usd"],
                ts=r["ts"],
            )
            for r in rows
        ]


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        dob=row["dob"],
        country=row["country"],
        created_at=row["created_at"],
        is_deleted=bool(row["is_deleted"]),
        failed_login_attempts=row["failed_login_attempts"],
        locked_until=row["locked_until"],
        current_room_id=row["current_room_id"],
    )


def _row_to_room(row: sqlite3.Row) -> Room:
    return Room(
        id=row["id"],
        capacity=row["capacity"],
        state=row["state"],
        created_at=row["created_at"],
        player_ids=json.loads(row["player_ids"]),
    )


def _row_to_tournament(row: sqlite3.Row) -> Tournament:
    return Tournament(
        id=row["id"],
        room_id=row["room_id"],
        capacity=row["capacity"],
        status=row["status"],
        bracket=json.loads(row["bracket"]),
        winner_user_id=row["winner_user_id"],
        prize_usd_est=row["prize_usd_est"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )


def _row_to_match(row: sqlite3.Row) -> Match:
    return Match(
        id=row["id"],
        tournament_id=row["tournament_id"],
        round_number=row["round_number"],
        player_white_id=row["player_white_id"],
        player_black_id=row["player_black_id"],
        status=row["status"],
        winner_id=row["winner_id"],
        game_state=json.loads(row["game_state"]) if row["game_state"] is not None else None,
        bracket_slot=row["bracket_slot"],
    )
