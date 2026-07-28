"""Match play business logic: server-authoritative dice + legality via the
pure engine (app.engine), persisted after every applied move so a running
match survives a server restart (SPEC §5.2 crash-recovery requirement).
"""

import uuid
from datetime import UTC, datetime

from app.engine import GameState, apply_move, initial_state, is_terminal, legal_moves, roll_dice
from app.engine.models import BLACK, WHITE, Move
from app.storage.base import GameMove, Match, StorageBackend

PENDING = "PENDING"
RUNNING = "RUNNING"
FINISHED = "FINISHED"


class MatchError(Exception):
    pass


class NotAParticipant(MatchError):
    pass


class NotYourTurn(MatchError):
    pass


class IllegalClientMove(MatchError):
    pass


def color_for_user(match: Match, user_id: str) -> int:
    if user_id == match.player_white_id:
        return WHITE
    if user_id == match.player_black_id:
        return BLACK
    raise NotAParticipant(f"{user_id} is not a participant in match {match.id}")


def opponent_id(match: Match, user_id: str) -> str:
    if user_id == match.player_white_id:
        return match.player_black_id
    if user_id == match.player_black_id:
        return match.player_white_id
    raise NotAParticipant(f"{user_id} is not a participant in match {match.id}")


def state_from_match(match: Match) -> GameState:
    d = match.game_state
    return GameState(
        points=tuple(d["points"]),
        bar_white=d["bar_white"],
        bar_black=d["bar_black"],
        off_white=d["off_white"],
        off_black=d["off_black"],
        turn=d["turn"],
    )


def _persist_state(storage: StorageBackend, match: Match, state: GameState) -> Match:
    match.game_state = state.to_dict()
    return storage.update_match(match)


def start_match(storage: StorageBackend, match: Match) -> tuple[Match, GameState]:
    state = initial_state()
    match.status = RUNNING
    match = _persist_state(storage, match, state)
    return match, state


def moves_from_raw(raw_seq: list) -> tuple:
    return tuple(Move(m[0], m[1], m[2]) for m in raw_seq)


def _log_moves(storage: StorageBackend, match_id: str, seq: tuple, seq_index_start: int,
                roll_index: int, now: datetime) -> None:
    for i, mv in enumerate(seq):
        storage.append_game_move(
            GameMove(
                id=uuid.uuid4().hex,
                match_id=match_id,
                seq_index=seq_index_start + i,
                move=list(mv),
                roll_index=roll_index,
                ts=now.isoformat(),
            )
        )


def apply_client_move(
    storage: StorageBackend,
    match: Match,
    state: GameState,
    dice: tuple[int, int],
    user_id: str,
    raw_seq: list,
    seq_index_start: int,
    roll_index: int,
    now: datetime | None = None,
) -> tuple[Match, GameState, int | None]:
    """Validate a client-submitted move against legal_moves(state, dice) for
    this user's turn, apply it, persist, and log it. Raises a MatchError
    subclass on any invalid input."""
    now = now or datetime.now(UTC)
    color = color_for_user(match, user_id)
    if state.turn != color:
        raise NotYourTurn("it is not your turn")

    candidate = moves_from_raw(raw_seq)
    if candidate not in legal_moves(state, dice):
        raise IllegalClientMove("submitted move is not legal")

    new_state = apply_move(state, candidate)
    match = _persist_state(storage, match, new_state)
    _log_moves(storage, match.id, candidate, seq_index_start, roll_index, now)

    return match, new_state, is_terminal(new_state)


def apply_forced_move(
    storage: StorageBackend,
    match: Match,
    state: GameState,
    candidate: tuple,
    seq_index_start: int,
    roll_index: int,
    now: datetime | None = None,
) -> tuple[Match, GameState, int | None]:
    """Server-issued move (a forced single legal option, or a timeout's
    forfeit-turn skip) — bypasses the client legality membership check
    since the server itself is choosing it."""
    now = now or datetime.now(UTC)
    new_state = apply_move(state, candidate)
    match = _persist_state(storage, match, new_state)
    _log_moves(storage, match.id, candidate, seq_index_start, roll_index, now)
    return match, new_state, is_terminal(new_state)


def finish_match(storage: StorageBackend, match: Match, winner_id: str | None) -> Match:
    match.status = FINISHED
    match.winner_id = winner_id
    return storage.update_match(match)


def roll_for_turn(rng=None) -> tuple[int, int]:
    return roll_dice(rng)
