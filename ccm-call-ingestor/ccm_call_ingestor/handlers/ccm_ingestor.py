import uuid
from hmac import compare_digest

import arrow
from canvas_sdk.commands import (
    AssessCommand,
    GoalCommand,
    HistoryOfPresentIllnessCommand,
    PlanCommand,
)
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPI, api
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.patient import Patient
from logger import log

REQUIRED_FIELDS = frozenset(
    {
        "patient_id",
        "provider_id",
        "practice_location_id",
        "datetime_of_service",
        "call_summary",
        "care_plan",
    }
)

STATUS_MAP = {
    "stable": AssessCommand.Status.STABLE,
    "improved": AssessCommand.Status.IMPROVED,
    "deteriorated": AssessCommand.Status.DETERIORATED,
}


class CCMCallIngestor(SimpleAPI):
    """
    Receives processed CCM phone call data from an external microservice and
    creates a pre-populated encounter note for nurse review.

    Endpoint: POST /plugin-io/api/ccm-call-ingestor/ccm-ingest/calls
    Auth: Authorization header value must match the 'simpleapi-api-key' secret.

    Expected JSON payload:
    {
        "patient_id": "uuid",
        "provider_id": "uuid",
        "practice_location_id": "uuid",
        "datetime_of_service": "2024-01-15T14:30:00Z",
        "call_summary": "...",
        "care_plan": "...",
        "conditions": [
            {"condition_id": "uuid", "status": "stable", "narrative": "..."}
        ],
        "goals": ["Maintain BP <130/80"],
        "action_items": [
            {"title": "Schedule follow-up lab", "assignee": "nurse_id"}
        ]
    }
    """

    PREFIX = "/ccm-ingest"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        expected = self.secrets.get("simpleapi-api-key", "")
        provided = credentials.key
        if not expected:
            log.warning("[CCMCallIngestor] simpleapi-api-key secret is not configured")
            return False
        return compare_digest(provided.encode(), expected.encode())

    @api.post("/calls")
    def ingest_call(self) -> list[Response | Effect]:
        body = self.request.json()

        # Validate required fields
        missing = REQUIRED_FIELDS - body.keys()
        if missing:
            return [
                JSONResponse(
                    {"error": f"Missing required fields: {', '.join(sorted(missing))}"},
                    status_code=422,
                )
            ]

        # Validate datetime
        try:
            datetime_of_service = arrow.get(body["datetime_of_service"]).datetime
        except Exception:
            return [
                JSONResponse(
                    {"error": "Invalid datetime_of_service format"},
                    status_code=422,
                )
            ]

        # Validate conditions list entries (before DB lookups)
        for condition in body.get("conditions", []):
            if not condition.get("condition_id"):
                return [
                    JSONResponse(
                        {"error": "condition_id is required for each entry in conditions"},
                        status_code=422,
                    )
                ]

        # Validate patient exists
        try:
            Patient.objects.get(id=body["patient_id"])
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=404)]

        # Resolve note type
        note_type_id = self._resolve_note_type_id()
        if note_type_id is None:
            return [
                JSONResponse(
                    {"error": "Could not resolve note type; set NOTE_TYPE_ID secret or ensure 'Office visit' note type exists"},
                    status_code=500,
                )
            ]

        # Pre-generate note UUID so we can chain commands to the note being created
        note_uuid = uuid.uuid4()
        note_uuid_str = str(note_uuid)

        # Build note effect
        note_effect = NoteEffect(
            instance_id=note_uuid,
            note_type_id=note_type_id,
            datetime_of_service=datetime_of_service,
            patient_id=body["patient_id"],
            practice_location_id=body["practice_location_id"],
            provider_id=body["provider_id"],
        )

        # Build commands
        commands = self._build_commands(note_uuid_str, body)

        # Task for nurse review
        task = AddTask(
            assignee_id=body["provider_id"],
            author_id=body["provider_id"],
            patient_id=body["patient_id"],
            title=f"CCM call ready for nurse review — Note {note_uuid_str}",
            status=TaskStatus.OPEN,
        )

        log.info(f"[CCMCallIngestor] Creating encounter note {note_uuid_str} for patient {body['patient_id']}")

        return [
            note_effect.create(),
            BatchOriginateCommandEffect(commands=commands).apply(),
            task.apply(),
            JSONResponse({"note_id": note_uuid_str}, status_code=201),
        ]

    def _build_commands(self, note_uuid_str: str, body: dict) -> list:
        """Build the list of note commands from the parsed request body."""
        commands: list = []

        # HPI — call summary
        commands.append(
            HistoryOfPresentIllnessCommand(
                note_uuid=note_uuid_str,
                narrative=body["call_summary"],
            )
        )

        # Assess each chronic condition
        for condition in body.get("conditions", []):
            raw_status = condition.get("status", "").lower()
            if raw_status not in STATUS_MAP:
                log.warning(
                    f"[CCMCallIngestor] Unrecognized condition status '{raw_status}', defaulting to STABLE"
                )
            commands.append(
                AssessCommand(
                    note_uuid=note_uuid_str,
                    condition_id=condition["condition_id"],
                    status=STATUS_MAP.get(raw_status, AssessCommand.Status.STABLE),
                    narrative=condition.get("narrative", ""),
                )
            )

        # Plan — care plan narrative + action items appended
        care_plan_text = body["care_plan"]
        action_items = body.get("action_items", [])
        if action_items:
            items_text = "\n".join(
                f"- {item.get('title', '')} (assignee: {item.get('assignee', 'unassigned')})"
                for item in action_items
            )
            care_plan_text = f"{care_plan_text}\n\nAction Items:\n{items_text}"
        commands.append(PlanCommand(note_uuid=note_uuid_str, narrative=care_plan_text))

        # Goals
        for goal_text in body.get("goals", []):
            commands.append(GoalCommand(note_uuid=note_uuid_str, goal_statement=goal_text))

        return commands

    def _resolve_note_type_id(self) -> str | None:
        note_type_id = self.secrets.get("NOTE_TYPE_ID", "").strip()
        if note_type_id:
            return note_type_id
        try:
            note_type = NoteType.objects.get(name="Office visit", is_active=True)
            return str(note_type.id)
        except (NoteType.DoesNotExist, NoteType.MultipleObjectsReturned) as exc:
            log.error(f"[CCMCallIngestor] Failed to resolve note type: {exc}")
            return None
