"""Async glue around app.tournament.service: WS broadcasts, the round-1
get-ready countdown, per-match join timeouts, and startup crash recovery
(SPEC §5.2: "any worker can advance any tournament" / resume from
persisted state on restart).
"""

import asyncio
import secrets

from fastapi import FastAPI

from app.storage.base import Match, Room, Tournament
from app.tournament import config, service


async def _send(app: FastAPI, user_id: str, message: dict) -> None:
    await app.state.connections.send(user_id, message)


async def _broadcast_bracket(app: FastAPI, tournament: Tournament) -> None:
    await app.state.tournament_connections.broadcast(
        tournament.id,
        {
            "type": "bracket_update",
            "tid": tournament.id,
            "status": tournament.status,
            "bracket": tournament.bracket,
        },
    )


async def start_tournament(app: FastAPI, room: Room) -> Tournament:
    storage = app.state.storage
    tournament, round1 = service.start_tournament(storage, room)

    for uid in room.player_ids:
        await _send(
            app,
            uid,
            {
                "type": "tournament_start",
                "tid": tournament.id,
                "capacity": room.capacity,
                "get_ready_seconds": config.get_ready_seconds(),
            },
        )
    await _broadcast_bracket(app, tournament)

    asyncio.create_task(_begin_round_after_get_ready(app, tournament.id, round1))
    return tournament


async def _begin_round_after_get_ready(
    app: FastAPI, tournament_id: str, matches: list[Match]
) -> None:
    try:
        await asyncio.sleep(config.get_ready_seconds())
    except asyncio.CancelledError:
        return
    await _announce_round(app, tournament_id, matches)


async def _announce_round(app: FastAPI, tournament_id: str, matches: list[Match]) -> None:
    for match in matches:
        for uid in (match.player_white_id, match.player_black_id):
            await _send(
                app,
                uid,
                {
                    "type": "round_start",
                    "tid": tournament_id,
                    "mid": match.id,
                    "round": match.round_number,
                },
            )
        asyncio.create_task(_match_join_timeout_watcher(app, match.id))


async def _match_join_timeout_watcher(app: FastAPI, match_id: str) -> None:
    try:
        await asyncio.sleep(config.match_join_timeout_seconds())
    except asyncio.CancelledError:
        return

    storage = app.state.storage
    match = storage.get_match(match_id)
    if match is None or match.status != "PENDING":
        return  # already started (or otherwise resolved) in the meantime

    runtime = app.state.match_runtimes.get(match_id)
    ready = runtime.ready if runtime is not None else set()
    white_ready = match.player_white_id in ready
    black_ready = match.player_black_id in ready

    if white_ready and not black_ready:
        winner_id = match.player_white_id
    elif black_ready and not white_ready:
        winner_id = match.player_black_id
    else:
        winner_id = secrets.choice([match.player_white_id, match.player_black_id])

    match.status = "FORFEITED"
    match.winner_id = winner_id
    match = storage.update_match(match)

    for uid in (match.player_white_id, match.player_black_id):
        await _send(
            app,
            uid,
            {
                "type": "match_result",
                "mid": match_id,
                "winner_user_id": winner_id,
                "reason": "forfeit_no_show",
            },
        )
    await handle_match_finished(app, match)


async def handle_match_finished(app: FastAPI, match: Match) -> None:
    """Called by app.match.ws_handlers after ANY match concludes (bear-off,
    resign, timeout forfeit, disconnect forfeit) as well as by the
    no-show join-timeout watcher above."""
    storage = app.state.storage
    tournament = storage.get_tournament(match.tournament_id)
    if tournament is None:
        return  # not a tournament match (e.g. an ad-hoc match created directly in tests)

    loser_id = (
        match.player_black_id if match.winner_id == match.player_white_id else match.player_white_id
    )
    loser = storage.get_user(loser_id)
    if loser is not None:
        loser.current_room_id = None
        storage.update_user(loser)

    service.log_match_impressions(storage, tournament.id, match)
    await _broadcast_bracket(app, tournament)

    await _advance_round_if_complete(app, tournament, match.round_number)


async def _advance_round_if_complete(
    app: FastAPI, tournament: Tournament, round_number: int
) -> bool:
    """Idempotent: safe to call speculatively (e.g. from crash recovery)
    on a round that hasn't finished, or one that's already been advanced."""
    storage = app.state.storage
    matches = service.round_matches(storage, tournament.id, round_number)
    if not service.is_round_complete(matches):
        return False

    already_advanced = str(round_number + 1) in tournament.bracket.get("rounds", {})
    if already_advanced:
        return False

    winners = service.round_winners(matches)

    if len(winners) == 1:
        tournament = service.finish_tournament(storage, tournament, winners[0])
        await _broadcast_bracket(app, tournament)
        result = {
            "type": "tournament_result",
            "tid": tournament.id,
            "winner_user_id": winners[0],
            "prize_usd_est": tournament.prize_usd_est,
        }
        await app.state.tournament_connections.broadcast(tournament.id, result)
        await _send(app, winners[0], result)
        winner = storage.get_user(winners[0])
        if winner is not None:
            winner.current_room_id = None
            storage.update_user(winner)
        return True

    next_round_number = round_number + 1
    next_matches = service.create_round(
        storage, tournament, round_number=next_round_number, ordered_ids=winners
    )
    tournament.bracket["rounds"][str(next_round_number)] = [m.id for m in next_matches]
    tournament = storage.update_tournament(tournament)

    service.log_round_advance_impressions(storage, tournament.id, winners)
    await _broadcast_bracket(app, tournament)
    await _announce_round(app, tournament.id, next_matches)
    return True


async def recover_tournaments(app: FastAPI) -> None:
    """SPEC §5.2 crash-recovery requirement: on restart, any RUNNING
    tournament whose current round is fully resolved but never advanced
    (server died between the last match finishing and round generation)
    picks up where it left off. In-progress matches themselves resume
    normally via the A6 reconnect path (match_ready)."""
    storage = app.state.storage
    for tournament in storage.list_tournaments(status="RUNNING"):
        rounds = tournament.bracket.get("rounds", {})
        if not rounds:
            continue
        latest_round = max(int(r) for r in rounds)
        await _advance_round_if_complete(app, tournament, latest_round)
