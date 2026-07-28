import pytest

from app.storage.base import (
    AdImpression,
    GameMove,
    LedgerEntry,
    Match,
    Room,
    Tournament,
    User,
)
from app.storage.factory import get_storage_backend
from app.storage.h5_backend import H5Backend
from app.storage.sqlite_backend import SqliteBackend


@pytest.fixture(params=["sqlite", "h5"])
def backend(request):
    b = get_storage_backend(backend=request.param, path=":memory:")
    yield b
    b.close()


def make_user(uid="u1", email="a@example.com") -> User:
    return User(
        id=uid,
        email=email,
        password_hash="hash",
        display_name="Ada",
        dob="2000-01-01",
        country="IE",
        created_at="2026-07-28T00:00:00Z",
    )


# -- factory -----------------------------------------------------------


def test_factory_selects_sqlite_backend():
    b = get_storage_backend(backend="sqlite", path=":memory:")
    assert isinstance(b, SqliteBackend)
    b.close()


def test_factory_selects_h5_backend():
    b = get_storage_backend(backend="h5", path=":memory:")
    assert isinstance(b, H5Backend)
    b.close()


def test_factory_reads_env_vars(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "h5")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    b = get_storage_backend()
    assert isinstance(b, H5Backend)
    b.close()


def test_factory_rejects_unknown_backend():
    with pytest.raises(ValueError):
        get_storage_backend(backend="mongo")


# -- users -----------------------------------------------------------


def test_create_and_get_user(backend):
    user = backend.create_user(make_user())
    fetched = backend.get_user(user.id)
    assert fetched == user


def test_get_user_missing_returns_none(backend):
    assert backend.get_user("nope") is None


def test_get_user_by_email(backend):
    backend.create_user(make_user())
    assert backend.get_user_by_email("a@example.com").id == "u1"
    assert backend.get_user_by_email("missing@example.com") is None


def test_update_user(backend):
    user = backend.create_user(make_user())
    user.display_name = "Ada Lovelace"
    user.is_deleted = True
    backend.update_user(user)
    fetched = backend.get_user(user.id)
    assert fetched.display_name == "Ada Lovelace"
    assert fetched.is_deleted is True


# -- rooms -------------------------------------------------------------


def test_create_get_update_room(backend):
    room = backend.create_room(Room(id="r1", capacity=2, state="OPEN", created_at="t"))
    assert backend.get_room("r1") == room
    room.state = "FULL"
    room.player_ids = ["u1", "u2"]
    backend.update_room(room)
    assert backend.get_room("r1").state == "FULL"
    assert backend.get_room("r1").player_ids == ["u1", "u2"]


def test_list_rooms_filters_by_capacity_and_state(backend):
    backend.create_room(Room(id="r1", capacity=2, state="OPEN", created_at="t"))
    backend.create_room(Room(id="r2", capacity=4, state="OPEN", created_at="t"))
    backend.create_room(Room(id="r3", capacity=2, state="FULL", created_at="t"))

    assert {r.id for r in backend.list_rooms(capacity=2)} == {"r1", "r3"}
    assert {r.id for r in backend.list_rooms(state="OPEN")} == {"r1", "r2"}
    assert {r.id for r in backend.list_rooms(capacity=2, state="OPEN")} == {"r1"}
    assert len(backend.list_rooms()) == 3


# -- tournaments -------------------------------------------------------


def test_create_get_update_tournament(backend):
    t = backend.create_tournament(
        Tournament(id="t1", room_id="r1", capacity=2, status="RUNNING", created_at="t")
    )
    assert backend.get_tournament("t1") == t
    t.status = "FINISHED"
    t.winner_user_id = "u1"
    t.prize_usd_est = 0.5
    t.bracket = {"rounds": [["u1", "u2"]]}
    backend.update_tournament(t)
    fetched = backend.get_tournament("t1")
    assert fetched.status == "FINISHED"
    assert fetched.winner_user_id == "u1"
    assert fetched.prize_usd_est == 0.5
    assert fetched.bracket == {"rounds": [["u1", "u2"]]}


# -- matches -------------------------------------------------------


def test_create_get_update_list_matches(backend):
    backend.create_match(
        Match(id="m1", tournament_id="t1", round_number=1,
              player_white_id="u1", player_black_id="u2")
    )
    backend.create_match(
        Match(id="m2", tournament_id="t1", round_number=1,
              player_white_id="u3", player_black_id="u4")
    )
    backend.create_match(
        Match(id="m3", tournament_id="other", round_number=1,
              player_white_id="u5", player_black_id="u6")
    )

    assert {m.id for m in backend.list_matches("t1")} == {"m1", "m2"}

    m1 = backend.get_match("m1")
    m1.status = "FINISHED"
    m1.winner_id = "u1"
    m1.game_state = {"points": [0] * 24, "turn": 1}
    backend.update_match(m1)

    fetched = backend.get_match("m1")
    assert fetched.status == "FINISHED"
    assert fetched.winner_id == "u1"
    assert fetched.game_state == {"points": [0] * 24, "turn": 1}


# -- game move log -----------------------------------------------------


def test_append_and_list_game_moves_ordered(backend):
    backend.append_game_move(
        GameMove(id="gm2", match_id="m1", seq_index=1, move=[[0, 1, 3]], roll_index=1, ts="t2")
    )
    backend.append_game_move(
        GameMove(id="gm1", match_id="m1", seq_index=0, move=[[23, 20, 3]], roll_index=0, ts="t1")
    )
    backend.append_game_move(
        GameMove(id="gm3", match_id="other", seq_index=0, move=[], roll_index=0, ts="t0")
    )

    moves = backend.list_game_moves("m1")
    assert [m.id for m in moves] == ["gm1", "gm2"]
    assert moves[0].move == [[23, 20, 3]]


# -- ledger (append-only, balance invariant) ----------------------------


def test_ledger_append_only_and_balance(backend):
    backend.append_ledger_entry(
        LedgerEntry(id="l1", user_id="u1", entry_type="credit", amount_usd=0.5,
                    tournament_id="t1", created_at="t1")
    )
    backend.append_ledger_entry(
        LedgerEntry(id="l2", user_id="u1", entry_type="debit", amount_usd=-0.2,
                    tournament_id=None, created_at="t2")
    )
    backend.append_ledger_entry(
        LedgerEntry(id="l3", user_id="other", entry_type="credit", amount_usd=99,
                    tournament_id=None, created_at="t1")
    )

    entries = backend.list_ledger_entries("u1")
    assert [e.id for e in entries] == ["l1", "l2"]
    assert backend.get_balance("u1") == pytest.approx(0.3)


def test_ledger_balance_zero_for_unknown_user(backend):
    assert backend.get_balance("ghost") == 0


# -- ad impressions ------------------------------------------------


def test_append_and_list_ad_impressions(backend):
    backend.append_ad_impression(
        AdImpression(id="a1", user_id="u1", tournament_id="t1", match_id="m1",
                     network="admob", format="interstitial", est_revenue_usd=0.015, ts="t")
    )
    backend.append_ad_impression(
        AdImpression(id="a2", user_id="u2", tournament_id="t1", match_id="m1",
                     network="admob", format="interstitial", est_revenue_usd=0.015, ts="t")
    )
    backend.append_ad_impression(
        AdImpression(id="a3", user_id="u1", tournament_id=None, match_id=None,
                     network="admob", format="banner", est_revenue_usd=0.001, ts="t")
    )

    impressions = backend.list_ad_impressions("t1")
    assert {i.id for i in impressions} == {"a1", "a2"}
    assert sum(i.est_revenue_usd for i in impressions) == pytest.approx(0.03)
