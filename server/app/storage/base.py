"""Storage boundary. Business logic (auth, lobby, tournaments, ledger) talks
only to the `StorageBackend` interface below, never to SQLite or h5py
directly, so the backend can be swapped via config (SPEC §3, §6.1).

Entities are plain dataclasses so both backends can serialize them the same
way (JSON for h5py values, columns for SQLite).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    display_name: str
    dob: str
    country: str
    created_at: str
    is_deleted: bool = False
    failed_login_attempts: int = 0
    locked_until: str | None = None


@dataclass
class Room:
    id: str
    capacity: int
    state: str  # OPEN | FULL | TOURNAMENT_RUNNING | FINISHED | CANCELLED
    created_at: str
    player_ids: list[str] = field(default_factory=list)


@dataclass
class Tournament:
    id: str
    room_id: str
    capacity: int
    status: str  # RUNNING | FINISHED | CANCELLED
    bracket: dict = field(default_factory=dict)
    winner_user_id: str | None = None
    prize_usd_est: float = 0.0
    created_at: str = ""
    finished_at: str | None = None


@dataclass
class Match:
    id: str
    tournament_id: str
    round_number: int
    player_white_id: str | None
    player_black_id: str | None
    status: str = "PENDING"  # PENDING | RUNNING | FINISHED | FORFEITED
    winner_id: str | None = None
    game_state: dict | None = None


@dataclass
class GameMove:
    id: str
    match_id: str
    seq_index: int
    move: Any
    roll_index: int
    ts: str


@dataclass
class LedgerEntry:
    id: str
    user_id: str
    entry_type: str  # credit | debit | adjustment
    amount_usd: float  # signed: credits positive, debits negative
    tournament_id: str | None
    created_at: str
    meta: dict = field(default_factory=dict)


@dataclass
class AdImpression:
    id: str
    user_id: str | None
    tournament_id: str | None
    match_id: str | None
    network: str
    format: str
    est_revenue_usd: float
    ts: str


class StorageBackend(ABC):
    """CRUD boundary for every persisted entity in the system.

    Synchronous by design in Phase A (demo scale, local SQLite/h5py); Phase B's
    move to PostgreSQL is expected to introduce an async driver behind this
    same interface. See docs/DECISIONS.md.
    """

    # -- users ---------------------------------------------------------
    @abstractmethod
    def create_user(self, user: User) -> User: ...

    @abstractmethod
    def get_user(self, user_id: str) -> User | None: ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    def update_user(self, user: User) -> User: ...

    # -- rooms -----------------------------------------------------------
    @abstractmethod
    def create_room(self, room: Room) -> Room: ...

    @abstractmethod
    def get_room(self, room_id: str) -> Room | None: ...

    @abstractmethod
    def list_rooms(
        self, *, capacity: int | None = None, state: str | None = None
    ) -> list[Room]: ...

    @abstractmethod
    def update_room(self, room: Room) -> Room: ...

    # -- tournaments -------------------------------------------------------
    @abstractmethod
    def create_tournament(self, tournament: Tournament) -> Tournament: ...

    @abstractmethod
    def get_tournament(self, tournament_id: str) -> Tournament | None: ...

    @abstractmethod
    def update_tournament(self, tournament: Tournament) -> Tournament: ...

    # -- matches -------------------------------------------------------
    @abstractmethod
    def create_match(self, match: Match) -> Match: ...

    @abstractmethod
    def get_match(self, match_id: str) -> Match | None: ...

    @abstractmethod
    def update_match(self, match: Match) -> Match: ...

    @abstractmethod
    def list_matches(self, tournament_id: str) -> list[Match]: ...

    # -- game move log ---------------------------------------------------
    @abstractmethod
    def append_game_move(self, move: GameMove) -> GameMove: ...

    @abstractmethod
    def list_game_moves(self, match_id: str) -> list[GameMove]: ...

    # -- ledger (append-only) ---------------------------------------------
    @abstractmethod
    def append_ledger_entry(self, entry: LedgerEntry) -> LedgerEntry: ...

    @abstractmethod
    def list_ledger_entries(self, user_id: str) -> list[LedgerEntry]: ...

    def get_balance(self, user_id: str) -> float:
        return sum(e.amount_usd for e in self.list_ledger_entries(user_id))

    # -- ad impressions (stub) --------------------------------------------
    @abstractmethod
    def append_ad_impression(self, impression: AdImpression) -> AdImpression: ...

    @abstractmethod
    def list_ad_impressions(self, tournament_id: str) -> list[AdImpression]: ...
