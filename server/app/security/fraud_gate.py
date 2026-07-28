"""Fraud-seating gate config (SPEC §10.2). Same-device/same-IP collision
detection for room seating needs device-fingerprint signal this codebase
doesn't collect yet (that lands with mobile/attestation work, §8.3) — so
this module owns only the part that's fully specified today: the
env-gated mode and the hard safety rail that ties it to real money.

The rail: the server must refuse to boot with the seating check off (or
log-only) in production, and must refuse to boot with a real payout
provider configured unless the check is fully enabled. This makes it
impossible to go live with real payouts and the fraud gate accidentally
off.
"""

import os

VALID_MODES = {"enabled", "log_only", "disabled"}


class FraudGateConfigError(Exception):
    """Configuration is unsafe to boot with."""


def get_fraud_seating_mode() -> str:
    mode = os.environ.get("FRAUD_SEATING_CHECK", "disabled").lower()
    if mode not in VALID_MODES:
        raise FraudGateConfigError(
            f"invalid FRAUD_SEATING_CHECK={mode!r}; expected one of {sorted(VALID_MODES)}"
        )
    return mode


def assert_safe_to_boot(
    *,
    env: str | None = None,
    fraud_mode: str | None = None,
    payout_provider: str | None = None,
) -> None:
    env = (env if env is not None else os.environ.get("ENV", "development")).lower()
    fraud_mode = fraud_mode if fraud_mode is not None else get_fraud_seating_mode()
    if payout_provider is None:
        payout_provider = os.environ.get("PAYOUT_PROVIDER", "demo")
    payout_provider = payout_provider.lower()

    if env == "production" and fraud_mode != "enabled":
        raise FraudGateConfigError(
            "refusing to start: ENV=production requires FRAUD_SEATING_CHECK=enabled"
            f" (got {fraud_mode!r})"
        )
    if payout_provider != "demo" and fraud_mode != "enabled":
        raise FraudGateConfigError(
            "refusing to start: a real payout provider is configured"
            f" (PAYOUT_PROVIDER={payout_provider!r}) but FRAUD_SEATING_CHECK is not"
            f" 'enabled' (got {fraud_mode!r})"
        )
