"""
Stateless HMAC-signed tokens for intake form links.

Token URL params: token=<sig>&apt=<appointment_id>&pid=<patient_id>&exp=<unix_ts>
No database storage required — the HMAC signature validates authenticity.
"""

import hashlib
import hmac
import time
from hmac import compare_digest

TTL_SECONDS = 7 * 24 * 3600  # 7 days — covers advance bookings


def generate_token(apt_id: str, patient_id: str, secret: str) -> dict:
    """Generate a signed token dict for the intake form URL."""
    exp = int(time.time()) + TTL_SECONDS
    payload = f"{apt_id}:{patient_id}:{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {"token": sig, "apt": apt_id, "pid": patient_id, "exp": exp}


def validate_token(token: str, apt: str, pid: str, exp: str, secret: str) -> bool:
    """Return True if the token is valid and not expired."""
    try:
        if time.time() > int(exp):
            return False
        payload = f"{apt}:{pid}:{exp}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return compare_digest(token, expected)
    except Exception:
        return False
