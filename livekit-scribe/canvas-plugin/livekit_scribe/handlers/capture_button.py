from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import Note

from livekit_scribe.libraries.authenticator import Authenticator


class CaptureButton(ActionButton):
    BUTTON_TITLE = "🎙 Scribe"
    BUTTON_KEY = "LIVEKIT_SCRIBE_CAPTURE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    RESPONDS_TO = [
        EventType.Name(EventType.SHOW_NOTE_HEADER_BUTTON),
        EventType.Name(EventType.ACTION_BUTTON_CLICKED),
    ]

    def handle(self) -> list[Effect]:
        note_id = self.event.context["note_id"]
        note_uuid = str(Note.objects.get(dbid=note_id).id)
        patient_uuid = self.target

        presigned_url = Authenticator.presigned_url(
            self.secrets["APISigningKey"],
            f"/plugin-io/api/livekit_scribe/capture/{patient_uuid}/{note_uuid}/{note_id}",
            {},
        )

        return [
            LaunchModalEffect(
                url=presigned_url,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="AI Scribe",
            ).apply()
        ]

    def visible(self) -> bool:
        return True
