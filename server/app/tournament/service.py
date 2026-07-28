"""Tournament business logic: bracket persistence, round creation, prize
calculation. Sync and storage-only (no WebSocket I/O) — the async
broadcast/timer glue lives in app.tournament.orchestrator, mirroring the
app.match.service / app.match.ws_handlers split from A6.
"""

import random
import uuid
from datetime import UTC, datetime

from app.storage.base import AdImpression, LedgerEntry, Match, Room, StorageBackend, Tournament
from app.tournament import bracket, config

RUNNING = "RUNNING"
FINISHED = "FINISHED"


def start_tournament(
    storage: StorageBackend,
    room: Room,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> tuple[Tournament, list[Match]]:
    """SPEC §5.2: on room_filled, freeze roster, random-seed, generate the
    bracket, persist, and create round-1 matches."""
    now = now or datetime.now(UTC)
    seeded = bracket.seed_players(room.player_ids, rng=rng)

    tournament = storage.create_tournament(
        Tournament(
            id=uuid.uuid4().hex,
            room_id=room.id,
            capacity=room.capacity,
            status=RUNNING,
            bracket={"seed_order": seeded, "rounds": {}},
            created_at=now.isoformat(),
        )
    )

    matches = create_round(storage, tournament, round_number=1, ordered_ids=seeded)
    tournament.bracket["rounds"]["1"] = [m.id for m in matches]
    tournament = storage.update_tournament(tournament)

    room.state = "TOURNAMENT_RUNNING"
    storage.update_room(room)

    return tournament, matches


def create_round(
    storage: StorageBackend, tournament: Tournament, *, round_number: int, ordered_ids: list[str]
) -> list[Match]:
    matches = []
    for slot, (white_id, black_id) in enumerate(bracket.pair_round(ordered_ids)):
        match = storage.create_match(
            Match(
                id=uuid.uuid4().hex,
                tournament_id=tournament.id,
                round_number=round_number,
                player_white_id=white_id,
                player_black_id=black_id,
                status="PENDING",
                bracket_slot=slot,
            )
        )
        matches.append(match)
    return matches


def round_matches(storage: StorageBackend, tournament_id: str, round_number: int) -> list[Match]:
    matches = [m for m in storage.list_matches(tournament_id) if m.round_number == round_number]
    return sorted(matches, key=lambda m: m.bracket_slot)


def is_round_complete(matches: list[Match]) -> bool:
    return bool(matches) and all(m.status in ("FINISHED", "FORFEITED") for m in matches)


def round_winners(matches: list[Match]) -> list[str]:
    return [m.winner_id for m in sorted(matches, key=lambda m: m.bracket_slot)]


def log_match_impressions(
    storage: StorageBackend, tournament_id: str, match: Match, now: datetime | None = None
) -> None:
    """SPEC §8.2: an interstitial after each match, attributed to the tournament."""
    now = now or datetime.now(UTC)
    for uid in (match.player_white_id, match.player_black_id):
        storage.append_ad_impression(
            AdImpression(
                id=uuid.uuid4().hex,
                user_id=uid,
                tournament_id=tournament_id,
                match_id=match.id,
                network="stub",
                format="interstitial",
                est_revenue_usd=config.stub_impression_revenue_usd(),
                ts=now.isoformat(),
            )
        )


def log_round_advance_impressions(
    storage: StorageBackend,
    tournament_id: str,
    advancing_ids: list[str],
    now: datetime | None = None,
) -> None:
    """SPEC §8.2: an interstitial on the between-round bracket screen."""
    now = now or datetime.now(UTC)
    for uid in advancing_ids:
        storage.append_ad_impression(
            AdImpression(
                id=uuid.uuid4().hex,
                user_id=uid,
                tournament_id=tournament_id,
                match_id=None,
                network="stub",
                format="interstitial",
                est_revenue_usd=config.stub_impression_revenue_usd(),
                ts=now.isoformat(),
            )
        )


def finish_tournament(
    storage: StorageBackend, tournament: Tournament, winner_id: str, now: datetime | None = None
) -> Tournament:
    """SPEC §5.3: prize pool = payout_rate x attributed ad revenue; credit
    the winner's ledger. Handles zero-revenue gracefully (prize = $0)."""
    now = now or datetime.now(UTC)
    impressions = storage.list_ad_impressions(tournament.id)
    total_revenue = sum(i.est_revenue_usd for i in impressions)
    prize = round(config.payout_rate() * total_revenue, 6)

    tournament.status = FINISHED
    tournament.winner_user_id = winner_id
    tournament.prize_usd_est = prize
    tournament.finished_at = now.isoformat()
    tournament = storage.update_tournament(tournament)

    storage.append_ledger_entry(
        LedgerEntry(
            id=uuid.uuid4().hex,
            user_id=winner_id,
            entry_type="credit",
            amount_usd=prize,
            tournament_id=tournament.id,
            created_at=now.isoformat(),
            meta={"estimated": True, "source": "tournament_prize", "provider": "demo"},
        )
    )

    room = storage.get_room(tournament.room_id)
    if room is not None:
        room.state = "FINISHED"
        storage.update_room(room)

    return tournament
