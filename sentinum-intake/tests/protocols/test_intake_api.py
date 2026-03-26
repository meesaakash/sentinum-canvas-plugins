"""Tests for IntakeFormAPI — form serving, submission, and dev-link."""

import json
import time
import uuid
from unittest.mock import Mock, patch

import pytest

from sentinum_intake.protocols.intake_api import IntakeFormAPI, _format_narrative
from sentinum_intake.protocols.tokens import generate_token

SECRET = "test-secret"
BASE_URL = "https://example.canvasmedical.com"
APT_ID = str(uuid.uuid4())
PATIENT_ID = str(uuid.uuid4())
NOTE_ID = str(uuid.uuid4())
NOTE_DBID = 42


def _valid_token(apt: str = APT_ID, pid: str = PATIENT_ID) -> dict:
    return generate_token(apt, pid, SECRET)


def make_api(secrets: dict | None = None, method: str = "GET") -> IntakeFormAPI:
    mock_event = Mock()
    mock_event.target = {}
    mock_event.context = {
        "method": method,
        "path": "/intake/form",
        "query_string": "",
        "body": b"",
        "headers": [],
    }
    return IntakeFormAPI(
        event=mock_event,
        secrets=secrets or {"intake-api-secret": SECRET, "intake-base-url": BASE_URL},
    )


class TestGetForm:
    def test_invalid_token_returns_401(self) -> None:
        api = make_api()
        api.request = Mock()
        api.request.query_params = {"token": "bad", "apt": APT_ID, "pid": PATIENT_ID, "exp": "0"}
        results = api.get_form()
        assert len(results) == 1
        assert results[0].status_code == 401

    def test_valid_token_returns_html(self) -> None:
        tok = _valid_token()
        api = make_api()
        api.request = Mock()
        api.request.query_params = {
            "token": tok["token"], "apt": APT_ID, "pid": PATIENT_ID, "exp": str(tok["exp"])
        }

        mock_patient = Mock()
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"

        with (
            patch("sentinum_intake.protocols.intake_api.Patient") as mock_patient_cls,
            patch("sentinum_intake.protocols.intake_api.render_to_string", return_value="<html>form</html>"),
        ):
            mock_patient_cls.objects.get.return_value = mock_patient
            results = api.get_form()

        assert len(results) == 1
        assert results[0].content == b"<html>form</html>"


class TestSubmitForm:
    def _make_api(self) -> IntakeFormAPI:
        return make_api(method="POST")

    def _base_body(self) -> dict:
        tok = _valid_token()
        return {
            "token": tok["token"],
            "apt": APT_ID,
            "pid": PATIENT_ID,
            "exp": tok["exp"],
            "chief_complaint": "Cough",
            "phq2": "0 - Not at all",
            "private_location": "Yes",
            "telehealth_consent": "Yes",
            "av_quality": "Yes, clear",
            "name_dob_confirm": "Jane Doe, 01/01/1985",
            "current_address": "123 Main St",
        }

    def test_invalid_token_returns_401(self) -> None:
        api = make_api(method="POST")
        api.request = Mock()
        api.request.json.return_value = {
            "token": "bad", "apt": APT_ID, "pid": PATIENT_ID, "exp": "0"
        }
        results = api.submit_form()
        assert results[0].status_code == 401

    def test_appointment_not_found_returns_404(self) -> None:
        api = make_api(method="POST")
        api.request = Mock()
        api.request.json.return_value = self._base_body()

        with patch("sentinum_intake.protocols.intake_api.Appointment") as mock_apt_cls:
            mock_apt_cls.DoesNotExist = Exception
            mock_apt_cls.objects.get.side_effect = mock_apt_cls.DoesNotExist
            results = api.submit_form()

        assert results[0].status_code == 404

    def test_successful_submit_returns_batch_checkin_and_200(self) -> None:
        api = make_api(method="POST")
        api.request = Mock()
        api.request.json.return_value = self._base_body()

        mock_note = Mock()
        mock_note.id = NOTE_ID

        mock_apt = Mock()
        mock_apt.note_id = NOTE_DBID

        mock_patient = Mock()
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"

        with (
            patch("sentinum_intake.protocols.intake_api.Appointment") as mock_apt_cls,
            patch("sentinum_intake.protocols.intake_api.Note") as mock_note_cls,
            patch("sentinum_intake.protocols.intake_api.Patient") as mock_patient_cls,
            patch("sentinum_intake.protocols.intake_api.NoteEffect") as mock_note_effect_cls,
        ):
            mock_apt_cls.objects.get.return_value = mock_apt
            mock_note_cls.objects.get.return_value = mock_note
            mock_patient_cls.objects.get.return_value = mock_patient
            mock_note_effect_cls.return_value.check_in.return_value = Mock()

            results = api.submit_form()

        # Expect: BatchOriginateCommandEffect, NoteEffect.check_in(), JSONResponse
        assert len(results) == 3
        json_resp = results[-1]
        assert json_resp.status_code == 200


class TestDevLink:
    def test_dev_mode_disabled_returns_403(self) -> None:
        api = make_api(secrets={"intake-api-secret": SECRET, "intake-base-url": BASE_URL})
        api.request = Mock()
        api.request.query_params = {"apt": APT_ID}
        results = api.dev_link()
        assert results[0].status_code == 403

    def test_dev_mode_enabled_returns_url(self) -> None:
        api = make_api(secrets={
            "intake-api-secret": SECRET,
            "intake-base-url": BASE_URL,
            "DEV_MODE": "true",
        })
        api.request = Mock()
        api.request.query_params = {"apt": APT_ID}

        mock_patient = Mock()
        mock_patient.id = PATIENT_ID
        mock_apt = Mock()
        mock_apt.patient = mock_patient

        with patch("sentinum_intake.protocols.intake_api.Appointment") as mock_apt_cls:
            mock_apt_cls.objects.get.return_value = mock_apt
            results = api.dev_link()

        assert results[0].status_code == 200
        data = json.loads(results[0].content)
        assert "url" in data
        assert "/plugin-io/api/sentinum_intake/intake/form" in data["url"]


class TestFormatNarrative:
    def test_includes_chief_complaint(self) -> None:
        narrative = _format_narrative({"chief_complaint": "Chest pain"}, "John Smith")
        assert "Chest pain" in narrative
        assert "John Smith" in narrative

    def test_missing_fields_show_not_provided(self) -> None:
        narrative = _format_narrative({}, "Test Patient")
        assert "Not provided" in narrative

    def test_severity_formatted_as_fraction(self) -> None:
        narrative = _format_narrative({"severity": 7}, "Test")
        assert "7/10" in narrative
