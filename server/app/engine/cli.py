"""Self-play demo: plays one full random-legal-move game and prints the result.

Not part of the pure engine boundary — this is I/O (stdout) and uses the
engine's public API exactly as a game server would.
"""

import random

from app.engine.engine import apply_move, initial_state, is_terminal, legal_moves, roll_dice

COLOR_NAME = {1: "White", -1: "Black"}


def play_random_game(max_turns: int = 2000) -> None:
    state = initial_state()
    turns = 0

    while is_terminal(state) is None and turns < max_turns:
        dice = roll_dice()
        sequences = legal_moves(state, dice)
        move = random.choice(sequences)
        state = apply_move(state, move)
        turns += 1
        if move:
            print(f"turn {turns}: {COLOR_NAME[-state.turn]} rolled {dice}, played {move}")
        else:
            print(f"turn {turns}: {COLOR_NAME[-state.turn]} rolled {dice}, no legal move (skipped)")

    winner = is_terminal(state)
    if winner is None:
        print(f"No winner after {max_turns} turns (safety cap hit).")
    else:
        print(f"\n{COLOR_NAME[winner]} wins in {turns} turns.")


if __name__ == "__main__":
    play_random_game()
