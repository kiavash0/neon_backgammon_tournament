import pytest

from app.security.fraud_gate import FraudGateConfigError, assert_safe_to_boot


def test_dev_defaults_are_safe_to_boot():
    assert_safe_to_boot(env="development", fraud_mode="disabled", payout_provider="demo")


def test_production_requires_fraud_check_enabled():
    with pytest.raises(FraudGateConfigError):
        assert_safe_to_boot(env="production", fraud_mode="disabled", payout_provider="demo")

    with pytest.raises(FraudGateConfigError):
        assert_safe_to_boot(env="production", fraud_mode="log_only", payout_provider="demo")

    assert_safe_to_boot(env="production", fraud_mode="enabled", payout_provider="demo")


def test_real_payout_provider_requires_fraud_check_enabled():
    with pytest.raises(FraudGateConfigError):
        assert_safe_to_boot(env="development", fraud_mode="disabled", payout_provider="tremendous")

    assert_safe_to_boot(env="development", fraud_mode="enabled", payout_provider="tremendous")


def test_env_vars_are_read_when_not_passed_explicitly(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("FRAUD_SEATING_CHECK", "disabled")
    monkeypatch.setenv("PAYOUT_PROVIDER", "demo")
    with pytest.raises(FraudGateConfigError):
        assert_safe_to_boot()
