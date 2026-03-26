#!/usr/bin/env python3
"""
Live test script for the CCM Auto-Billing plugin.

Sends a CCM call payload for Samuel Alta (Sam) to the plugin endpoint on the
Canvas sandbox. Auto-looks up his active condition IDs via FHIR, then POSTs
to the plugin. Prints the response and a direct chart link.

Patient: Samuel Alta (Sam)
  Canvas ID : 41fb2a51a18d4948afb9d874a7a2adcb
  DOB       : 1989-07-01, Male
  Conditions: E11.9 (Type 2 DM), F32.1 (MDD), I10 (HTN) → CPT 99490 (CCM)

Run (no args needed — all defaults point at sentinumhealth-sandbox + Samuel Alta):
    python test_live_call.py

Or override via env vars:
    CCM_API_KEY=my-key CANVAS_INSTANCE=other-sandbox python test_live_call.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Configuration — all defaults pre-filled for sentinumhealth-sandbox
# ---------------------------------------------------------------------------

CANVAS_INSTANCE    = os.environ.get("CANVAS_INSTANCE", "sentinumhealth-sandbox")
BASE_URL           = f"https://{CANVAS_INSTANCE}.canvasmedical.com"

CLIENT_ID     = "jYsMMb2QU04UCXDXi8J9k19T86dntCFswimOvGay"
CLIENT_SECRET = (
    "kRygTNiYJBYISlTaf919TVOnqRQ6w607rHvWr7puB5tIra27yD413AJsEroSCQQ07Z9P7BVqJxRCxq0MoBCgY"
    "jXXXJ4ghB5sdyV6Nq5lzi4IIlb3Qw46PfTVYpflO5ts"
)

CCM_API_KEY          = os.environ.get("CCM_API_KEY", "test-ccm-key-2026")
PATIENT_ID           = os.environ.get("PATIENT_ID", "41fb2a51a18d4948afb9d874a7a2adcb")  # Samuel Alta
PROVIDER_ID          = os.environ.get("PROVIDER_ID", "e766816672f34a5b866771c773e38f3c")  # Richard Wilson MD
PRACTICE_LOCATION_ID = os.environ.get("PRACTICE_LOCATION_ID", "d1eacdb5-9ead-47ce-855a-c8c6ef3932a6")

PLUGIN_ENDPOINT = "/plugin-io/api/ccm_auto_billing/ccm/calls"

# ICD-10 codes to look for in Samuel Alta's active conditions
TARGET_CODES = {"E11.9", "E119", "F32.1", "F321", "I10"}

# ---------------------------------------------------------------------------
# CCM call content for Samuel Alta
# ---------------------------------------------------------------------------

CALL_SUMMARY = (
    "Completed 20-minute CCM telephone encounter with Samuel Alta (Sam). "
    "Patient was engaged and cooperative throughout the call. "
    "Reviewed management of Type 2 diabetes mellitus, essential hypertension, and major depressive disorder. "
    "Patient reports fasting blood glucose averaging 140-180 mg/dL over the past month — "
    "no hypoglycemic episodes, dietary adherence discussed, patient agrees to reduce refined carbohydrate intake. "
    "Home BP readings averaging 128/78 mmHg — current antihypertensive regimen appears effective, "
    "patient tolerated medications well with no side effects. "
    "PHQ-9 score of 6 at last visit; patient reports mood is stable on fluoxetine 20mg daily, "
    "encouraged to maintain sleep hygiene and social engagement. "
    "Reinforced medication adherence and daily BP/glucose monitoring. "
    "No urgent concerns or new medication side effects reported."
)

CARE_PLAN = (
    "1. Continue fluoxetine 20 mg capsule once daily for MDD management.\n"
    "2. Monitor BP at home daily; target consistently <130/80 mmHg.\n"
    "3. Reinforce low-carbohydrate diet and maintain glucose log for review.\n"
    "4. Schedule follow-up labs: HbA1c in 3 months.\n"
    "5. Repeat PHQ-9 at next in-person visit to assess depression trajectory.\n"
    "6. Patient to call clinic if BP exceeds 150/95 or glucose consistently >200 mg/dL."
)

GOALS = [
    "Maintain HbA1c < 7.5% over next 3 months",
    "Keep home BP consistently below 130/80 mmHg",
    "PHQ-9 score < 5 at next scheduled assessment",
]

# Narratives keyed by normalised ICD-10 code (no dot, uppercase)
CONDITION_NARRATIVES = {
    "E119": (
        "Type 2 diabetes without complications. Fasting glucose averaging 140-180 mg/dL over "
        "the past month. No hypoglycemic episodes. Dietary adherence reinforced; patient agrees "
        "to reduce refined carbohydrate intake. HbA1c due in 3 months."
    ),
    "F321": (
        "Major depressive disorder, single episode, moderate. PHQ-9 score of 6 at last visit, "
        "consistent with mild residual symptoms. Patient reports mood stable on fluoxetine 20mg "
        "daily. Encouraged to maintain sleep hygiene and social engagement. Repeat PHQ-9 at next visit."
    ),
    "I10": (
        "Essential hypertension. Home BP readings averaging 128/78 mmHg over the past two weeks. "
        "Current antihypertensive regimen effective. Patient tolerated medications well with no "
        "reported side effects. Continue monitoring."
    ),
}

DEFAULT_NARRATIVE = "Condition reviewed during CCM call. Patient reports stable status."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_code(code: str) -> str:
    """E11.9 → E119,  F32.1 → F321, I10 → I10"""
    return code.replace(".", "").upper()


def get_token() -> str:
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/auth/token/",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def fhir_get(token: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}/api/{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}


def lookup_conditions(token: str, patient_id: str) -> list[dict]:
    """
    Query FHIR for the patient's active conditions and return a list of
    {condition_id, status, narrative} dicts for conditions matching TARGET_CODES.
    Falls back to all active conditions if none match.
    """
    data = fhir_get(
        token,
        f"Condition/?patient=Patient/{patient_id}&clinical-status=active",
    )
    if "error" in data:
        print(f"  WARN: FHIR Condition lookup failed ({data}). Conditions will have no IDs.")
        return []

    entries = data.get("entry", [])
    matched = []
    unmatched = []

    for entry in entries:
        resource = entry.get("resource", {})
        condition_id = str(resource.get("id", ""))
        # Extract ICD-10 code (Canvas may use icd-10-cm or other system URLs)
        codings = resource.get("code", {}).get("coding", [])
        icd_coding = next(
            (c for c in codings if "icd-10" in c.get("system", "").lower()),
            codings[0] if codings else {},
        )
        raw_code = icd_coding.get("code", "")
        norm = _normalise_code(raw_code)
        display = icd_coding.get("display", raw_code)

        rec = {
            "condition_id": condition_id,
            "status": "stable",
            "narrative": CONDITION_NARRATIVES.get(norm, DEFAULT_NARRATIVE),
            "_code": raw_code,
            "_display": display,
        }
        if norm in {_normalise_code(c) for c in TARGET_CODES}:
            matched.append(rec)
            print(f"  ✓ {condition_id:>6}  {raw_code:<8}  {display}")
        else:
            unmatched.append(rec)

    if not matched:
        print("  No target conditions found — including all active conditions instead.")
        for rec in unmatched:
            print(f"  ~ {rec['condition_id']:>6}  {rec['_code']:<8}  {rec['_display']}")
        return unmatched

    return matched


def post_plugin(api_key: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{PLUGIN_ENDPOINT}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode()
            return e.code, json.loads(body_text)
        except Exception:
            return e.code, {"raw": body_text if "body_text" in dir() else "unreadable"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 62)
    print("  CCM Auto-Billing Plugin — Live Test")
    print(f"  Instance : {CANVAS_INSTANCE}")
    print(f"  Patient  : Samuel Alta ({PATIENT_ID[:8]}...)")
    print(f"  Provider : Richard Wilson MD ({PROVIDER_ID[:8]}...)")
    print(f"  Location : {PRACTICE_LOCATION_ID}")
    print(f"  Endpoint : {PLUGIN_ENDPOINT}")
    print("=" * 62)

    # Step 1 — OAuth token
    print("\n[1/3] Fetching OAuth token...")
    try:
        token = get_token()
        print("      OK")
    except Exception as exc:
        print(f"      FAILED: {exc}")
        sys.exit(1)

    # Step 2 — Condition IDs via FHIR
    print(f"\n[2/3] Looking up active conditions for Samuel Alta...")
    conditions = lookup_conditions(token, PATIENT_ID)

    # Strip internal _code/_display keys before sending
    clean_conditions = [
        {k: v for k, v in c.items() if not k.startswith("_")}
        for c in conditions
    ]

    cpt = "99490" if len(clean_conditions) != 1 else "99424"
    print(f"\n      {len(clean_conditions)} condition(s) found → will bill as CPT {cpt}")

    # Step 3 — POST to plugin
    print("\n[3/3] Sending CCM call payload to plugin...")
    payload = {
        "patient_id": PATIENT_ID,
        "provider_id": PROVIDER_ID,
        "practice_location_id": PRACTICE_LOCATION_ID,
        "datetime_of_service": "2026-03-25T23:30:00Z",
        "call_summary": CALL_SUMMARY,
        "care_plan": CARE_PLAN,
        "conditions": clean_conditions,
        "goals": GOALS,
        "action_items": [],
    }

    status, response = post_plugin(CCM_API_KEY, payload)

    print(f"\nHTTP {status}")
    print(json.dumps(response, indent=2))

    if status == 201:
        note_id = response.get("note_id", "")
        cpt_code = response.get("cpt_code", "")
        print(f"\n[SUCCESS] Encounter note created — CPT {cpt_code}")
        print(f"  Note ID  : {note_id}")
        print(f"  Chart    : {BASE_URL}/patient/{PATIENT_ID}")
        print(f"\n  Next: open the chart, review the note, then Lock → Sign → Push Charges")
        print(f"  The CCMClaimRouter will auto-route the claim to QUEUED_FOR_SUBMISSION.")
    elif status == 401:
        print(
            "\n[FAIL] 401 Unauthorised — check that CCM_API_KEY matches the "
            "'simpleapi-api-key' secret in Canvas Admin for ccm_auto_billing."
        )
    elif status == 404:
        print(f"\n[FAIL] 404 — patient {PATIENT_ID} not found, or plugin not installed.")
    elif status == 422:
        print("\n[FAIL] 422 Validation error — check condition IDs and required fields above.")
    elif status == 500:
        print(
            "\n[FAIL] 500 — note type may not be configured. "
            "Set NOTE_TYPE_ID secret in Canvas Admin, or ensure 'Office visit' note type exists."
        )
    else:
        print(f"\n[FAIL] Unexpected status {status}")


if __name__ == "__main__":
    main()
