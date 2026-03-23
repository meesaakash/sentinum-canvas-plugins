from datetime import datetime, timezone

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast, JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPIRoute

from livekit_scribe.libraries.authenticator import Authenticator


class ProgressDisplay(SimpleAPIRoute):
    PATH = "/progress"

    def authenticate(self, credentials: Credentials) -> bool:
        return Authenticator.check(
            self.secrets["APISigningKey"],
            3600,
            self.request.query_params,
        )

    def get(self) -> list[Response | Effect]:
        now = datetime.now(timezone.utc)
        messages = []
        if (key := self._cache_key()) and (cached := get_cache().get(key)):
            messages = cached
        return [JSONResponse({"time": now.isoformat(), "messages": messages})]

    def post(self) -> list[Response | Effect]:
        from http import HTTPStatus
        events = self.request.json()
        if key := self._cache_key():
            cached = get_cache().get(key)
            if not isinstance(cached, list):
                cached = []
            cached.extend(events)
            get_cache().set(key, cached)
        note_id = self.request.query_params.get("note_id", "")
        channel = self._ws_channel(note_id)
        return [
            Broadcast(message={"events": events}, channel=channel).apply(),
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.ACCEPTED),
        ]

    def _cache_key(self) -> str:
        if note_id := self.request.query_params.get("note_id"):
            return f"livekit-scribe-progress-{note_id}"
        return ""

    @staticmethod
    def _ws_channel(note_id: str) -> str:
        return f"livekit_scribe_progress_{note_id.replace('-', '')}"
