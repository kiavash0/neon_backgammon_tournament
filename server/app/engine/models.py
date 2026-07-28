from dataclasses import dataclass
from typing import Literal

# Board points are indexed 0-23, representing backgammon points 1-24.
# points[i] > 0  -> that many White checkers on point i+1
# points[i] < 0  -> that many Black checkers on point i+1
# White bears off past point 1 (index 0); Black bears off past point 24 (index 23).
WHITE = 1
BLACK = -1

Color = Literal[1, -1]

BAR: Literal["bar"] = "bar"
OFF: Literal["off"] = "off"


class Move(tuple):
    """A single atomic checker move: (frm, to, die).

    frm is an int point index (0-23) or the literal "bar".
    to is an int point index (0-23) or the literal "off".
    """

    def __new__(cls, frm, to, die):
        return super().__new__(cls, (frm, to, die))

    @property
    def frm(self):
        return self[0]

    @property
    def to(self):
        return self[1]

    @property
    def die(self):
        return self[2]


MoveSequence = tuple[Move, ...]


@dataclass(frozen=True)
class GameState:
    points: tuple[int, ...]  # length 24
    bar_white: int
    bar_black: int
    off_white: int
    off_black: int
    turn: Color

    def to_dict(self) -> dict:
        return {
            "points": list(self.points),
            "bar_white": self.bar_white,
            "bar_black": self.bar_black,
            "off_white": self.off_white,
            "off_black": self.off_black,
            "turn": self.turn,
        }


class IllegalMove(Exception):
    """Raised when apply_move is given a move that is not legal in the given state."""
