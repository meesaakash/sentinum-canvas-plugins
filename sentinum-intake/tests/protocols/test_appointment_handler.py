"""Tests for AppointmentCreatedHandler."""

import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest

from sentinum_intake.protocols.appointment_handler import AppointmentCreatedHandler

APT_ID = str(uuid.uuid4())
PATIENT_ID = str(uuid.uuid4())
SECRET = "test-secret"
BASE_URL = "https://example.canvasmedical.com"


def make_handler(apt_id: str = APT_ID) -> AppointmentCreatedHandler:
    mock_event = Mock()
    mock_event.target = {"id": apt_id}
    return AppointmentCreatedHandler(
        event=mock_event,
        secrets={
            "intake-api-secret": SECRET,
            "intake-base-url": BASE_URL,
        },
    )


class TestAppointmentCreatedHandler:
    def test_returns_no_effects_when_patient_has_no_phone(self) -> None:
        handler = make_handler()
        mock_patient = Mock()
        mock_patient.id = PATIENT_ID
        mock_patient.telecom.filter.return_value.first.return_value = None

        mock_apt = Mock()
        mock_apt.patient = mock_patient

        with patch("sentinum_intake.protocols.appointment_handler.Appointment") as mock_apt_cls:
            mock_apt_cls.objects.get.return_value = mock_apt
            effects = handler.compute()

        assert effects == []

    def test_returns_no_effects_when_appointment_not_found(self) -> None:
        handler = make_handler()
        with patch("sentinum_intake.protocols.appointment_handler.Appointment") as mock_apt_cls:
            mock_apt_cls.objects.get.side_effect = Exception("DoesNotExist")
            # DoesNotExist is caught generically in handler
            mock_apt_cls.DoesNotExist = Exception
            mock_apt_cls.objects.get.side_effect = mock_apt_cls.DoesNotExist
            effects = handler.compute()
        assert effects == []

    def test_returns_no_effects_when_secret_missing(self) -> None:
        mock_event = Mock()
        mock_event.target = {"id": APT_ID}
        handler = AppointmentCreatedHandler(
            event=mock_event,
            secrets={"intake-base-url": BASE_URL},  # no intake-api-secret
        )

        mock_patient = Mock()
        mock_patient.id = PATIENT_ID
        mock_contact = Mock()
        mock_contact.value = "5555555555"
        mock_patient.telecom.filter.return_value.first.return_value = mock_contact

        mock_apt = Mock()
        mock_apt.patient = mock_patient

        with patch("sentinum_intake.protocols.appointment_handler.Appointment") as mock_apt_cls:
            mock_apt_cls.objects.get.return_value = mock_apt
            effects = handler.compute()

        assert effects == []

    def test_logs_form_url_when_phone_and_secrets_present(self, caplog) -> None:
        handler = make_handler()

        mock_patient = Mock()
        mock_patient.id = PATIENT_ID
        mock_contact = Mock()
        mock_contact.value = "5555555555"
        mock_patient.telecom.filter.return_value.first.return_value = mock_contact

        mock_apt = Mock()
        mock_apt.patient = mock_patient

        with (
            patch("sentinum_intake.protocols.appointment_handler.Appointment") as mock_apt_cls,
            patch("sentinum_intake.protocols.appointment_handler.log") as mock_log,
        ):
            mock_apt_cls.objects.get.return_value = mock_apt
            effects = handler.compute()
            assert mock_log.info.called
            logged_url = mock_log.info.call_args[0][0]
            assert "/plugin-io/api/sentinum_intake/intake/form" in logged_url
            assert "token=" in logged_url

        assert effects == []
