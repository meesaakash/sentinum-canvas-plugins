#!/usr/bin/env python3
"""
Helper script to create a test CCM encounter for Samuel Alta (Sam).

Patient: Samuel Alta
  ID:         362737078
  DOB:        7/1/1989, Age 36, Male
  Phone:      (202) 555-1252
  Conditions: Type 2 DM (E11.9), MDD single episode moderate (F32.1), Hypertension (I10)
  Meds:       fluoxetine 20 mg capsule once daily

With 3 conditions this call will be billed as CPT 99490 (CCM).

Usage:
    python scripts/create_test_encounter.py \\
        --base-url https://<canvas-instance>.canvasmedical.com \\
        --api-key <simpleapi-api-key> \\
        --provider-id <provider-uuid> \\
        --location-id <location-uuid> \\
        [--condition-id-e119 <uuid>]  \\
        [--condition-id-f321 <uuid>]  \\
        [--condition-id-i10  <uuid>]

If condition IDs are not provided, conditions are included without IDs
(useful for testing validation; include them for a fully valid encounter).
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# ─── Patient constants ────────────────────────────────────────────────────────
SAMUEL_ALTA_PATIENT_ID = "362737078"

# ─── Sample CCM call payload ──────────────────────────────────────────────────
SAMPLE_CONDITIONS = [
    {
        # E11.9 — Type 2 diabetes mellitus without complications
        "status": "stable",
        "narrative": (
            "Type 2 diabetes without complications. Patient reports fasting glucose "
            "averaging 140-180 mg/dL over the past month. No hypoglycemic episodes. "
            "Dietary adherence discussed; patient agrees to reduce refined carbohydrate intake. "
            "HbA1c due in 3 months."
        ),
    },
    {
        # F32.1 — Major depressive disorder, single episode, moderate
        "status": "stable",
        "narrative": (
            "Major depressive disorder, single episode, moderate. PHQ-9 score of 6 at last visit, "
            "consistent with mild residual symptoms. Patient reports mood is stable on fluoxetine "
            "20 mg daily. Encouraged to maintain sleep hygiene and social engagement. "
            "Repeat PHQ-9 at next visit."
        ),
    },
    {
        # I10 — Essential (primary) hypertension
        "status": "stable",
        "narrative": (
            "Essential hypertension. Home BP readings averaging 128/78 mmHg over the past two weeks. "
            "Current antihypertensive regimen appears effective. Patient tolerated medications well "
            "with no reported side effects. Continue monitoring."
        ),
    },
]

SAMPLE_PAYLOAD: dict = {
    "patient_id": SAMUEL_ALTA_PATIENT_ID,
    "datetime_of_service": "2026-03-25T23:30:00Z",
    "call_summary": (
        "Completed a 20-minute CCM telephone encounter with Samuel Alta (Sam). "
        "Patient was in good spirits and engaged throughout the call. "
        "Reviewed management of Type 2 diabetes, hypertension, and major depressive disorder. "
        "Patient reports blood glucose averaging 140-180 mg/dL; BP home readings around 128/78 mmHg. "
        "PHQ-9 score of 6 at last visit — mood stable on fluoxetine 20mg daily. "
        "Reinforced medication adherence, dietary modification (low-carb), and daily BP monitoring. "
        "No urgent concerns or medication side effects reported."
    ),
    "care_plan": (
        "1. Continue fluoxetine 20 mg capsule once daily for MDD management.\n"
        "2. Monitor BP at home daily; target consistently <130/80 mmHg.\n"
        "3. Reinforce low-carbohydrate diet and maintain glucose log for review.\n"
        "4. Schedule follow-up labs: HbA1c in 3 months.\n"
        "5. Repeat PHQ-9 at next in-person visit to assess depression trajectory.\n"
        "6. Patient to call clinic if BP exceeds 150/95 or glucose consistently >200 mg/dL."
    ),
    "conditions": SAMPLE_CONDITIONS,
    "goals": [
        "Maintain HbA1c < 7.5% over next 3 months",
        "Keep home BP consistently below 130/80 mmHg",
        "PHQ-9 score < 5 at next scheduled assessment",
    ],
    "action_items": [],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a test CCM encounter for Samuel Alta via the ccm-auto-billing plugin."
    )
    parser.add_argument("--base-url", required=True, help="Canvas instance base URL")
    parser.add_argument("--api-key", required=True, help="simpleapi-api-key secret value")
    parser.add_argument("--provider-id", required=True, help="Provider UUID")
    parser.add_argument("--location-id", required=True, help="Practice location UUID")
    parser.add_argument("--condition-id-e119", default=None, help="Canvas condition UUID for E11.9 (Type 2 DM)")
    parser.add_argument("--condition-id-f321", default=None, help="Canvas condition UUID for F32.1 (MDD)")
    parser.add_argument("--condition-id-i10", default=None, help="Canvas condition UUID for I10 (Hypertension)")
    args = parser.parse_args()

    # Build payload with provider and location
    payload = {
        **SAMPLE_PAYLOAD,
        "provider_id": args.provider_id,
        "practice_location_id": args.location_id,
    }

    # Deep-copy conditions and inject IDs where provided
    conditions = [dict(c) for c in SAMPLE_CONDITIONS]
    condition_id_args = [args.condition_id_e119, args.condition_id_f321, args.condition_id_i10]
    for i, cid in enumerate(condition_id_args):
        if cid:
            conditions[i]["condition_id"] = cid
    payload["conditions"] = conditions

    # Warn if no condition IDs provided (creates will still validate them)
    if not any(condition_id_args):
        print(
            "WARNING: No condition IDs provided. "
            "The server will reject requests if condition_id is required. "
            "Use --condition-id-e119 / --condition-id-f321 / --condition-id-i10 to supply them.",
            file=sys.stderr,
        )

    url = f"{args.base_url.rstrip('/')}/plugin-io/api/ccm-auto-billing/ccm/calls"
    print(f"POST {url}")
    print(f"Patient: Samuel Alta (ID: {SAMUEL_ALTA_PATIENT_ID})")
    print(f"Conditions: {len(conditions)} → expected CPT 99490 (CCM)")
    print()

    resp = requests.post(
        url,
        json=payload,
        headers={"Authorization": args.api_key},
        timeout=30,
    )

    print(f"Status: {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)

    sys.exit(0 if resp.status_code == 201 else 1)


if __name__ == "__main__":
    main()
