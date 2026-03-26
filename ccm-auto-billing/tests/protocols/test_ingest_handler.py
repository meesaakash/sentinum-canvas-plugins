"""
Tests for CCMAutoIngestor handler.

Run with: uv run pytest tests/ -v
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

from ccm_auto_billing.protocols.ingest_handler import (
    CCMAutoIngestor,
    _resolve_condition_uuid,
    _select_cpt,
    _validate_cpt_code,
    CPT_CCM,
    CPT_PCM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event_context(method: str = "POST", path: str = "/ccm/calls") -> dict:
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
) -> CCMAutoIngestor:
    """Instantiate CCMAutoIngestor with a mocked event and request."""
    mock_event = Mock()
    mock_event.context = make_event_context()
    handler = CCMAutoIngestor(
        event=mock_event,
        secrets={"simpleapi-api-key": api_key, "NOTE_TYPE_ID": note_type_id},
    )
    mock_request = Mock()
    mock_request.json.return_value = payload or {}
    handler.__dict__["request"] = mock_request
    return handler


def response_body(response: JSONResponse) -> dict:
    return json.loads(response.content)


def get_json_response(effects: list) -> JSONResponse:
    for e in effects:
        if isinstance(e, JSONResponse):
            return e
    raise AssertionError("No JSONResponse found in effects")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_fixtures():
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
    """Valid CCM payload with 3 conditions (→ CPT 99490)."""
    return {
        "patient_id": db_fixtures["patient_id"],
        "provider_id": db_fixtures["provider_id"],
        "practice_location_id": db_fixtures["practice_location_id"],
        "datetime_of_service": "2026-03-25T23:30:00Z",
        "call_summary": "Completed 20-min CCM call. Patient stable on all medications.",
        "care_plan": "Continue current regimen. Repeat HbA1c in 3 months.",
        "conditions": [
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": "DM stable"},
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": "HTN stable"},
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": "MDD stable"},
        ],
        "goals": ["Maintain HbA1c < 7.5%", "Keep BP < 130/80"],
        "action_items": [],
    }


# Patch that bypasses ChargeDescriptionMaster DB validation in success-path tests
_SKIP_CPT_VALIDATION = patch(
    "ccm_auto_billing.protocols.ingest_handler._validate_cpt_code",
    return_value=None,
)
# Patch that returns a fake UUID for condition resolution (integer → UUID)
_SKIP_CONDITION_RESOLVE = patch(
    "ccm_auto_billing.protocols.ingest_handler._resolve_condition_uuid",
    side_effect=lambda cid: f"00000000-0000-0000-0000-{str(cid).zfill(12)}",
)
# Patch that suppresses private note type lookup (returns None → skips private note)
_SKIP_PRIVATE_NOTE = patch.object(
    CCMAutoIngestor, "_resolve_private_note_type_id", return_value=None
)


# ---------------------------------------------------------------------------
# CPT selection logic
# ---------------------------------------------------------------------------

class TestSelectCpt:
    def test_zero_conditions_returns_ccm(self) -> None:
        assert _select_cpt([]) == CPT_CCM

    def test_one_condition_returns_pcm(self) -> None:
        assert _select_cpt([{"condition_id": "x"}]) == CPT_PCM

    def test_two_conditions_returns_ccm(self) -> None:
        assert _select_cpt([{"condition_id": "a"}, {"condition_id": "b"}]) == CPT_CCM

    def test_three_conditions_returns_ccm(self) -> None:
        assert _select_cpt([{"condition_id": str(uuid.uuid4())} for _ in range(3)]) == CPT_CCM


# ---------------------------------------------------------------------------
# Authentication
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
        handler = CCMAutoIngestor(event=mock_event, secrets={})
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = "any-key"
        assert handler.authenticate(credentials) is False

    def test_empty_secret_returns_false(self) -> None:
        mock_event = Mock()
        mock_event.context = make_event_context()
        handler = CCMAutoIngestor(event=mock_event, secrets={"simpleapi-api-key": ""})
        credentials = Mock(spec=APIKeyCredentials)
        credentials.key = ""
        assert handler.authenticate(credentials) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_patient_id_returns_422(self) -> None:
        payload = {
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2026-03-25T23:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload)
        response = get_json_response(handler.ingest_call())
        assert response.status_code == 422
        assert "patient_id" in response_body(response)["error"]

    def test_multiple_missing_fields_all_listed(self) -> None:
        payload = {
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2026-03-25T23:30:00Z",
            "call_summary": "Summary.",
        }
        handler = make_handler(payload)
        response = get_json_response(handler.ingest_call())
        assert response.status_code == 422
        body = response_body(response)["error"]
        assert "care_plan" in body
        assert "patient_id" in body

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
        with patch("ccm_auto_billing.protocols.ingest_handler.Patient"):
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 422
        assert "datetime_of_service" in response_body(response)["error"]

    def test_unknown_patient_returns_404(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2026-03-25T23:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload)
        with patch("ccm_auto_billing.protocols.ingest_handler.Patient") as mock_patient:
            mock_patient.DoesNotExist = Exception
            mock_patient.objects.get.side_effect = mock_patient.DoesNotExist("not found")
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 404
        assert "Patient not found" in response_body(response)["error"]

    def test_condition_missing_id_returns_422(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2026-03-25T23:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
            "conditions": [{"status": "stable", "narrative": "no id here"}],
        }
        handler = make_handler(payload)
        with patch("ccm_auto_billing.protocols.ingest_handler.Patient"):
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 422
        assert "condition_id" in response_body(response)["error"]

    def test_unresolvable_note_type_returns_500(self) -> None:
        payload = {
            "patient_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "datetime_of_service": "2026-03-25T23:30:00Z",
            "call_summary": "Summary.",
            "care_plan": "Plan.",
        }
        handler = make_handler(payload=payload, note_type_id="")
        with (
            patch("ccm_auto_billing.protocols.ingest_handler.Patient"),
            patch.object(handler, "_resolve_note_type_id", return_value=None),
            _SKIP_CPT_VALIDATION,
            _SKIP_CONDITION_RESOLVE,
            _SKIP_PRIVATE_NOTE,
        ):
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Note type resolution
# ---------------------------------------------------------------------------

class TestResolveNoteType:
    def test_secret_id_is_returned_directly(self) -> None:
        custom_id = str(uuid.uuid4())
        handler = make_handler(note_type_id=custom_id)
        assert handler._resolve_note_type_id() == custom_id

    def test_falls_back_to_db_lookup(self) -> None:
        fallback_id = str(uuid.uuid4())
        handler = make_handler(note_type_id="")
        with patch("ccm_auto_billing.protocols.ingest_handler.NoteType") as mock_nt:
            mock_nt.objects.get.return_value = Mock(id=fallback_id)
            result = handler._resolve_note_type_id()
        assert result == fallback_id
        mock_nt.objects.get.assert_called_once_with(name="Office visit", is_active=True)

    def test_db_lookup_failure_returns_none(self) -> None:
        handler = make_handler(note_type_id="")
        with patch("ccm_auto_billing.protocols.ingest_handler.NoteType") as mock_nt:
            mock_nt.DoesNotExist = Exception
            mock_nt.MultipleObjectsReturned = ValueError
            mock_nt.objects.get.side_effect = mock_nt.DoesNotExist("not found")
            assert handler._resolve_note_type_id() is None


# ---------------------------------------------------------------------------
# Happy-path / billing
# ---------------------------------------------------------------------------

class TestSuccessfulIngest:
    def _run(self, db_fixtures: dict, payload: dict) -> list:
        handler = make_handler(payload=payload, note_type_id=db_fixtures["note_type_id"])
        with _SKIP_CPT_VALIDATION, _SKIP_CONDITION_RESOLVE, _SKIP_PRIVATE_NOTE:
            return handler.ingest_call()

    def test_returns_201(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        assert get_json_response(effects).status_code == 201

    def test_response_includes_note_id(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        body = response_body(get_json_response(effects))
        uuid.UUID(body["note_id"])  # must be a valid UUID

    def test_response_includes_cpt_code(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        body = response_body(get_json_response(effects))
        assert "cpt_code" in body

    def test_three_conditions_returns_99490(self, db_fixtures, valid_payload) -> None:
        assert len(valid_payload["conditions"]) == 3
        effects = self._run(db_fixtures, valid_payload)
        assert response_body(get_json_response(effects))["cpt_code"] == CPT_CCM

    def test_one_condition_returns_99424(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "stable", "narrative": "HTN"}
        ]
        effects = self._run(db_fixtures, valid_payload)
        assert response_body(get_json_response(effects))["cpt_code"] == CPT_PCM

    def test_zero_conditions_returns_99490(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = []
        effects = self._run(db_fixtures, valid_payload)
        assert response_body(get_json_response(effects))["cpt_code"] == CPT_CCM

    def test_five_effects_returned(self, db_fixtures, valid_payload) -> None:
        # NoteEffect.create(), BatchOriginate.apply(), AddBillingLineItem.apply(),
        # AddTask.apply(), JSONResponse
        effects = self._run(db_fixtures, valid_payload)
        assert len(effects) == 5

    def test_billing_line_item_effect_present(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        billing_effects = [
            e for e in effects
            if hasattr(e, "type") and e.type == EffectType.ADD_BILLING_LINE_ITEM
        ]
        assert len(billing_effects) == 1

    def test_billing_line_item_contains_cpt_code(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        billing_effects = [
            e for e in effects
            if hasattr(e, "type") and e.type == EffectType.ADD_BILLING_LINE_ITEM
        ]
        payload_data = json.loads(billing_effects[0].payload)
        assert payload_data["data"]["cpt"] == CPT_CCM

    def test_billing_line_item_has_no_assessment_ids_at_creation(self, db_fixtures, valid_payload) -> None:
        """At creation time, assessment_ids should be empty — CCMNoteStateLinker links them at lock."""
        effects = self._run(db_fixtures, valid_payload)
        billing_effects = [
            e for e in effects
            if hasattr(e, "type") and e.type == EffectType.ADD_BILLING_LINE_ITEM
        ]
        payload_data = json.loads(billing_effects[0].payload)
        assert payload_data["data"]["assessment_ids"] == []

    def test_note_uuid_consistent_across_effects(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        note_id = response_body(get_json_response(effects))["note_id"]
        found = any(
            hasattr(e, "payload") and isinstance(e.payload, str) and note_id in e.payload
            for e in effects
        )
        assert found, f"note_id {note_id} not found in any effect payload"

    def test_task_title_contains_short_note_id_cpt_and_service_date(self, db_fixtures, valid_payload) -> None:
        effects = self._run(db_fixtures, valid_payload)
        note_id = response_body(get_json_response(effects))["note_id"]
        task_effects = [
            e for e in effects
            if hasattr(e, "type") and e.type == EffectType.CREATE_TASK
        ]
        assert len(task_effects) == 1
        title = json.loads(task_effects[0].payload)["data"]["title"]
        assert note_id[:8] in title          # short note ID
        assert CPT_CCM in title              # CPT code
        assert "2026-03-25" in title         # service date from payload
        assert "[CCM Review]" in title       # prefix tag


# ---------------------------------------------------------------------------
# CPT validation
# ---------------------------------------------------------------------------

class TestCPTValidation:
    def test_invalid_cpt_returns_422(self, db_fixtures, valid_payload) -> None:
        handler = make_handler(payload=valid_payload, note_type_id=db_fixtures["note_type_id"])
        with (
            patch(
                "ccm_auto_billing.protocols.ingest_handler._validate_cpt_code",
                return_value="CPT code '99490' not found in ChargeDescriptionMaster",
            ),
        ):
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 422
        assert "99490" in response_body(response)["error"]

    def test_valid_cpt_does_not_block_request(self, db_fixtures, valid_payload) -> None:
        handler = make_handler(payload=valid_payload, note_type_id=db_fixtures["note_type_id"])
        with _SKIP_CPT_VALIDATION, _SKIP_CONDITION_RESOLVE, _SKIP_PRIVATE_NOTE:
            response = get_json_response(handler.ingest_call())
        assert response.status_code == 201

    def test_validate_cpt_code_returns_none_for_valid_code(self) -> None:
        from datetime import date, timedelta
        mock_cdm = Mock()
        mock_cdm.end_date = None
        mock_cdm.effective_date = date.today() - timedelta(days=1)
        with patch("ccm_auto_billing.protocols.ingest_handler.ChargeDescriptionMaster") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = mock_cdm
            assert _validate_cpt_code("99490") is None

    def test_validate_cpt_code_returns_none_for_unknown_code(self) -> None:
        """Unknown CPT codes log a warning but don't block the request."""
        with patch("ccm_auto_billing.protocols.ingest_handler.ChargeDescriptionMaster") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = None
            assert _validate_cpt_code("XXXXX") is None

    def test_validate_cpt_code_returns_error_for_expired_code(self) -> None:
        from datetime import date, timedelta
        mock_cdm = Mock()
        mock_cdm.end_date = date.today() - timedelta(days=1)
        mock_cdm.effective_date = None
        with patch("ccm_auto_billing.protocols.ingest_handler.ChargeDescriptionMaster") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = mock_cdm
            result = _validate_cpt_code("99490")
        assert result is not None
        assert "expired" in result.lower()

    def test_validate_cpt_code_returns_error_for_future_effective_date(self) -> None:

        from datetime import date, timedelta
        mock_cdm = Mock()
        mock_cdm.end_date = None
        mock_cdm.effective_date = date.today() + timedelta(days=30)
        with patch("ccm_auto_billing.protocols.ingest_handler.ChargeDescriptionMaster") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = mock_cdm
            result = _validate_cpt_code("99490")
        assert result is not None
        assert "not yet effective" in result.lower()


# ---------------------------------------------------------------------------
# Condition UUID resolution
# ---------------------------------------------------------------------------

class TestResolveConditionUUID:
    def test_integer_id_is_resolved_via_db(self) -> None:
        fake_uuid = str(uuid.uuid4())
        with patch("ccm_auto_billing.protocols.ingest_handler.Condition") as mock_cond:
            mock_cond.objects.filter.return_value.values_list.return_value.first.return_value = fake_uuid
            result = _resolve_condition_uuid("42")
        assert result == fake_uuid

    def test_uuid_string_is_returned_as_is(self) -> None:
        existing_uuid = str(uuid.uuid4())
        assert _resolve_condition_uuid(existing_uuid) == existing_uuid

    def test_empty_string_returns_none(self) -> None:
        assert _resolve_condition_uuid("") is None

    def test_db_miss_returns_none(self) -> None:
        with patch("ccm_auto_billing.protocols.ingest_handler.Condition") as mock_cond:
            mock_cond.objects.filter.return_value.values_list.return_value.first.return_value = None
            assert _resolve_condition_uuid("99") is None


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

class TestCommandBuilding:
    def _commands(self, db_fixtures: dict, payload: dict) -> list:
        handler = make_handler(payload=payload, note_type_id=db_fixtures["note_type_id"])
        with _SKIP_CONDITION_RESOLVE:
            return handler._build_encounter_commands(str(uuid.uuid4()), payload)

    def test_hpi_contains_call_summary(self, db_fixtures, valid_payload) -> None:
        cmds = self._commands(db_fixtures, valid_payload)
        hpi = [c for c in cmds if isinstance(c, HistoryOfPresentIllnessCommand)]
        assert len(hpi) == 1
        assert hpi[0].narrative == valid_payload["call_summary"]

    def test_plan_contains_care_plan(self, db_fixtures, valid_payload) -> None:
        cmds = self._commands(db_fixtures, valid_payload)
        plans = [c for c in cmds if isinstance(c, PlanCommand)]
        assert len(plans) == 1
        assert valid_payload["care_plan"] in plans[0].narrative

    def test_action_items_appended_to_plan(self, db_fixtures, valid_payload) -> None:
        valid_payload["action_items"] = [{"title": "Order HbA1c", "assignee": "nurse"}]
        cmds = self._commands(db_fixtures, valid_payload)
        plan = next(c for c in cmds if isinstance(c, PlanCommand))
        assert "Order HbA1c" in plan.narrative

    def test_assess_count_matches_conditions(self, db_fixtures, valid_payload) -> None:
        cmds = self._commands(db_fixtures, valid_payload)
        assert len([c for c in cmds if isinstance(c, AssessCommand)]) == 3

    def test_unknown_status_defaults_to_stable(self, db_fixtures, valid_payload) -> None:
        valid_payload["conditions"] = [
            {"condition_id": str(uuid.uuid4()), "status": "BOGUS", "narrative": ""}
        ]
        cmds = self._commands(db_fixtures, valid_payload)
        assess = next(c for c in cmds if isinstance(c, AssessCommand))
        assert assess.status == AssessCommand.Status.STABLE

    def test_goal_commands_match_goals(self, db_fixtures, valid_payload) -> None:
        cmds = self._commands(db_fixtures, valid_payload)
        goals = [c for c in cmds if isinstance(c, GoalCommand)]
        assert len(goals) == len(valid_payload["goals"])
        texts = {g.goal_statement for g in goals}
        assert texts == set(valid_payload["goals"])
