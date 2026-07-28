"""Async orchestration for match play over the shared /ws endpoint: turn
timers, dice/state broadcasts, and disconnect/reconnect grace (SPEC §4.4,
§6.3). Business rules (legality, persistence) live in app.match.service;
this module is the asyncio glue around them.
"""

import asyncio
import secrets

from fastapi import FastAPI

from app.engine import legal_moves
from app.engine.models import WHITE
from app.match import config, service
from app.match.runtime import MatchRuntime, MatchRuntimeManager
from app.tournament.orchestrator import handle_match_finished


async def _send(app: FastAPI, user_id: str, message: dict) -> None:
    await app.state.connections.send(user_id, message)


async def _send_error(app: FastAPI, user_id: str, code: str, msg: str) -> None:
    await _send(app, user_id, {"type": "error", "code": code, "msg": msg})


async def handle_message(app: FastAPI, user, message: dict) -> None:
    mtype = message.get("type")
    if mtype == "match_ready":
        await handle_match_ready(app, user, message.get("mid"))
    elif mtype == "move":
        await handle_move(app, user, message.get("mid"), message.get("seq", []))
    elif mtype == "resign":
        await handle_resign(app, user, message.get("mid"))
    elif mtype == "ping":
        await _send(app, user.id, {"type": "pong"})
    elif mtype == "subscribe_lobby":
        return  # handled in the realtime router itself
    else:
        await _send_error(app, user.id, "unknown_message_type", f"unknown type {mtype!r}")


async def _state_message(match, state, for_user_id: str, runtime: MatchRuntime) -> dict:
    your_turn = state.turn == service.color_for_user(match, for_user_id)
    options = legal_moves(state, runtime.dice) if runtime.dice and your_turn else []
    return {
        "type": "state",
        "mid": match.id,
        "game_state": state.to_dict(),
        "your_turn": your_turn,
        "legal_moves": [list(m) for m in options] if your_turn else [],
    }


async def handle_match_ready(app: FastAPI, user, mid: str | None) -> None:
    if not mid:
        await _send_error(app, user.id, "bad_request", "missing mid")
        return
    storage = app.state.storage
    match = storage.get_match(mid)
    if match is None:
        await _send_error(app, user.id, "not_found", "match not found")
        return
    try:
        service.color_for_user(match, user.id)
    except service.NotAParticipant:
        await _send_error(app, user.id, "forbidden", "not a participant in this match")
        return

    runtime = app.state.match_runtimes.get_or_create(mid)
    runtime.participants = {match.player_white_id, match.player_black_id}

    async with runtime.lock:
        if user.id in runtime.disconnected:
            await _handle_reconnect(app, match, runtime, user.id)
            return

        if match.status == service.RUNNING:
            state = service.state_from_match(match)
            # We are about to (re)send the turn-start state with the full set
            # of legal sequences; if the requester is the mover mid-prefix,
            # restart the turn so client and server agree on what's left.
            if runtime.turn_prefix and state.turn == service.color_for_user(match, user.id):
                runtime.turn_prefix = []
            if runtime.dice is None:
                # Fresh runtime with no in-memory turn state — either the very
                # first ready ping right as the match started, or (SPEC §5.2
                # crash recovery) a process restart, which never persists the
                # in-flight dice roll. Re-roll for the current turn rather
                # than handing back a "your_turn: true, legal_moves: []"
                # dead end.
                await _advance_turn(app, match, state)
                return
            await _send(app, user.id, await _state_message(match, state, user.id, runtime))
            return

        runtime.ready.add(user.id)
        if runtime.ready >= runtime.participants:
            match, state = service.start_match(storage, match)
            for uid in runtime.participants:
                await _send(
                    app,
                    uid,
                    {
                        "type": "match_start",
                        "mid": mid,
                        "opponent": service.opponent_id(match, uid),
                        "your_color": service.color_for_user(match, uid),
                    },
                )
            await _advance_turn(app, match, state)


async def _handle_reconnect(app: FastAPI, match, runtime: MatchRuntime, user_id: str) -> None:
    runtime.disconnected.discard(user_id)
    runtime.cancel_disconnect_task(user_id)

    if match.status != service.RUNNING:
        return
    state = service.state_from_match(match)
    your_turn = state.turn == service.color_for_user(match, user_id)
    if your_turn and runtime.turn_prefix:
        # Mid-prefix reconnect: the turn restarts from its persisted start
        # state (nothing mid-turn is ever persisted), so drop the prefix.
        runtime.turn_prefix = []
    await _send(app, user_id, await _state_message(match, state, user_id, runtime))

    if your_turn and runtime.dice is not None and runtime.turn_timer_task is None:
        runtime.generation += 1
        gen = runtime.generation
        runtime.turn_timer_task = asyncio.create_task(_turn_timeout_watcher(app, match.id, gen))


async def _advance_turn(app: FastAPI, match, state) -> None:
    storage = app.state.storage
    runtime = app.state.match_runtimes.get(match.id)

    dice = service.roll_for_turn()
    runtime.dice = dice
    runtime.roll_index += 1
    options = legal_moves(state, dice)

    if options == [()]:
        match, state, winner_color = service.apply_forced_move(
            storage, match, state, (), runtime.move_seq_counter, runtime.roll_index
        )
        if winner_color is not None:
            await _finish_and_broadcast(
                app, match, _winner_id(match, winner_color), "bear_off", final_state=state
            )
            return
        runtime.generation += 1
        await _advance_turn(app, match, state)
        return

    runtime.turn_prefix = []
    runtime.generation += 1
    gen = runtime.generation
    for uid in (match.player_white_id, match.player_black_id):
        await _send(app, uid, {"type": "dice", "mid": match.id, "d1": dice[0], "d2": dice[1]})
        await _send(app, uid, await _state_message(match, state, uid, runtime))
    runtime.turn_timer_task = asyncio.create_task(_turn_timeout_watcher(app, match.id, gen))


def _winner_id(match, winner_color: int) -> str:
    return match.player_white_id if winner_color == WHITE else match.player_black_id


async def handle_move(app: FastAPI, user, mid: str | None, raw_seq: list) -> None:
    if not mid:
        await _send_error(app, user.id, "bad_request", "missing mid")
        return
    storage = app.state.storage
    match = storage.get_match(mid)
    if match is None or match.status != service.RUNNING:
        await _send_error(app, user.id, "not_active", "match is not currently running")
        return

    runtime = app.state.match_runtimes.get(mid)
    if runtime is None or runtime.dice is None:
        await _send_error(app, user.id, "not_active", "no active turn to move in")
        return

    if not raw_seq:
        await _send_error(app, user.id, "bad_request", "empty move")
        return

    async with runtime.lock:
        # Nothing is persisted mid-turn, so the stored state is always the
        # turn-start state; runtime.turn_prefix holds the atomic moves the
        # mover has already committed this turn (submitted one die at a time
        # for instant per-checker feedback on both boards).
        state = service.state_from_match(match)
        try:
            color = service.color_for_user(match, user.id)
        except service.NotAParticipant:
            await _send_error(app, user.id, "forbidden", "not a participant in this match")
            return
        if state.turn != color:
            await _send_error(app, user.id, "not_your_turn", "it is not your turn")
            return

        new_moves = service.moves_from_raw(raw_seq)
        candidate = tuple(runtime.turn_prefix) + new_moves
        full_options = legal_moves(state, runtime.dice)
        if not any(s[: len(candidate)] == candidate for s in full_options):
            await _send_error(app, user.id, "illegal_move", "submitted move is not legal")
            return

        opponent = service.opponent_id(match, user.id)
        await _send(
            app,
            opponent,
            {"type": "opponent_move", "mid": mid, "move": [list(m) for m in new_moves]},
        )

        complete = not any(
            len(s) > len(candidate) for s in full_options if s[: len(candidate)] == candidate
        )
        if not complete:
            runtime.turn_prefix = list(candidate)
            return

        match, new_state, winner_color = service.apply_client_move(
            storage, match, state, runtime.dice, user.id, [list(m) for m in candidate],
            runtime.move_seq_counter, runtime.roll_index,
        )
        runtime.move_seq_counter += len(candidate)
        runtime.turn_prefix = []
        runtime.cancel_turn_timer()
        runtime.consecutive_timeouts[user.id] = 0

        if winner_color is not None:
            await _finish_and_broadcast(
                app, match, _winner_id(match, winner_color), "bear_off", final_state=new_state
            )
            return
        await _advance_turn(app, match, new_state)


async def handle_resign(app: FastAPI, user, mid: str | None) -> None:
    if not mid:
        await _send_error(app, user.id, "bad_request", "missing mid")
        return
    storage = app.state.storage
    match = storage.get_match(mid)
    if match is None or match.status != service.RUNNING:
        await _send_error(app, user.id, "not_active", "match is not currently running")
        return

    runtime = app.state.match_runtimes.get_or_create(mid)
    async with runtime.lock:
        try:
            opponent = service.opponent_id(match, user.id)
        except service.NotAParticipant:
            await _send_error(app, user.id, "forbidden", "not a participant in this match")
            return
        await _finish_and_broadcast(app, match, opponent, "resign")


async def _finish_and_broadcast(
    app: FastAPI, match, winner_id: str, reason: str, final_state=None
) -> None:
    storage = app.state.storage
    if final_state is not None:
        # A bear-off win means the board changed on this very move; make sure
        # clients render the true final position (e.g. 15 checkers off)
        # instead of freezing on the second-to-last state.
        for uid in (match.player_white_id, match.player_black_id):
            await _send(
                app,
                uid,
                {
                    "type": "state",
                    "mid": match.id,
                    "game_state": final_state.to_dict(),
                    "your_turn": False,
                    "legal_moves": [],
                },
            )
    match = service.finish_match(storage, match, winner_id)
    for uid in (match.player_white_id, match.player_black_id):
        await _send(
            app,
            uid,
            {
                "type": "match_result",
                "mid": match.id,
                "winner_user_id": winner_id,
                "reason": reason,
            },
        )
    app.state.match_runtimes.pop(match.id)
    await handle_match_finished(app, match)


# -- turn timeout ------------------------------------------------------


async def _turn_timeout_watcher(app: FastAPI, match_id: str, generation: int) -> None:
    try:
        await asyncio.sleep(config.turn_timeout_seconds())
    except asyncio.CancelledError:
        return
    await _on_turn_timeout(app, match_id, generation)


async def _on_turn_timeout(app: FastAPI, match_id: str, generation: int) -> None:
    runtime = app.state.match_runtimes.get(match_id)
    if runtime is None or runtime.generation != generation:
        return
    storage = app.state.storage
    match = storage.get_match(match_id)
    if match is None or match.status != service.RUNNING:
        return

    async with runtime.lock:
        if runtime.generation != generation:
            return

        state = service.state_from_match(match)
        mover_id = match.player_white_id if state.turn == WHITE else match.player_black_id
        runtime.consecutive_timeouts[mover_id] = runtime.consecutive_timeouts.get(mover_id, 0) + 1

        options = legal_moves(state, runtime.dice)
        prefix = tuple(runtime.turn_prefix)
        if prefix:
            # Mover committed part of the turn then stalled: complete it with
            # the first legal continuation rather than snapping their already-
            # visible moves back off the board.
            candidates = [s for s in options if s[: len(prefix)] == prefix]
            chosen = candidates[0] if candidates else ()
        else:
            chosen = options[0] if len(options) == 1 else ()
        runtime.turn_prefix = []

        match, new_state, winner_color = service.apply_forced_move(
            storage, match, state, chosen, runtime.move_seq_counter, runtime.roll_index
        )
        runtime.move_seq_counter += len(chosen)

        opponent = service.opponent_id(match, mover_id)
        # The opponent already saw the prefix land move-by-move; only send
        # the part the server filled in.
        suffix = chosen[len(prefix):] if prefix else chosen
        await _send(
            app,
            opponent,
            {
                "type": "opponent_move",
                "mid": match_id,
                "move": [list(m) for m in suffix],
                "timeout": True,
            },
        )

        if winner_color is not None:
            await _finish_and_broadcast(
                app, match, _winner_id(match, winner_color), "bear_off", final_state=new_state
            )
            return

        if runtime.consecutive_timeouts[mover_id] >= config.max_consecutive_timeouts():
            await _finish_and_broadcast(app, match, opponent, "forfeit_timeout")
            return

        await _advance_turn(app, match, new_state)


# -- disconnect / reconnect grace --------------------------------------


async def handle_player_disconnected(app: FastAPI, user_id: str) -> None:
    runtime_manager: MatchRuntimeManager = app.state.match_runtimes
    runtime = runtime_manager.find_active_for_user(user_id)
    if runtime is None:
        return
    storage = app.state.storage
    match = storage.get_match(runtime.match_id)
    if match is None or match.status != service.RUNNING:
        return

    async with runtime.lock:
        if user_id in runtime.disconnected:
            return
        runtime.disconnected.add(user_id)

        state = service.state_from_match(match)
        if state.turn == service.color_for_user(match, user_id):
            runtime.cancel_turn_timer()

        opponent = service.opponent_id(match, user_id)
        if opponent in runtime.disconnected:
            for uid in list(runtime.disconnect_tasks):
                runtime.cancel_disconnect_task(uid)
            if runtime.both_disconnect_deadline_task is None:
                runtime.both_disconnect_deadline_task = asyncio.create_task(
                    _both_disconnect_watcher(app, runtime.match_id)
                )
        else:
            runtime.disconnect_tasks[user_id] = asyncio.create_task(
                _disconnect_grace_watcher(app, runtime.match_id, user_id)
            )


async def _disconnect_grace_watcher(app: FastAPI, match_id: str, user_id: str) -> None:
    try:
        await asyncio.sleep(config.reconnect_grace_seconds())
    except asyncio.CancelledError:
        return

    runtime = app.state.match_runtimes.get(match_id)
    if runtime is None or user_id not in runtime.disconnected:
        return
    storage = app.state.storage
    match = storage.get_match(match_id)
    if match is None or match.status != service.RUNNING:
        return

    async with runtime.lock:
        if user_id not in runtime.disconnected:
            return
        opponent = service.opponent_id(match, user_id)
        await _finish_and_broadcast(app, match, opponent, "forfeit_disconnect")


async def _both_disconnect_watcher(app: FastAPI, match_id: str) -> None:
    try:
        await asyncio.sleep(config.both_disconnect_grace_seconds())
    except asyncio.CancelledError:
        return

    runtime = app.state.match_runtimes.get(match_id)
    if runtime is None:
        return
    storage = app.state.storage
    match = storage.get_match(match_id)
    if match is None or match.status != service.RUNNING:
        return

    async with runtime.lock:
        if len(runtime.disconnected) < 2:
            return
        winner_id = secrets.choice([match.player_white_id, match.player_black_id])
        await _finish_and_broadcast(app, match, winner_id, "double_forfeit_disconnect")
