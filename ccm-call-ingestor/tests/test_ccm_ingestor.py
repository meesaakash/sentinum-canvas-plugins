"""
Tests for CCMCallIngestor handler.

Run with: uv run pytest tests/test_ccm_ingestor.py -v
"""

import json
import uuid
from unittest.mock import Mock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.commands import (
    AssessCommand,
    GoalCommand,
    HistoryOfPresentIllnessCommand,
    PlanCommand,
)
from canvas_sdk.effects.simple_api import JSONResponse
from canvas_sdk.effects.task import TaskStatus
from canvas_sdk.handlers.simple_api import APIKeyCredentials
from canvas_sdk.test_utils.factories import (
    NoteTypeFactory,
    PatientFactory,
    PracticeLocationFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.note import NoteTypeCategories

from ccm_call_ingestor.handlers.ccm_ingestor import CCMCallIngestor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event_context(method: str = "POST", path: str = "/ccm-ingest/calls") -> dict:
    return {
        "method": method,
        "path": path,
        "query_string": "",
        "body": b"{}",
        "headers": [],
    }


def make_handler(
    payload: dict | None = None,
    api_key: str = "test-secret",
    note_type_id: str = "",
) -> CCMCallIngestor:
    """Instantiate CCMCallIngestor with a mocked event and request."""
    mock_event = Mock()
    mock_event.context = make_event_context()
    handler = CCMCallIngestor(
        event=mock_event,
        secrets={"simpleapi-api-key": api_key, "NOTE_TYPE_ID": note_type_id},
    )
    mock_request = Mock()
    mock_request.json.return_value = payload or {}
    # Override the cached_property by writing directly to the instance __dict__
    handler.__dict__["request"] = mock_request
    return handler


def response_body(response: JSONResponse) -> dict:
    """Parse the JSON body from a JSONResponse (stored as bytes in .content)."""
    return json.loads(response.content)


def get_json_response(effects: list) -> JSONResponse:
    """Extract the first JSONResponse from the effects list."""
    for e in effects:
        if isinstance(e, JSONResponse):
            return e
    raise AssertionError("No JSONResponse found in effects")


# ---------------------------------------------------------------------------
# Fixtures — create real DB records for happy-path and command-building tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_fixtures():
    """Create real Canvas DB records needed for NoteEffect validation."""
    patient = PatientFactory.create()
    staff = StaffFactory.create()
    location = PracticeLocationFactory.create()
    note_type = NoteTypeFactory.create(
        name="Office visit",
        is_active=True,
        category=NoteTypeCategories.ENCOUNTER,
    )
    return {
        "patient_id": str(patient.id),
        "provider_id": str(staff.id),
        "practice_location_id": str(location.id),
        "note_type_id": str(note_type.id),
    }


@pytest.fixture()
def valid_payload(db_fixtures) -> dict:
    """Valid CCM call payload using real DB UUIDs."""
    return {
        "patient_id": db_fixtures["patient_id"],
        "provider_id": db_fixtures["provider_id"],
        "practice_location_id": db_fixtures["practice_location_id"],
        "datetime_of_service": "2024-01-15T14:30:00Z",
        "call_summary": "Patient reports stable blood pressure at home.",
        "care_plan": "Continue current medications. Follow up in 2 weeks.",
        "conditions": [
            {
                "condition_id": str(uuid.uuid4()),
                "status": "stable",
                "narrative": "BP well controlled",
            }
        ],
        "goals": ["Maintain blood pressure <130/80"],
        "action_items": [
            {"title": "Schedule follow-up lab", "assignee": "nurse_id_123"}
        ],
    }


# ---------------------------------------------------------------------------
# Authentication tests  (no DB needed)
# ---------------------------------------------------------------------------

class TestAuthenticate:
    def test_valid_key_returns_true(self) -> None:
        handler = make_handler(api_key="correct-key")
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = "correct-key"
        assert handler.authenticate(credentials) is True

    def test_invalid_key_returns_false(self) -> None:
        handler = make_handler(api_key="correct-key")
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = "wrong-key"
        assert handler.authenticate(credentials) is False

    def test_missing_secret_returns_false(self) -> None:
        mock_event = Mock()
        mock_event.context = make_event_context()
        handler = CCMCallIngestor(event=mock_event, secrets={})
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = "any-key"
        assert handler.authenticate(credentials) is False

    def test_empty_secret_returns_false(self) -> None:
        mock_event = Mock()
        mock_event.context = make_event_context()
        handler = CCMCallIngestor(event=mock_event, secrets={"simpleapi-api-key": ""})
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = ""
        assert handler.authenticate(credentials) is False


# ---------------------------------------------------------------------------
# Validation tests  (no DB needed — return early before NoteEffect is built)
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_required_field_returns_422(self) -> None:
        payload = {
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2024-01-15T14:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }  # patient_id intentionally missing
        handler = make_handler(payload)
        effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 422
        assert "patient_id" in response_body(response)["error"]

    def test_multiple_missing_fields_listed_in_error(self) -> None:
        payload = {
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2024-01-15T14:30:00Z",
            "call_summary": "Summary.",
        }  # patient_id and care_plan missing
        handler = make_handler(payload)
        effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 422
        assert "care_plan" in response_body(response)["error"]
        assert "patient_id" in response_body(response)["error"]

    def test_invalid_datetime_returns_422(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "not-a-date",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload)
        with patch("ccm_call_ingestor.handlers.ccm_ingestor.Patient"):
            effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 422
        assert "datetime_of_service" in response_body(response)["error"]

    def test_unknown_patient_returns_404(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2024-01-15T14:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload)
        with patch("ccm_call_ingestor.handlers.ccm_ingestor.Patient") as mock_patient:
            mock_patient.DoesNotExist = Exception
            mock_patient.objects.get.side_effect = mock_patient.DoesNotExist("not found")
            effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 404
        assert "Patient not found" in response_body(response)["error"]

    def test_condition_missing_condition_id_returns_422(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2024-01-15T14:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
            "conditions": [{"status": "stable", "narrative": "no condition id"}],
        }
        handler = make_handler(payload)
        with patch("ccm_call_ingestor.handlers.ccm_ingestor.Patient"):
            effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 422
        assert "condition_id" in response_body(response)["error"]


# ---------------------------------------------------------------------------
# Note type resolution tests  (no DB needed)
# ---------------------------------------------------------------------------

class TestResolveNoteType:
    def test_note_type_from_secret_is_used(self) -> None:
        custom_note_type_id = str(uuid.uuid4())
        handler = make_handler(note_type_id=custom_note_type_id)
        result = handler._resolve_note_type_id()
        assert result == custom_note_type_id

    def test_falls_back_to_name_lookup_when_secret_empty(self) -> None:
        fallback_id = str(uuid.uuid4())
        handler = make_handler(note_type_id="")
        with patch("ccm_call_ingestor.handlers.ccm_ingestor.NoteType") as mock_nt:
            mock_note_type = Mock()
            mock_note_type.id = fallback_id
            mock_nt.objects.get.return_value = mock_note_type
            result = handler._resolve_note_type_id()
        assert result == fallback_id
        mock_nt.objects.get.assert_called_once_with(name="Office visit", is_active=True)

    def test_unresolvable_note_type_returns_none(self) -> None:
        handler = make_handler(note_type_id="")
        with patch("ccm_call_ingestor.handlers.ccm_ingestor.NoteType") as mock_nt:
            mock_nt.DoesNotExist = Exception
            mock_nt.MultipleObjectsReturned = ValueError
            mock_nt.objects.get.side_effect = mock_nt.DoesNotExist("not found")
            result = handler._resolve_note_type_id()
        assert result is None

    def test_unresolvable_note_type_returns_500_in_handler(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2024-01-15T14:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload=payload, note_type_id="")
        with (
            patch("ccm_call_ingestor.handlers.ccm_ingestor.Patient"),
            patch.object(handler, "_resolve_note_type_id", return_value=None),
        ):
            effects = handler.ingest_call()
        response = get_json_response(effects)
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Happy-path tests  (require real DB records via db_fixtures)
# ---------------------------------------------------------------------------

class TestSuccessfulIngest:
    def _run(self, db_fixtures: dict, payload: dict) -> list:
        handler = make_handler(payload=payload, note_type_id=db_fixtures["note_type_id"])
        return handler.ingest_call()

    def test_returns_201_with_note_id(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        response = get_json_response(effects)
        assert response.status_code == 201
        body = response_body(response)
        assert "note_id" in body
        uuid.UUID(body["note_id"])  # must be a valid UUID

    def test_four_effects_returned(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        # NoteEffect.create(), BatchOriginate.apply(), AddTask.apply(), JSONResponse
        assert len(effects) == 4

    def test_note_uuid_consistent_across_effects(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        response = get_json_response(effects)
        note_id = response_body(response)["note_id"]
        # The note_id should appear in at least one Effect payload (note or batch commands)
        found = False
        for e in effects:
            if hasattr(e, "payload") and isinstance(e.payload, str) and note_id in e.payload:
                found = True
                break
        assert found, f"note_id {note_id} not found in any effect payload"

    def test_empty_conditions_succeeds(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = []
        effects = self._run(db_fixtures, valid_payload)
        assert get_json_response(effects).status_code == 201

    def test_empty_goals_succeeds(self, db_fixtures, valid_payload) -> None:
        valid_payload["goals"] = []
        effects = self._run(db_fixtures, valid_payload)
        assert get_json_response(effects).status_code == 201

    def test_missing_optional_lists_succeeds(self, db_fixtures, valid_payload) -> None:
        for key in ("conditions", "goals", "action_items"):
            valid_payload.pop(key, None)
        effects = self._run(db_fixtures, valid_payload)
        assert get_json_response(effects).status_code == 201


# ---------------------------------------------------------------------------
# Command-building tests  (require real DB records via db_fixtures)
# ---------------------------------------------------------------------------

class TestCommandBuilding:
    def _commands(self, db_fixtures: dict, payload: dict) -> list:
        """Return the commands list by calling _build_commands directly."""
        handler = make_handler(payload=payload, note_type_id=db_fixtures["note_type_id"])
        note_uuid_str = str(uuid.uuid4())
        return handler._build_commands(note_uuid_str, payload)

    def test_hpi_command_contains_call_summary(self, db_fixtures, valid_payload) -> None:
        commands = self._commands(db_fixtures, valid_payload)
        hpi_cmds = [c for c in commands if isinstance(c, HistoryOfPresentIllnessCommand)]
        assert len(hpi_cmds) == 1
        assert hpi_cmds[0].narrative == valid_payload["call_summary"]

    def test_plan_command_contains_care_plan(self, db_fixtures, valid_payload) -> None:
        commands = self._commands(db_fixtures, valid_payload)
        plan_cmds = [c for c in commands if isinstance(c, PlanCommand)]
        assert len(plan_cmds) == 1
        assert valid_payload["care_plan"] in plan_cmds[0].narrative

    def test_action_items_appended_to_plan_narrative(self, db_fixtures, valid_payload) -> None:
        commands = self._commands(db_fixtures, valid_payload)
        plan_cmds = [c for c in commands if isinstance(c, PlanCommand)]
        assert "Schedule follow-up lab" in plan_cmds[0].narrative

    def test_single_condition_creates_one_assess_command(self, db_fixtures, valid_payload) -> None:
        commands = self._commands(db_fixtures, valid_payload)
        assert len([c for c in commands if isinstance(c, AssessCommand)]) == 1

    def test_multiple_conditions_create_multiple_assess_commands(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": "A"},
            {"condition_id": str(uuid.uuid4()), "status": "improved", "narrative": "B"},
        ]
        commands = self._commands(db_fixtures, valid_payload)
        assert len([c for c in commands if isinstance(c, AssessCommand)]) == 2

    def test_empty_conditions_no_assess_commands(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = []
        commands = self._commands(db_fixtures, valid_payload)
        assert len([c for c in commands if isinstance(c, AssessCommand)]) == 0

    def test_condition_status_stable_maps_correctly(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": ""}
        ]
        commands = self._commands(db_fixtures, valid_payload)
        assess = next(c for c in commands if isinstance(c, AssessCommand))
        assert assess.status == AssessCommand.Status.STABLE

    def test_condition_status_improved_maps_correctly(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "improved", "narrative": ""}
        ]
        commands = self._commands(db_fixtures, valid_payload)
        assess = next(c for c in commands if isinstance(c, AssessCommand))
        assert assess.status == AssessCommand.Status.IMPROVED

    def test_condition_status_deteriorated_maps_correctly(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "deteriorated", "narrative": ""}
        ]
        commands = self._commands(db_fixtures, valid_payload)
        assess = next(c for c in commands if isinstance(c, AssessCommand))
        assert assess.status == AssessCommand.Status.DETERIORATED

    def test_unknown_status_defaults_to_stable(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "unknown_status", "narrative": ""}
        ]
        commands = self._commands(db_fixtures, valid_payload)
        assess = next(c for c in commands if isinstance(c, AssessCommand))
        assert assess.status == AssessCommand.Status.STABLE

    def test_single_goal_creates_one_goal_command(self, db_fixtures, valid_payload) -> None:
        commands = self._commands(db_fixtures, valid_payload)
        goal_cmds = [c for c in commands if isinstance(c, GoalCommand)]
        assert len(goal_cmds) == 1
        assert goal_cmds[0].goal_statement == valid_payload["goals"][0]

    def test_multiple_goals_create_multiple_goal_commands(self, db_fixtures, valid_payload) -> None:
        valid_payload["goals"] = ["Goal A", "Goal B", "Goal C"]
        commands = self._commands(db_fixtures, valid_payload)
        assert len([c for c in commands if isinstance(c, GoalCommand)]) == 3

    def test_empty_goals_no_goal_commands(self, db_fixtures, valid_payload) -> None:
        valid_payload["goals"] = []
        commands = self._commands(db_fixtures, valid_payload)
        assert len([c for c in commands if isinstance(c, GoalCommand)]) == 0


# ---------------------------------------------------------------------------
# Task tests  (require real DB records via db_fixtures)
# ---------------------------------------------------------------------------

def _get_task_payload(effects: list) -> dict:
    """Find the CREATE_TASK effect and return its parsed payload dict."""
    for e in effects:
        if e.type == EffectType.CREATE_TASK:
            return json.loads(e.payload)["data"]
    raise AssertionError("No CREATE_TASK effect found in effects")


class TestTaskCreation:
    def _effects(self, db_fixtures: dict, payload: dict) -> list:
        handler = make_handler(payload=payload, note_type_id=db_fixtures["note_type_id"])
        return handler.ingest_call()

    def test_task_assigned_to_provider(self, db_fixtures, valid_payload) -> None:
        effects = self._effects(db_fixtures, valid_payload)
        task_data = _get_task_payload(effects)
        assert task_data["assignee"]["id"] == db_fixtures["provider_id"]

    def test_task_linked_to_patient(self, db_fixtures, valid_payload) -> None:
        effects = self._effects(db_fixtures, valid_payload)
        task_data = _get_task_payload(effects)
        assert task_data["patient"]["id"] == db_fixtures["patient_id"]

    def test_task_title_contains_note_uuid(self, db_fixtures, valid_payload) -> None:
        effects = self._effects(db_fixtures, valid_payload)
        note_id = response_body(get_json_response(effects))["note_id"]
        task_data = _get_task_payload(effects)
        assert note_id in task_data["title"]

    def test_task_status_is_open(self, db_fixtures, valid_payload) -> None:
        effects = self._effects(db_fixtures, valid_payload)
        task_data = _get_task_payload(effects)
        assert task_data["status"] == "OPEN"
