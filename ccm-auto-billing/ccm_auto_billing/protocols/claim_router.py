from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim.claim import ClaimEffect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.billing import BillingLineItem
from logger import log

# All CCM/PCM CPT codes we auto-route to submission
CCM_CPT_CODES = {"99490", "99424", "99491", "99426", "99427"}

# Canvas billing queue name for electronic claim submission
SUBMISSION_QUEUE = "QUEUED_FOR_SUBMISSION"


class CCMClaimRouter(BaseProtocol):
    """
    Listens for newly created claims and auto-routes any claim that contains
    a CCM or PCM billing line item (99490, 99424, 99491, 99426, 99427) to
    the QUEUED_FOR_SUBMISSION queue.

    Billing flow:
      1. Provider reviews CCM encounter note, signs, and pushes charges.
      2. Canvas creates a Claim from the pushed BillingLineItems.
      3. CLAIM_CREATED fires → this handler checks the claim's line items.
      4. If a CCM/PCM CPT code is found, the claim is moved to QUEUED_FOR_SUBMISSION.
    """

    RESPONDS_TO = [EventType.Name(EventType.CLAIM_CREATED)]

    def compute(self) -> list[Effect]:
        claim = self.event.target.instance

        # Check if the claim has any CCM/PCM billing line items
        has_ccm = BillingLineItem.objects.filter(
            note=claim.note, cpt__in=CCM_CPT_CODES
        ).exists()

        if not has_ccm:
            return []

        cpt_found = (
            BillingLineItem.objects.filter(note=claim.note, cpt__in=CCM_CPT_CODES)
            .values_list("cpt", flat=True)
            .first()
        )
        log.info(
            f"[CCMClaimRouter] Claim {claim.id} contains CCM/PCM CPT {cpt_found} — "
            f"routing to {SUBMISSION_QUEUE}"
        )

        return [ClaimEffect(claim_id=claim.id).move_to_queue(SUBMISSION_QUEUE)]
