"""In-memory, per-process match runtime: dice for the active turn, readiness,
timer tasks, disconnect bookkeeping. Durable state (GameState, status,
winner) lives in StorageBackend and is persisted after every applied move
(SPEC §5.2 crash-recovery requirement) — this class only tracks the
ephemeral bits needed to run live timers and reconnect grace.
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class MatchRuntime:
    match_id: str
    participants: set[str] = field(default_factory=set)
    dice: tuple[int, int] | None = None
    ready: set[str] = field(default_factory=set)
    roll_index: int = -1  # incremented each roll, for audit logging
    move_seq_counter: int = 0  # running position in the match's move log
    generation: int = 0  # bumped whenever the turn advances or the match ends
    turn_timer_task: asyncio.Task | None = None
    consecutive_timeouts: dict[str, int] = field(default_factory=dict)
    disconnected: set[str] = field(default_factory=set)
    disconnect_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    both_disconnect_deadline_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def cancel_turn_timer(self) -> None:
        if self.turn_timer_task is not None and not self.turn_timer_task.done():
            self.turn_timer_task.cancel()
        self.turn_timer_task = None

    def cancel_disconnect_task(self, user_id: str) -> None:
        task = self.disconnect_tasks.pop(user_id, None)
        if task is not None and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        self.cancel_turn_timer()
        for user_id in list(self.disconnect_tasks):
            self.cancel_disconnect_task(user_id)
        both_task = self.both_disconnect_deadline_task
        if both_task is not None and not both_task.done():
            both_task.cancel()
        self.both_disconnect_deadline_task = None


class MatchRuntimeManager:
    def __init__(self) -> None:
        self._matches: dict[str, MatchRuntime] = {}

    def get_or_create(self, match_id: str) -> MatchRuntime:
        if match_id not in self._matches:
            self._matches[match_id] = MatchRuntime(match_id=match_id)
        return self._matches[match_id]

    def get(self, match_id: str) -> MatchRuntime | None:
        return self._matches.get(match_id)

    def pop(self, match_id: str) -> MatchRuntime | None:
        runtime = self._matches.pop(match_id, None)
        if runtime is not None:
            runtime.cancel_all()
        return runtime

    def find_active_for_user(self, user_id: str) -> MatchRuntime | None:
        for runtime in self._matches.values():
            if user_id in runtime.participants:
                return runtime
        return None
