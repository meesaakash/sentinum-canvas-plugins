from datetime import datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.external_event import ExternalEvent
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import BearerCredentials, SimpleAPIRoute

from logger import log


METRIPORT_PLUGIN_TOKEN = "METRIPORT_PLUGIN_TOKEN"


class AdtAPIProtocol(SimpleAPIRoute):
    PATH = "/routes/adt"

    def authenticate(self, credentials: BearerCredentials) -> bool:
        provided_token = credentials.token
        token = self.secrets[METRIPORT_PLUGIN_TOKEN]
        return provided_token == token

    def post(self) -> list[Response | Effect]:
        try:
            body = self.request.json()
            log.info(f"ADT event received: {body.get('event_type')}")

            # Parse optional datetime fields
            event_datetime = None
            if body.get("event_datetime"):
                event_datetime = datetime.fromisoformat(body["event_datetime"])

            message_datetime = None
            if body.get("message_datetime"):
                message_datetime = datetime.fromisoformat(body["message_datetime"])

            external_event = ExternalEvent(
                patient_id=body["patient_id"],
                visit_identifier=body["visit_identifier"],
                message_control_id=body["message_control_id"],
                event_type=body["event_type"],
                event_datetime=event_datetime,
                message_datetime=message_datetime,
                information_source=body.get("information_source"),
                facility_name=body.get("facility_name"),
                raw_message=body.get("raw_message"),
            )

            return [
                external_event.create(),
                JSONResponse(
                    {"message": "External event created successfully"},
                    status_code=HTTPStatus.CREATED,
                ),
            ]

        except KeyError as e:
            log.error(f"Missing required field: {e}")
            return [
                JSONResponse(
                    {"error": f"Missing required field: {e}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        except Exception as e:
            log.error(f"Error creating external event: {e}")
            return [
                JSONResponse(
                    {"error": str(e)},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
