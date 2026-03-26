"""
AppointmentCreatedHandler — fires on APPOINTMENT_CREATED.

Generates a signed HMAC intake form link and sends it to the patient via SMS
(Twilio stub — configure separately). Also logs the URL for local development.

The form link is valid for 7 days, covering both same-day and advance bookings.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from sentinum_intake.protocols.tokens import generate_token


class AppointmentCreatedHandler(BaseProtocol):
    RESPONDS_TO = [EventType.Name(EventType.APPOINTMENT_CREATED)]

    def compute(self) -> list[Effect]:
        apt_id = self.event.target.get("id")
        if not apt_id:
            return []

        try:
            appointment = Appointment.objects.get(id=apt_id)
        except Appointment.DoesNotExist:
            log.warning(f"[IntakeSend] Appointment {apt_id} not found")
            return []

        patient = appointment.patient

        # Get patient phone number
        contact = patient.telecom.filter(system="phone").first()
        if not contact:
            log.warning(f"[IntakeSend] No phone number on file for patient {patient.id} — intake link not sent")
            return []

        secret = self.secrets.get("intake-api-secret", "")
        if not secret:
            log.error("[IntakeSend] intake-api-secret is not configured")
            return []

        base_url = self.secrets.get("intake-base-url", "").rstrip("/")
        if not base_url:
            log.error("[IntakeSend] intake-base-url is not configured")
            return []

        token_data = generate_token(str(apt_id), str(patient.id), secret)
        url = (
            f"{base_url}/plugin-io/api/sentinum_intake/intake/form"
            f"?token={token_data['token']}"
            f"&apt={token_data['apt']}"
            f"&pid={token_data['pid']}"
            f"&exp={token_data['exp']}"
        )

        # --- Twilio SMS (stubbed — uncomment and configure to activate) ---
        # from twilio.rest import Client as TwilioClient
        # twilio = TwilioClient(
        #     self.secrets.get("twilio-account-sid"),
        #     self.secrets.get("twilio-auth-token"),
        # )
        # twilio.messages.create(
        #     to=contact.value,
        #     from_=self.secrets.get("twilio-from-number"),
        #     body=(
        #         f"Hi {patient.first_name}, please complete your intake form "
        #         f"before your upcoming appointment: {url}"
        #     ),
        # )
        # log.info(f"[IntakeSend] SMS sent to patient {patient.id}")
        # -------------------------------------------------------------------

        log.info(
            f"[IntakeSend] Intake form URL for patient {patient.id} "
            f"(appt {apt_id}): {url}"
        )
        return []
