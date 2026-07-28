"""Pure, deterministic backgammon rules engine. No I/O, no networking.

Given a GameState and dice, this module answers move legality and produces
the next state. See docs spec §4 for the full rules this implements.
"""

import secrets
from collections.abc import Callable
from dataclasses import replace

from app.engine.models import BLACK, OFF, WHITE, Color, GameState, IllegalMove, Move, MoveSequence

NUM_POINTS = 24
CHECKERS_PER_PLAYER = 15

_WHITE_HOME = range(0, 6)
_BLACK_HOME = range(18, 24)


def initial_state() -> GameState:
    points = [0] * NUM_POINTS
    points[23] = 2 * WHITE
    points[12] = 5 * WHITE
    points[7] = 3 * WHITE
    points[5] = 5 * WHITE
    points[0] = 2 * BLACK
    points[11] = 5 * BLACK
    points[16] = 3 * BLACK
    points[18] = 5 * BLACK
    return GameState(
        points=tuple(points),
        bar_white=0,
        bar_black=0,
        off_white=0,
        off_black=0,
        turn=WHITE,
    )


def _default_die() -> int:
    return secrets.randbelow(6) + 1


def roll_dice(rng: Callable[[], int] | None = None) -> tuple[int, int]:
    """Roll two dice. `rng`, if given, is a zero-arg callable returning 1-6
    (inject a deterministic fake for tests). Defaults to a CSPRNG source.
    """
    roll = rng if rng is not None else _default_die
    return (roll(), roll())


def is_terminal(state: GameState) -> Color | None:
    if state.off_white == CHECKERS_PER_PLAYER:
        return WHITE
    if state.off_black == CHECKERS_PER_PLAYER:
        return BLACK
    return None


def _home_range(color: Color) -> range:
    return _WHITE_HOME if color == WHITE else _BLACK_HOME


def _bar_count(state: GameState, color: Color) -> int:
    return state.bar_white if color == WHITE else state.bar_black


def _entry_index(color: Color, die: int) -> int:
    return 24 - die if color == WHITE else die - 1


def _pip(color: Color, idx: int) -> int:
    return idx + 1 if color == WHITE else 24 - idx


def _all_in_home(state: GameState, color: Color) -> bool:
    home = _home_range(color)
    for idx in range(NUM_POINTS):
        if idx in home:
            continue
        if state.points[idx] * color > 0:
            return False
    return True


def _is_farthest(state: GameState, color: Color, idx: int) -> bool:
    my_pip = _pip(color, idx)
    for other in _home_range(color):
        if state.points[other] * color > 0 and _pip(color, other) > my_pip:
            return False
    return True


def _blocked(state: GameState, color: Color, idx: int) -> bool:
    val = state.points[idx]
    return val * color < 0 and abs(val) >= 2


def single_die_moves(state: GameState, color: Color, die: int) -> list[Move]:
    """All legal atomic moves for `color` using a single `die`, given the
    current state (ignores any other dice remaining in the turn)."""
    moves: list[Move] = []

    if _bar_count(state, color) > 0:
        entry = _entry_index(color, die)
        if not _blocked(state, color, entry):
            moves.append(Move("bar", entry, die))
        return moves

    direction = -1 if color == WHITE else 1
    can_bear_off = _all_in_home(state, color)

    for idx in range(NUM_POINTS):
        if state.points[idx] * color <= 0:
            continue
        target = idx + direction * die
        if 0 <= target < NUM_POINTS:
            if not _blocked(state, color, target):
                moves.append(Move(idx, target, die))
        elif can_bear_off:
            pip = _pip(color, idx)
            if pip == die:
                moves.append(Move(idx, OFF, die))
            elif pip < die and _is_farthest(state, color, idx):
                moves.append(Move(idx, OFF, die))

    return moves


def _apply_atomic(state: GameState, color: Color, move: Move) -> GameState:
    frm, to, _die = move
    points = list(state.points)
    bar_white, bar_black = state.bar_white, state.bar_black
    off_white, off_black = state.off_white, state.off_black

    if frm == "bar":
        if color == WHITE:
            bar_white -= 1
        else:
            bar_black -= 1
    else:
        points[frm] -= color

    if to == OFF:
        if color == WHITE:
            off_white += 1
        else:
            off_black += 1
    else:
        if points[to] * color < 0:
            if color == WHITE:
                bar_black += 1
            else:
                bar_white += 1
            points[to] = 0
        points[to] += color

    return replace(
        state,
        points=tuple(points),
        bar_white=bar_white,
        bar_black=bar_black,
        off_white=off_white,
        off_black=off_black,
    )


def _search(state: GameState, color: Color, dice_remaining: tuple[int, ...]) -> list[MoveSequence]:
    if not dice_remaining:
        return [()]

    results: list[MoveSequence] = []
    seen_dice: set[int] = set()

    for i, die in enumerate(dice_remaining):
        if die in seen_dice:
            continue
        seen_dice.add(die)

        rest = dice_remaining[:i] + dice_remaining[i + 1 :]
        for mv in single_die_moves(state, color, die):
            next_state = _apply_atomic(state, color, mv)
            for continuation in _search(next_state, color, rest):
                results.append((mv, *continuation))

    return results if results else [()]


def legal_moves(state: GameState, dice: tuple[int, int]) -> list[MoveSequence]:
    """All legal full-turn move sequences for the dice, respecting the
    forced-move rules (must play both dice if possible; if only one die is
    playable alone, the higher must be chosen when it's an option)."""
    color = state.turn
    d1, d2 = dice
    dice_multiset = (d1, d1, d1, d1) if d1 == d2 else (d1, d2)

    all_sequences = _search(state, color, dice_multiset)
    max_len = max(len(seq) for seq in all_sequences)
    candidates = [seq for seq in all_sequences if len(seq) == max_len]

    if max_len == 1 and d1 != d2:
        higher = max(d1, d2)
        higher_only = [seq for seq in candidates if seq[0].die == higher]
        if higher_only:
            candidates = higher_only

    return list(dict.fromkeys(candidates))


def apply_move(state: GameState, move: MoveSequence) -> GameState:
    """Apply a full turn (a MoveSequence, possibly empty for a forced skip),
    validating every atomic step, and return the resulting state with the
    turn passed to the opponent. Raises IllegalMove on any invalid step."""
    color = state.turn
    current = state

    for mv in move:
        legal = single_die_moves(current, color, mv[2])
        if mv not in legal:
            raise IllegalMove(f"{mv!r} is not a legal move in the current state")
        current = _apply_atomic(current, color, mv)

    return replace(current, turn=-color)
