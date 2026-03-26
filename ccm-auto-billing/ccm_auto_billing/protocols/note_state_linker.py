"""
CCMNoteStateLinker — updates CCM billing line items with diagnosis pointers
when the provider locks the encounter note.

Canvas only creates Assessment records after commands are committed (which
happens at lock time). This protocol fires on NOTE_STATE_CHANGE_EVENT_CREATED
with state "LKD" and calls UpdateBillingLineItem to link all assessments on
the note to the CCM/PCM billing line item, resolving the "missing diagnosis
pointer" claim validation error.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import UpdateBillingLineItem
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.v1.data.billing import BillingLineItem
from canvas_sdk.v1.data.note import Note
from logger import log

CCM_CPT_CODES = {"99490", "99424", "99491", "99426", "99427"}

# Canvas note state codes
_STATE_LOCKED = "LKD"


class CCMNoteStateLinker(BaseProtocol):
    """
    When a CCM encounter note is locked, update its billing line item(s) with
    the assessment IDs as diagnosis pointers so the claim passes validation.
    """

    RESPONDS_TO = [EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)]

    def compute(self) -> list[Effect]:
        state = self.event.context.get("state")
        if state != _STATE_LOCKED:
            return []

        note_id = self.event.context.get("note_id")
        if not note_id:
            return []

        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            log.warning(f"[CCMNoteStateLinker] Note {note_id} not found")
            return []

        # Only act on notes that have a CCM/PCM billing line item
        ccm_items = list(
            BillingLineItem.objects.filter(note=note, cpt__in=CCM_CPT_CODES)
        )
        if not ccm_items:
            return []

        # Get all assessment IDs committed to this note
        assessment_ids = [
            str(a_id)
            for a_id in Assessment.objects.filter(note_id=note.dbid).values_list("id", flat=True)
        ]

        if not assessment_ids:
            log.warning(
                f"[CCMNoteStateLinker] Note {note_id} has CCM billing but no assessments after lock — "
                "diagnosis pointers cannot be linked"
            )
            return []

        log.info(
            f"[CCMNoteStateLinker] Linking {len(assessment_ids)} assessment(s) to "
            f"{len(ccm_items)} CCM billing line item(s) on note {note_id}"
        )

        return [
            UpdateBillingLineItem(
                billing_line_item_id=str(item.id),
                assessment_ids=assessment_ids,
            ).apply()
            for item in ccm_items
        ]
