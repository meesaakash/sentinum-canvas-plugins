import uuid
from datetime import date
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
from canvas_sdk.effects.billing_line_item.add_billing_line_item import AddBillingLineItem
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPI, api
from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
from canvas_sdk.v1.data.condition import Condition
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

# CPT codes for CCM/PCM services
CPT_CCM = "99490"   # Chronic Care Management: 2+ chronic conditions, first 30 min/month
CPT_PCM = "99424"   # Principal Care Management: 1 complex chronic condition, first 30 min/month

# Private note type names to try in order
_PRIVATE_NOTE_TYPE_NAMES = ["Private note", "Message", "Letter", "Internal note"]


def _select_cpt(conditions: list) -> str:
    """Return 99490 (CCM) for 2+ conditions, 99424 (PCM) for exactly 1."""
    return CPT_CCM if len(conditions) != 1 else CPT_PCM


def _validate_cpt_code(cpt_code: str) -> str | None:
    """
    Validate CPT code against ChargeDescriptionMaster.
    Returns an error message string if invalid, or None if valid.
    Skips validation (returns None) if CDM table is empty or unavailable.
    """
    today = date.today()
    try:
        cdm = ChargeDescriptionMaster.objects.filter(cpt_code=cpt_code).first()
    except Exception as exc:
        log.warning(f"[CCMAutoIngestor] CPT validation skipped — CDM query failed: {exc}")
        return None
    if cdm is None:
        log.warning(f"[CCMAutoIngestor] CPT code '{cpt_code}' not found in ChargeDescriptionMaster — proceeding anyway")
        return None
    if cdm.end_date and cdm.end_date < today:
        return f"CPT code '{cpt_code}' is expired (end date: {cdm.end_date})"
    if cdm.effective_date and cdm.effective_date > today:
        return f"CPT code '{cpt_code}' is not yet effective (effective date: {cdm.effective_date})"
    return None


def _resolve_condition_uuid(condition_id: str) -> str | None:
    """
    Canvas FHIR returns integer dbids for conditions (e.g. "2", "17").
    AssessCommand.condition_id requires the externally exposable UUID.
    Convert integer dbid → UUID. If already a UUID (has dashes), return as-is.
    """
    if not condition_id:
        return None
    if "-" in str(condition_id):
        return str(condition_id)  # already a UUID
    try:
        cond_uuid = (
            Condition.objects.filter(dbid=int(condition_id))
            .values_list("id", flat=True)
            .first()
        )
        return str(cond_uuid) if cond_uuid else None
    except Exception as exc:
        log.warning(f"[CCMAutoIngestor] Could not resolve condition UUID for id={condition_id}: {exc}")
        return None


class CCMAutoIngestor(SimpleAPI):
    """
    Receives processed CCM/PCM phone call data and creates a pre-populated
    encounter note with a billing line item for automated claim generation.

    Endpoint: POST /plugin-io/api/ccm_auto_billing/ccm/calls
    Auth: Authorization header value must match the 'simpleapi-api-key' secret.

    CPT auto-selection:
      - 2+ conditions → 99490 (Chronic Care Management)
      - 1 condition   → 99424 (Principal Care Management)
    """

    PREFIX = "/ccm"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        expected = self.secrets.get("simpleapi-api-key", "")
        provided = credentials.key
        if not expected:
            log.warning("[CCMAutoIngestor] simpleapi-api-key secret is not configured")
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

        # Validate condition entries have condition_id
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

        # Resolve encounter note type
        note_type_id = self._resolve_note_type_id()
        if note_type_id is None:
            return [
                JSONResponse(
                    {"error": "Could not resolve note type; set NOTE_TYPE_ID secret or ensure 'Office visit' note type exists"},
                    status_code=500,
                )
            ]

        # Pre-generate note UUIDs so we can chain commands to each note
        note_uuid = uuid.uuid4()
        note_uuid_str = str(note_uuid)
        private_note_uuid = uuid.uuid4()
        private_note_uuid_str = str(private_note_uuid)

        # Select CPT code based on condition count
        conditions = body.get("conditions", [])
        cpt_code = _select_cpt(conditions)

        # Validate CPT code against ChargeDescriptionMaster
        cpt_error = _validate_cpt_code(cpt_code)
        if cpt_error:
            log.error(f"[CCMAutoIngestor] CPT validation failed: {cpt_error}")
            return [JSONResponse({"error": cpt_error}, status_code=422)]

        # Build encounter note + commands
        note_effect = NoteEffect(
            instance_id=note_uuid,
            note_type_id=note_type_id,
            datetime_of_service=datetime_of_service,
            patient_id=body["patient_id"],
            practice_location_id=body["practice_location_id"],
            provider_id=body["provider_id"],
        )
        encounter_commands = self._build_encounter_commands(note_uuid_str, body)

        # Billing line item — assessment_ids left empty here; CCMNoteStateLinker
        # will update them with diagnosis pointers when the note is locked.
        billing_item = AddBillingLineItem(
            note_id=note_uuid_str,
            cpt=cpt_code,
            units=1,
        )

        # Private note — call summary + care plan for internal reference
        effects: list[Response | Effect] = [
            note_effect.create(),
            BatchOriginateCommandEffect(commands=encounter_commands).apply(),
            billing_item.apply(),
        ]

        private_note_effects = self._build_private_note_effects(
            private_note_uuid_str, body, datetime_of_service, cpt_code
        )
        effects.extend(private_note_effects)

        # Task for provider review
        service_dt = datetime_of_service.strftime("%Y-%m-%d %H:%M UTC")
        condition_count = len(conditions)
        short_note_id = note_uuid_str[:8]
        task = AddTask(
            assignee_id=body["provider_id"],
            author_id=body["provider_id"],
            patient_id=body["patient_id"],
            title=(
                f"[CCM Review] {service_dt} — {cpt_code} ({condition_count} condition{'s' if condition_count != 1 else ''}) "
                f"| Note {short_note_id} | Review, Lock → Sign → Push Charges to submit claim"
            ),
            status=TaskStatus.OPEN,
        )
        effects.append(task.apply())
        effects.append(JSONResponse({"note_id": note_uuid_str, "cpt_code": cpt_code}, status_code=201))

        log.info(
            f"[CCMAutoIngestor] Created encounter note {note_uuid_str} + private note "
            f"for patient {body['patient_id']} with CPT {cpt_code}"
        )
        return effects

    def _build_encounter_commands(self, note_uuid_str: str, body: dict) -> list:
        """Build the structured clinical commands for the encounter note."""
        commands: list = []

        # HPI — call summary
        commands.append(
            HistoryOfPresentIllnessCommand(
                note_uuid=note_uuid_str,
                narrative=body["call_summary"],
            )
        )

        # Assess each chronic condition — resolve integer dbid → UUID for AssessCommand
        for condition in body.get("conditions", []):
            raw_id = condition.get("condition_id", "")
            condition_uuid = _resolve_condition_uuid(str(raw_id))
            if not condition_uuid:
                log.warning(
                    f"[CCMAutoIngestor] Could not resolve condition UUID for id={raw_id}, skipping AssessCommand"
                )
                continue
            raw_status = condition.get("status", "").lower()
            if raw_status not in STATUS_MAP:
                log.warning(
                    f"[CCMAutoIngestor] Unrecognized condition status '{raw_status}', defaulting to STABLE"
                )
            commands.append(
                AssessCommand(
                    note_uuid=note_uuid_str,
                    condition_id=condition_uuid,
                    status=STATUS_MAP.get(raw_status, AssessCommand.Status.STABLE),
                    narrative=condition.get("narrative", ""),
                )
            )

        # Plan — care plan narrative + action items
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

    def _build_private_note_effects(
        self,
        private_note_uuid_str: str,
        body: dict,
        datetime_of_service,
        cpt_code: str,
    ) -> list:
        """
        Create a private/internal note containing the full CCM call summary and care plan.
        Returns [] if no suitable private note type is found on this Canvas instance.
        """
        private_note_type_id = self._resolve_private_note_type_id()
        if not private_note_type_id:
            log.warning("[CCMAutoIngestor] No private note type found — skipping private note creation")
            return []

        private_note_effect = NoteEffect(
            instance_id=private_note_uuid_str,
            note_type_id=private_note_type_id,
            datetime_of_service=datetime_of_service,
            patient_id=body["patient_id"],
            practice_location_id=body["practice_location_id"],
            provider_id=body["provider_id"],
            title=f"CCM Call Note — {cpt_code} — {datetime_of_service.strftime('%Y-%m-%d')}",
        )

        condition_count = len(body.get("conditions", []))
        narrative = (
            f"CCM Telephone Encounter — {cpt_code} "
            f"({condition_count} chronic condition{'s' if condition_count != 1 else ''})\n\n"
            f"=== CALL SUMMARY ===\n{body['call_summary']}\n\n"
            f"=== CARE PLAN ===\n{body['care_plan']}"
        )
        if body.get("goals"):
            goals_text = "\n".join(f"• {g}" for g in body["goals"])
            narrative += f"\n\n=== GOALS ===\n{goals_text}"

        hpi_command = HistoryOfPresentIllnessCommand(
            note_uuid=private_note_uuid_str,
            narrative=narrative,
        )

        return [
            private_note_effect.create(),
            BatchOriginateCommandEffect(commands=[hpi_command]).apply(),
        ]

    def _resolve_note_type_id(self) -> str | None:
        note_type_id = self.secrets.get("NOTE_TYPE_ID", "").strip()
        if note_type_id:
            return note_type_id
        try:
            note_type = NoteType.objects.get(name="Office visit", is_active=True)
            return str(note_type.id)
        except (NoteType.DoesNotExist, NoteType.MultipleObjectsReturned) as exc:
            log.error(f"[CCMAutoIngestor] Failed to resolve note type: {exc}")
            return None

    def _resolve_private_note_type_id(self) -> str | None:
        """
        Look up a suitable private/internal note type by trying common names in order.
        Override with PRIVATE_NOTE_TYPE_ID secret to pin a specific type.

        NoteEffect.create() rejects APPOINTMENT, SCHEDULE_EVENT, MESSAGE, and LETTER
        categories — only query types with allowed categories.
        """
        pinned = self.secrets.get("PRIVATE_NOTE_TYPE_ID", "").strip()
        if pinned:
            return pinned
        # Only categories that NoteEffect.create() accepts
        allowed_categories = ["review", "encounter", "inpatient", "data"]
        for name in _PRIVATE_NOTE_TYPE_NAMES:
            try:
                nt = (
                    NoteType.objects
                    .filter(name=name, is_active=True, category__in=allowed_categories)
                    .values_list("id", flat=True)
                    .first()
                )
                if nt:
                    log.info(f"[CCMAutoIngestor] Using private note type: '{name}'")
                    return str(nt)
            except Exception:
                continue
        return None
