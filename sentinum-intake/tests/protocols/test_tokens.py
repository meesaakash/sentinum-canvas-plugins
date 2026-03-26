"""Tests for HMAC token generation and validation."""

import time
from unittest.mock import patch

import pytest

from sentinum_intake.protocols.tokens import TTL_SECONDS, generate_token, validate_token

SECRET = "test-secret-key"
APT_ID = "apt-uuid-1234"
PATIENT_ID = "patient-uuid-5678"


class TestGenerateToken:
    def test_returns_required_keys(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert set(tok.keys()) == {"token", "apt", "pid", "exp"}

    def test_apt_and_pid_match_inputs(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert tok["apt"] == APT_ID
        assert tok["pid"] == PATIENT_ID

    def test_exp_is_future(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert tok["exp"] > int(time.time())

    def test_exp_is_approximately_7_days(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        delta = tok["exp"] - int(time.time())
        assert abs(delta - TTL_SECONDS) < 5  # within 5 seconds


class TestValidateToken:
    def test_valid_token_returns_true(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert validate_token(tok["token"], APT_ID, PATIENT_ID, str(tok["exp"]), SECRET) is True

    def test_wrong_secret_returns_false(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert validate_token(tok["token"], APT_ID, PATIENT_ID, str(tok["exp"]), "wrong-secret") is False

    def test_tampered_apt_returns_false(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert validate_token(tok["token"], "different-apt", PATIENT_ID, str(tok["exp"]), SECRET) is False

    def test_tampered_pid_returns_false(self) -> None:
        tok = generate_token(APT_ID, PATIENT_ID, SECRET)
        assert validate_token(tok["token"], APT_ID, "different-patient", str(tok["exp"]), SECRET) is False

    def test_expired_token_returns_false(self) -> None:
        past_exp = int(time.time()) - 1
        import hashlib
        import hmac
        payload = f"{APT_ID}:{PATIENT_ID}:{past_exp}"
        sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        assert validate_token(sig, APT_ID, PATIENT_ID, str(past_exp), SECRET) is False

    def test_garbage_token_returns_false(self) -> None:
        assert validate_token("garbage", APT_ID, PATIENT_ID, "notanumber", SECRET) is False
