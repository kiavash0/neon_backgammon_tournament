import os


def turn_timeout_seconds() -> float:
    """SPEC §4.4: 30s move timer."""
    return float(os.environ.get("TURN_TIMEOUT_SECONDS", "30"))


def max_consecutive_timeouts() -> int:
    """SPEC §4.4: 3 consecutive timeouts -> match forfeit."""
    return int(os.environ.get("MAX_CONSECUTIVE_TIMEOUTS", "3"))


def reconnect_grace_seconds() -> float:
    """SPEC §4.4: 60s single-player reconnect grace."""
    return float(os.environ.get("RECONNECT_GRACE_SECONDS", "60"))


def both_disconnect_grace_seconds() -> float:
    """SPEC §4.4: 2-minute both-disconnected pause before a double forfeit."""
    return float(os.environ.get("BOTH_DISCONNECT_GRACE_SECONDS", "120"))
