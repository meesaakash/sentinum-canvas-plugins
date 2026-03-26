# CCM Auto-Billing Plugin

Automates CCM/PCM encounter note creation and claim routing for automated phone call workflows.

## What It Does

1. **Ingest call data** — `POST /plugin-io/api/ccm-auto-billing/ccm/calls`
   Creates a pre-populated encounter note (HPI, condition assessments, care plan, goals) with an attached CPT billing line item.

2. **Auto-select CPT code**
   - 2+ chronic conditions → **99490** (Chronic Care Management)
   - 1 complex condition → **99424** (Principal Care Management)

3. **Auto-route claims** — listens for `CLAIM_CREATED`
   When a provider signs and pushes charges on a CCM/PCM note, the resulting claim is automatically moved to `QUEUED_FOR_SUBMISSION`.

## Billing Flow

```
Automated call → POST /ccm/calls
    → Note (NEW) + BillingLineItem (99490/99424) + Task
    → Provider reviews, signs, pushes charges
    → Canvas creates Claim
    → CLAIM_CREATED fires → moved to QUEUED_FOR_SUBMISSION
```

## Secrets

| Secret | Description |
|--------|-------------|
| `simpleapi-api-key` | API key for authenticating ingest requests |
| `NOTE_TYPE_ID` | (Optional) Override note type UUID; defaults to `Office visit` |

## API Payload

```json
{
  "patient_id": "uuid",
  "provider_id": "uuid",
  "practice_location_id": "uuid",
  "datetime_of_service": "2026-03-25T23:30:00Z",
  "call_summary": "...",
  "care_plan": "...",
  "conditions": [
    {"condition_id": "uuid", "status": "stable", "narrative": "..."}
  ],
  "goals": ["Maintain HbA1c < 7.5%"],
  "action_items": [{"title": "Order labs", "assignee": "provider-uuid"}]
}
```

## Test Helper

```bash
python scripts/create_test_encounter.py \
  --base-url https://<instance>.canvasmedical.com \
  --api-key <key> \
  --provider-id <uuid> \
  --location-id <uuid> \
  --condition-id-e119 <uuid> \
  --condition-id-f321 <uuid> \
  --condition-id-i10 <uuid>
```

Creates a test encounter for **Samuel Alta (ID: 362737078)** with 3 conditions (E11.9, F32.1, I10) billed as CPT 99490.
