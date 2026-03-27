from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from requests import Response
from logger import log

METRIPORT_WEBHOOK_URL = "https://api.metriport.com/ehr/webhook/canvas"
METRIPORT_WEBHOOK_NAME = "demographics-updated"
METRIPORT_TOKEN_SECRET = "METRIPORT_WEBHOOK_TOKEN"


class PatientDemographicsUpdatedProtocol(BaseProtocol):
    """
    A protocol that sends a webhook to the Metriport API when a patient's
    demographics (name, dob and gender) is updated in Canvas.
    """

    RESPONDS_TO = EventType.Name(EventType.PATIENT_UPDATED)

    def compute(self):
        """Notify Metriport when patient demographics are updated."""
        metriport_token = self.secrets[METRIPORT_TOKEN_SECRET]
        if metriport_token is None:
            raise Exception("Metriport token not set")
        if metriport_token == "":
            raise Exception("Metriport token is empty")

        patient_id = self.event.target.id

        url = f"{METRIPORT_WEBHOOK_URL}/patient/{patient_id}/{METRIPORT_WEBHOOK_NAME}"
        payload = create_webhook_payload(METRIPORT_WEBHOOK_NAME, patient_id)
        headers = create_webhook_headers(metriport_token)
        make_webhook_request(url, payload, headers)
        return []


def create_webhook_payload(wh_type: str, patient_id: str) -> dict:
    return {
        "meta": {
            "type": wh_type,
        },
        "patientId": patient_id,
    }


def create_webhook_headers(metriport_token: str) -> dict:
    return {
        "authorization": f"Bearer {metriport_token}",
    }


def make_webhook_request(url: str, payload: dict, headers: dict) -> Response:
    http = Http()
    response = http.post(url, json=payload, headers=headers)
    if response.ok:
        log.info("Webhook request successful")
        return response
    log.error(f"Webhook request failed: {response}")
    raise Exception(f"Webhook request failed: {response}")
