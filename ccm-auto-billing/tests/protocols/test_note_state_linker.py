"""Tests for CCMNoteStateLinker — links diagnosis pointers when note is locked."""

import json
import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType

from ccm_auto_billing.protocols.note_state_linker import CCMNoteStateLinker


def make_linker(note_id: str, state: str) -> CCMNoteStateLinker:
    mock_event = Mock()
    mock_event.context = {"note_id": note_id, "state": state}
    return CCMNoteStateLinker(event=mock_event, secrets={})


class TestCCMNoteStateLinker:
    def test_non_locked_state_returns_no_effects(self) -> None:
        linker = make_linker(str(uuid.uuid4()), "SGN")
        assert linker.compute() == []

    def test_locked_state_with_no_ccm_billing_returns_no_effects(self) -> None:
        linker = make_linker(str(uuid.uuid4()), "LKD")
        with (
            patch("ccm_auto_billing.protocols.note_state_linker.Note") as mock_note_cls,
            patch("ccm_auto_billing.protocols.note_state_linker.BillingLineItem") as mock_bli,
        ):
            mock_note_cls.objects.get.return_value = Mock(dbid=1)
            mock_bli.objects.filter.return_value = []  # no CCM items
            assert linker.compute() == []

    def test_locked_state_with_ccm_billing_and_assessments_updates_line_items(self) -> None:
        note_id = str(uuid.uuid4())
        billing_item_id = str(uuid.uuid4())
        assessment_id = str(uuid.uuid4())
        linker = make_linker(note_id, "LKD")

        mock_note = Mock()
        mock_note.dbid = 1

        mock_item = Mock()
        mock_item.id = billing_item_id

        with (
            patch("ccm_auto_billing.protocols.note_state_linker.Note") as mock_note_cls,
            patch("ccm_auto_billing.protocols.note_state_linker.BillingLineItem") as mock_bli,
            patch("ccm_auto_billing.protocols.note_state_linker.Assessment") as mock_assess,
            patch(
                "ccm_auto_billing.protocols.note_state_linker._MoveClaimToQueue._get_error_details",
                return_value=[],
            ) if False else patch("builtins.id", side_effect=lambda x: x),  # noop placeholder
        ):
            mock_note_cls.objects.get.return_value = mock_note
            mock_bli.objects.filter.return_value = [mock_item]
            mock_assess.objects.filter.return_value.values_list.return_value = [assessment_id]

            effects = linker.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.UPDATE_BILLING_LINE_ITEM

    def test_locked_state_with_ccm_billing_but_no_assessments_returns_no_effects(self) -> None:
        linker = make_linker(str(uuid.uuid4()), "LKD")
        mock_note = Mock()
        mock_note.dbid = 1
        mock_item = Mock()
        mock_item.id = str(uuid.uuid4())

        with (
            patch("ccm_auto_billing.protocols.note_state_linker.Note") as mock_note_cls,
            patch("ccm_auto_billing.protocols.note_state_linker.BillingLineItem") as mock_bli,
            patch("ccm_auto_billing.protocols.note_state_linker.Assessment") as mock_assess,
        ):
            mock_note_cls.objects.get.return_value = mock_note
            mock_bli.objects.filter.return_value = [mock_item]
            mock_assess.objects.filter.return_value.values_list.return_value = []
            assert linker.compute() == []

    def test_responds_to_note_state_change_event(self) -> None:
        from canvas_sdk.events import EventType
        assert "NOTE_STATE_CHANGE_EVENT_CREATED" in CCMNoteStateLinker.RESPONDS_TO
