import os


def get_ready_seconds() -> float:
    """SPEC §5.2: 30s "get ready" countdown before round 1 starts."""
    return float(os.environ.get("TOURNAMENT_GET_READY_SECONDS", "30"))


def match_join_timeout_seconds() -> float:
    """SPEC §5.2: players get MATCH_JOIN_TIMEOUT to appear for a new round, else forfeit."""
    return float(os.environ.get("MATCH_JOIN_TIMEOUT", "90"))


def payout_rate() -> float:
    """SPEC §5.3: winner receives payout_rate x tournament ad revenue, default 50%."""
    return float(os.environ.get("PAYOUT_RATE", "0.50"))


def stub_impression_revenue_usd() -> float:
    """SPEC §14 A7 DoD: stub revenue model ($0.015/simulated impression) so the
    prize math path is real even though no real ad network is wired up yet."""
    return float(os.environ.get("STUB_IMPRESSION_REVENUE_USD", "0.015"))
