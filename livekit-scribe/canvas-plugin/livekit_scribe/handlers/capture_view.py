import json
import time
from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from livekit.api import AccessToken, VideoGrants

from livekit_scribe.libraries.authenticator import Authenticator


class CaptureView(SimpleAPI):
    PREFIX = None

    def authenticate(self, credentials: Credentials) -> bool:
        return Authenticator.check(
            self.secrets["APISigningKey"],
            3600,
            self.request.query_params,
        )

    @api.get("/capture/<patient_uuid>/<note_uuid>/<note_id>")
    def capture_get(self) -> list[Response | Effect]:
        patient_uuid = self.request.path_params["patient_uuid"]
        note_uuid = self.request.path_params["note_uuid"]
        note_id = self.request.path_params["note_id"]

        token_url = Authenticator.presigned_url(
            self.secrets["APISigningKey"],
            f"/plugin-io/api/livekit_scribe/token/{patient_uuid}/{note_uuid}/{note_id}",
            {},
        )
        progress_url = Authenticator.presigned_url(
            self.secrets["APISigningKey"],
            "/plugin-io/api/livekit_scribe/progress",
            {"note_id": note_id},
        )

        html = render_to_string(
            "livekit_scribe/scribe.html",
            {
                "token_url": token_url,
                "progress_url": progress_url,
                "note_uuid": note_uuid,
                "note_id": note_id,
            },
        )
        return [HTMLResponse(html)]

    @api.get("/token/<patient_uuid>/<note_uuid>/<note_id>")
    def get_token(self) -> list[Response | Effect]:
        patient_uuid = self.request.path_params["patient_uuid"]
        note_uuid = self.request.path_params["note_uuid"]
        note_id = self.request.path_params["note_id"]

        livekit_url = self.secrets["LiveKitUrl"]
        api_key = self.secrets["LiveKitApiKey"]
        api_secret = self.secrets["LiveKitApiSecret"]
        canvas_instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        signing_key = self.secrets["APISigningKey"]

        room_name = f"note-{note_uuid}"
        room_metadata = json.dumps({
            "note_uuid": note_uuid,
            "patient_uuid": patient_uuid,
            "provider_uuid": "",
            "canvas_instance": f"https://{canvas_instance}" if canvas_instance and not canvas_instance.startswith("http") else canvas_instance,
            "api_signing_key": signing_key,
        })

        # Generate LiveKit participant token
        token = (
            AccessToken(api_key, api_secret)
            .with_identity(f"provider-{note_id}")
            .with_name("Provider")
            .with_grants(VideoGrants(room_join=True, room=room_name))
            .with_metadata(room_metadata)
            .to_jwt()
        )

        return [JSONResponse({"token": token, "url": livekit_url, "room": room_name})]
