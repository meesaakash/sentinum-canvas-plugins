from hashlib import sha256
from time import time
from urllib.parse import urlencode


class Authenticator:
    @classmethod
    def check(cls, secret: str, expiration_seconds: int, params: dict) -> bool:
        if "ts" not in params or "sig" not in params:
            return False
        timestamp = int(params["ts"])
        if (time() - timestamp) > expiration_seconds:
            return False
        internal_sig = sha256(f"{timestamp}{secret}".encode("utf-8")).hexdigest()
        return bool(params["sig"] == internal_sig)

    @classmethod
    def presigned_url(cls, secret: str, url: str, params: dict) -> str:
        timestamp = str(int(time()))
        sig = sha256(f"{timestamp}{secret}".encode("utf-8")).hexdigest()
        return f"{url}?{urlencode(params | {'ts': timestamp, 'sig': sig})}"

    @classmethod
    def presigned_url_no_params(cls, secret: str, url: str) -> str:
        return cls.presigned_url(secret, url, {})
