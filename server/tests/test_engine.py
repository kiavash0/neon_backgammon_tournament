from dataclasses import replace

import pytest

from app.engine.engine import (
    apply_move,
    initial_state,
    is_terminal,
    legal_moves,
    roll_dice,
    single_die_moves,
)
from app.engine.models import BLACK, WHITE, GameState, IllegalMove, Move

EMPTY = tuple([0] * 24)


def empty_state(turn=WHITE, **overrides) -> GameState:
    base = dict(points=EMPTY, bar_white=0, bar_black=0, off_white=0, off_black=0, turn=turn)
    base.update(overrides)
    return GameState(**base)


# --- initial_state -----------------------------------------------------


def test_initial_state_checker_counts():
    state = initial_state()
    assert sum(v for v in state.points if v > 0) == 15
    assert sum(-v for v in state.points if v < 0) == 15
    assert state.bar_white == state.bar_black == 0
    assert state.off_white == state.off_black == 0
    assert state.turn == WHITE


def test_initial_state_standard_layout():
    state = initial_state()
    assert state.points[23] == 2
    assert state.points[12] == 5
    assert state.points[7] == 3
    assert state.points[5] == 5
    assert state.points[0] == -2
    assert state.points[11] == -5
    assert state.points[16] == -3
    assert state.points[18] == -5


# --- roll_dice -----------------------------------------------------------


def test_roll_dice_default_range():
    for _ in range(50):
        d1, d2 = roll_dice()
        assert 1 <= d1 <= 6
        assert 1 <= d2 <= 6


def test_roll_dice_injected_rng_is_deterministic():
    values = iter([3, 5])
    d1, d2 = roll_dice(lambda: next(values))
    assert (d1, d2) == (3, 5)


# --- basic movement --------------------------------------------------------


def test_simple_move_is_legal_and_applies():
    state = initial_state()
    moves = single_die_moves(state, WHITE, 3)
    assert Move(23, 20, 3) in moves
    new_state = apply_move(state, (Move(23, 20, 3),))
    assert new_state.points[23] == 1
    assert new_state.points[20] == 1
    assert new_state.turn == BLACK


def test_blocked_point_cannot_be_landed_on():
    # Black has 5 checkers on index 18; White cannot land there.
    state = initial_state()
    moves = single_die_moves(state, WHITE, 5)
    assert all(m.to != 18 for m in moves)


def test_hitting_a_blot_sends_it_to_the_bar():
    state = empty_state(points=tuple(
        [1 if i == 10 else (-1 if i == 7 else 0) for i in range(24)]
    ))
    move = Move(10, 7, 3)
    assert move in single_die_moves(state, WHITE, 3)
    new_state = apply_move(state, (move,))
    assert new_state.points[7] == 1
    assert new_state.bar_black == 1


def test_illegal_move_raises():
    state = initial_state()
    with pytest.raises(IllegalMove):
        apply_move(state, (Move(23, 0, 3),))  # not a real single-die move (23->0 needs die 23)


# --- bar entry ---------------------------------------------------------


def test_must_enter_from_bar_before_other_moves():
    points = list(EMPTY)
    points[7] = 3  # a spare white checker elsewhere
    state = empty_state(points=tuple(points), bar_white=1)
    moves = single_die_moves(state, WHITE, 4)
    assert moves == [Move("bar", 20, 4)]


def test_bar_entry_blocked_by_two_or_more_opponents():
    points = list(EMPTY)
    points[20] = -2  # blocks White's die-4 entry point (24-4=20)
    state = empty_state(points=tuple(points), bar_white=1)
    moves = single_die_moves(state, WHITE, 4)
    assert moves == []


def test_bar_entry_hits_blot():
    points = list(EMPTY)
    points[20] = -1
    state = empty_state(points=tuple(points), bar_white=1)
    move = Move("bar", 20, 4)
    new_state = apply_move(state, (move,))
    assert new_state.points[20] == 1
    assert new_state.bar_black == 1
    assert new_state.bar_white == 0


# --- bearing off ---------------------------------------------------------


def test_bear_off_exact_roll():
    points = list(EMPTY)
    points[2] = 1  # point 3, pip == 3
    state = empty_state(points=tuple(points))
    move = Move(2, "off", 3)
    assert move in single_die_moves(state, WHITE, 3)
    new_state = apply_move(state, (move,))
    assert new_state.off_white == 1
    assert new_state.points[2] == 0


def test_cannot_bear_off_with_checkers_outside_home():
    points = list(EMPTY)
    points[2] = 1
    points[10] = 1  # outside home board
    state = empty_state(points=tuple(points))
    moves = single_die_moves(state, WHITE, 3)
    assert Move(2, "off", 3) not in moves


def test_bear_off_overshoot_allowed_only_from_farthest_point():
    # White has one checker on point 5 (idx 4, pip 5) and one on point 2 (idx 1, pip 2).
    # A roll of 6 can only bear off the farthest checker (point 5), not point 2.
    points = list(EMPTY)
    points[4] = 1
    points[1] = 1
    state = empty_state(points=tuple(points))
    moves = single_die_moves(state, WHITE, 6)
    assert Move(4, "off", 6) in moves
    assert Move(1, "off", 6) not in moves


def test_bear_off_overshoot_blocked_when_farther_checker_exists():
    points = list(EMPTY)
    points[4] = 1  # point 5, pip 5 (farthest)
    points[1] = 1  # point 2, pip 2
    state = empty_state(points=tuple(points))
    moves = single_die_moves(state, WHITE, 6)
    assert Move(4, "off", 6) in moves  # farthest checker may use the overshoot
    assert Move(1, "off", 6) not in moves  # nearer checker may not, while idx4 is occupied


# --- forced-move rules -----------------------------------------------------


def test_both_dice_played_when_possible():
    state = initial_state()
    sequences = legal_moves(state, (3, 5))
    assert all(len(seq) == 2 for seq in sequences)


def test_doubles_play_four_moves_when_possible():
    state = initial_state()
    sequences = legal_moves(state, (2, 2))
    assert max(len(seq) for seq in sequences) == 4


def test_forced_higher_die_when_only_one_playable_alone():
    # White has a single checker on point 21 (idx 20). die 3 -> idx17 is legal alone;
    # die 5 -> idx15 is legal alone. Chaining either order lands on idx12, which is
    # blocked, so only one die can ever be played this turn. The forced-move rule
    # requires the higher die (5) be chosen.
    points = list(EMPTY)
    points[20] = 1
    points[12] = -2  # blocks the only square either chain order would land on
    state = empty_state(points=tuple(points))

    sequences = legal_moves(state, (3, 5))

    assert max(len(seq) for seq in sequences) == 1
    assert sequences == [(Move(20, 15, 5),)]


def test_no_legal_move_returns_skip_sequence():
    points = list(EMPTY)
    points[10] = 1  # white checker outside home, both die targets blocked
    points[9] = -2  # blocks die 1 (10 -> 9)
    points[8] = -2  # blocks die 2 (10 -> 8)
    state = empty_state(points=tuple(points))
    sequences = legal_moves(state, (1, 2))
    assert sequences == [()]
    new_state = apply_move(state, ())
    assert new_state.turn == BLACK
    assert new_state.points == state.points


# --- terminal state / winning -------------------------------------------


def test_is_terminal_none_mid_game():
    assert is_terminal(initial_state()) is None


def test_is_terminal_white_wins():
    state = empty_state(off_white=15)
    assert is_terminal(state) == WHITE


def test_is_terminal_black_wins():
    state = empty_state(off_black=15)
    assert is_terminal(state) == BLACK


# --- black-side symmetry ---------------------------------------------------


def test_black_moves_toward_increasing_index():
    points = list(EMPTY)
    points[3] = -1
    state = empty_state(points=tuple(points), turn=BLACK)
    moves = single_die_moves(state, BLACK, 4)
    assert Move(3, 7, 4) in moves


def test_black_bears_off_from_own_home():
    points = list(EMPTY)
    points[21] = -1  # point 22, black pip = 24-21 = 3
    state = empty_state(points=tuple(points), turn=BLACK)
    move = Move(21, "off", 3)
    assert move in single_die_moves(state, BLACK, 3)
    new_state = apply_move(state, (move,))
    assert new_state.off_black == 1


def test_black_bar_entry_index():
    points = list(EMPTY)
    state = empty_state(points=tuple(points), turn=BLACK, bar_black=1)
    moves = single_die_moves(state, BLACK, 4)
    assert moves == [Move("bar", 3, 4)]


# --- full game smoke test (via CLI's engine calls) --------------------------


def test_full_random_self_play_terminates():
    import random

    state = initial_state()
    rng = random.Random(42)
    turns = 0
    while is_terminal(state) is None and turns < 3000:
        dice = roll_dice(lambda: rng.randint(1, 6))
        sequences = legal_moves(state, dice)
        move = rng.choice(sequences)
        state = apply_move(state, move)
        turns += 1
    assert is_terminal(state) is not None
    winner = is_terminal(state)
    if winner == WHITE:
        assert state.off_white == 15
    else:
        assert state.off_black == 15


def test_game_state_to_dict_is_json_shaped():
    state = initial_state()
    d = state.to_dict()
    assert d["turn"] == WHITE
    assert len(d["points"]) == 24
    assert isinstance(d["points"], list)


def test_apply_move_rejects_move_not_matching_available_dice_value():
    state = initial_state()
    with pytest.raises(IllegalMove):
        # die value 4 was never rolled/legal from this exact origin in this shape
        apply_move(state, (Move(23, 22, 1), Move(22, 16, 4)))


def test_replace_helper_used_for_turn_toggle_only():
    state = initial_state()
    result = apply_move(state, ())
    assert result == replace(state, turn=BLACK)
