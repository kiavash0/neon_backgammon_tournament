from app.engine.cli import play_random_game
from app.engine.models import Move


def test_play_random_game_completes_and_prints(capsys):
    play_random_game(max_turns=3000)
    out = capsys.readouterr().out
    assert "wins in" in out


def test_move_accessors():
    move = Move(3, 7, 4)
    assert move.frm == 3
    assert move.to == 7
    assert move.die == 4
