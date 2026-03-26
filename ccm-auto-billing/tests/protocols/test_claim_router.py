"""
Tests for CCMClaimRouter handler.

Run with: uv run pytest tests/ -v
"""

import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType

from ccm_auto_billing.protocols.claim_router import CCMClaimRouter, CCM_CPT_CODES, SUBMISSION_QUEUE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_router(claim_id: str | None = None, note_id: str | None = None) -> CCMClaimRouter:
    """Create a CCMClaimRouter with a mocked CLAIM_CREATED event."""
    mock_claim = Mock()
    mock_claim.id = claim_id or str(uuid.uuid4())
    mock_claim.note = Mock(id=note_id or str(uuid.uuid4()))

    mock_event = Mock()
    mock_event.target.instance = mock_claim

    return CCMClaimRouter(event=mock_event, secrets={})


# Patch that bypasses _MoveClaimToQueue DB validation (Claim/ClaimQueue existence checks)
_SKIP_QUEUE_VALIDATION = patch(
    "canvas_sdk.effects.claim.claim_queue._MoveClaimToQueue._get_error_details",
    return_value=[],
)


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

class TestCCMClaimRouter:
    def test_ccm_claim_is_routed_to_submission_queue(self) -> None:
        router = make_router()
        with (
            patch("ccm_auto_billing.protocols.claim_router.BillingLineItem") as mock_bli,
            _SKIP_QUEUE_VALIDATION,
        ):
            mock_bli.objects.filter.return_value.exists.return_value = True
            mock_bli.objects.filter.return_value.values_list.return_value.first.return_value = "99490"
            effects = router.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.MOVE_CLAIM_TO_QUEUE

    def test_non_ccm_claim_returns_no_effects(self) -> None:
        router = make_router()
        with patch("ccm_auto_billing.protocols.claim_router.BillingLineItem") as mock_bli:
            mock_bli.objects.filter.return_value.exists.return_value = False
            effects = router.compute()

        assert effects == []

    def test_move_to_queue_payload_contains_claim_id(self) -> None:
        import json
        claim_id = str(uuid.uuid4())
        router = make_router(claim_id=claim_id)
        with (
            patch("ccm_auto_billing.protocols.claim_router.BillingLineItem") as mock_bli,
            _SKIP_QUEUE_VALIDATION,
        ):
            mock_bli.objects.filter.return_value.exists.return_value = True
            mock_bli.objects.filter.return_value.values_list.return_value.first.return_value = "99490"
            effects = router.compute()

        payload = json.loads(effects[0].payload)
        assert claim_id in str(payload)

    @pytest.mark.parametrize("cpt", sorted(CCM_CPT_CODES))
    def test_all_ccm_cpt_codes_trigger_routing(self, cpt: str) -> None:
        router = make_router()
        with (
            patch("ccm_auto_billing.protocols.claim_router.BillingLineItem") as mock_bli,
            _SKIP_QUEUE_VALIDATION,
        ):
            mock_bli.objects.filter.return_value.exists.return_value = True
            mock_bli.objects.filter.return_value.values_list.return_value.first.return_value = cpt
            effects = router.compute()
        assert len(effects) == 1, f"Expected routing for CPT {cpt}"

    def test_billing_line_item_queried_with_ccm_codes(self) -> None:
        router = make_router()
        with patch("ccm_auto_billing.protocols.claim_router.BillingLineItem") as mock_bli:
            mock_bli.objects.filter.return_value.exists.return_value = False
            router.compute()
            call_kwargs = mock_bli.objects.filter.call_args[1]
            assert set(call_kwargs.get("cpt__in", [])) == CCM_CPT_CODES

    def test_responds_to_claim_created_event(self) -> None:
        from canvas_sdk.events import EventType
        assert "CLAIM_CREATED" in CCMClaimRouter.RESPONDS_TO
