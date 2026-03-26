"""
IntakeFormAPI — serves the patient intake form and processes submissions.

Endpoints:
  GET  /intake/form       — serves the HTML intake form (requires valid HMAC token)
  POST /intake/submit     — receives form answers, populates note, checks patient in
  GET  /intake/dev-link   — (DEV_MODE only) generates a form URL for a given appointment
"""

from canvas_sdk.commands import HistoryOfPresentIllnessCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient
from logger import log

from sentinum_intake.protocols.tokens import generate_token, validate_token


def _format_narrative(data: dict, patient_name: str) -> str:
    """Build a structured HPI narrative from submitted form data."""

    def v(key: str, fallback: str = "Not provided") -> str:
        val = data.get(key, "").strip()
        return val if val else fallback

    severity = data.get("severity", "")
    severity_str = f"{severity}/10" if severity else "Not provided"

    lines = [
        f"=== INTAKE FORM — {patient_name} ===",
        "",
        "TELEHEALTH CONSENTS",
        f"  Private/safe location: {v('private_location')}",
        f"  Name + DOB confirmed: {v('name_dob_confirm')}",
        f"  Current address: {v('current_address')}",
        f"  Telehealth consent: {v('telehealth_consent')}",
        f"  Audio/video quality: {v('av_quality')}",
        "",
        "CHIEF COMPLAINT",
        f"  Primary reason: {v('chief_complaint')}",
        f"  Onset/frequency: {v('symptom_onset')}",
        f"  Severity: {severity_str}",
        f"  Better/worse: {v('better_worse')}",
        f"  Other symptoms: {v('other_symptoms')}",
        "",
        "MEDICAL & SURGICAL HISTORY",
        f"  Chronic conditions: {v('chronic_conditions')}",
        f"  Prior surgeries/hospitalizations: {v('surgeries')}",
        f"  Current specialists: {v('specialists')}",
        "",
        "MEDICATIONS & ALLERGIES",
        f"  Prescription medications: {v('rx_medications')}",
        f"  OTC/Supplements: {v('otc_supplements')}",
        f"  Allergies: {v('allergies')}",
        "",
        "SOCIAL & FAMILY HISTORY",
        f"  Tobacco: {v('tobacco')}",
        f"  Alcohol: {v('alcohol')}",
        f"  Recreational drugs: {v('recreational_drugs')}",
        f"  Family history: {v('family_history')}",
        "",
        "HOME VITALS & WELLNESS",
        f"  Home vitals: {v('home_vitals')}",
        f"  Appetite/sleep/energy changes: {v('wellness_changes')}",
        f"  PHQ-2 (feeling down/hopeless): {v('phq2')}",
    ]
    return "\n".join(lines)


class IntakeFormAPI(SimpleAPI):
    PREFIX = "/intake"

    def authenticate(self, credentials) -> bool:
        # Public endpoints — authentication is handled per-request via HMAC token
        return True

    @api.get("/form")
    def get_form(self) -> list[Response | Effect]:
        params = self.request.query_params
        token = params.get("token", "")
        apt = params.get("apt", "")
        pid = params.get("pid", "")
        exp = params.get("exp", "")

        secret = self.secrets.get("intake-api-secret", "")
        if not validate_token(token, apt, pid, exp, secret):
            return [JSONResponse({"error": "Invalid or expired intake link"}, status_code=401)]

        # Look up patient name for personalization
        patient_name = ""
        try:
            patient = Patient.objects.get(id=pid)
            patient_name = f"{patient.first_name} {patient.last_name}".strip()
        except Patient.DoesNotExist:
            pass

        html = render_to_string(
            "intake_form.html",
            {
                "patient_name": patient_name,
                "token": token,
                "apt": apt,
                "pid": pid,
                "exp": exp,
            },
        )
        return [HTMLResponse(content=html)]

    @api.post("/submit")
    def submit_form(self) -> list[Response | Effect]:
        body = self.request.json()

        token = body.get("token", "")
        apt = body.get("apt", "")
        pid = body.get("pid", "")
        exp = str(body.get("exp", ""))

        secret = self.secrets.get("intake-api-secret", "")
        if not validate_token(token, apt, pid, exp, secret):
            return [JSONResponse({"error": "Invalid or expired intake token"}, status_code=401)]

        # Look up appointment and associated note
        try:
            appointment = Appointment.objects.get(id=apt)
        except Appointment.DoesNotExist:
            log.error(f"[IntakeSubmit] Appointment {apt} not found")
            return [JSONResponse({"error": "Appointment not found"}, status_code=404)]

        if not appointment.note_id:
            log.warning(f"[IntakeSubmit] Appointment {apt} has no associated note")
            return [JSONResponse({"error": "No note found for this appointment"}, status_code=422)]

        try:
            note = Note.objects.get(dbid=appointment.note_id)
            note_uuid_str = str(note.id)
        except Note.DoesNotExist:
            log.error(f"[IntakeSubmit] Note with dbid={appointment.note_id} not found")
            return [JSONResponse({"error": "Appointment note not found"}, status_code=404)]

        # Get patient name for narrative header
        patient_name = ""
        try:
            patient = Patient.objects.get(id=pid)
            patient_name = f"{patient.first_name} {patient.last_name}".strip()
        except Patient.DoesNotExist:
            patient_name = pid

        narrative = _format_narrative(body, patient_name)

        hpi_command = HistoryOfPresentIllnessCommand(
            note_uuid=note_uuid_str,
            narrative=narrative,
        )

        log.info(
            f"[IntakeSubmit] Submitting intake for patient {pid}, "
            f"appointment {apt}, note {note_uuid_str}"
        )

        return [
            BatchOriginateCommandEffect(commands=[hpi_command]).apply(),
            NoteEffect(instance_id=note_uuid_str).check_in(),
            JSONResponse({"status": "ok"}, status_code=200),
        ]

    @api.get("/dev-link")
    def dev_link(self) -> list[Response | Effect]:
        """Return a form URL for local testing. Requires DEV_MODE=true secret."""
        if self.secrets.get("DEV_MODE", "").lower() != "true":
            return [JSONResponse({"error": "dev-link is disabled"}, status_code=403)]

        apt = self.request.query_params.get("apt", "")
        if not apt:
            return [JSONResponse({"error": "apt query param required"}, status_code=422)]

        try:
            appointment = Appointment.objects.get(id=apt)
        except Appointment.DoesNotExist:
            return [JSONResponse({"error": "Appointment not found"}, status_code=404)]

        patient_id = str(appointment.patient.id)
        secret = self.secrets.get("intake-api-secret", "")
        base_url = self.secrets.get("intake-base-url", "").rstrip("/")
        token_data = generate_token(apt, patient_id, secret)

        url = (
            f"{base_url}/plugin-io/api/sentinum_intake/intake/form"
            f"?token={token_data['token']}"
            f"&apt={token_data['apt']}"
            f"&pid={token_data['pid']}"
            f"&exp={token_data['exp']}"
        )
        return [JSONResponse({"url": url, "expires_in_days": 7})]
