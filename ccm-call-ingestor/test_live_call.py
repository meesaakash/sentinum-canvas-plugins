#!/usr/bin/env python3
"""
Live test script for the CCM Call Ingestor plugin.

Sends a real CCM call payload (Call ID 4279 - Dorrie's call) to the plugin endpoint
running on the Canvas sandbox and prints the response.

Usage:
    uv run python test_live_call.py

Configuration via environment variables:
    CCM_API_KEY           - The simpleapi-api-key secret configured in Canvas (required)
    CANVAS_INSTANCE       - Canvas instance name (default: sentinumhealth-sandbox)
    PATIENT_ID            - Canvas patient 32-char key (default: Jane Doe on sandbox)
    PROVIDER_ID           - Canvas staff 32-char key (default: Richard Wilson MD on sandbox)
    PRACTICE_LOCATION_ID  - Canvas practice location UUID (default: sandbox location)

Sandbox IDs (sentinumhealth-sandbox):
    Patients:
      a02f8379f7814821afec304c193dbfa1  Jane Doe (F, 1953-11-04)
      8b3a507224e84c61ba40f721533dd1d7  Joseph Adams (M, 1990-08-31)
      94764cdf73404a728735e08d3ed90df2  John Shaw (M, 1975-08-21)
      41fb2a51a18d4948afb9d874a7a2adcb  Samuel Alta (M, 1989-07-01)
      18a0db31d07b4b02a63ad5ab8f274c3e  Bob Smith (M, 1970-01-01)
    Staff:
      e766816672f34a5b866771c773e38f3c  Richard Wilson MD
      e6e90e416e0c422992aabb110fe8b1f1  Amanda Miller DO
      2f3d5e810d1844caa51034744c64918c  Christopher Taylor NP
    Practice Location UUID: d1eacdb5-9ead-47ce-855a-c8c6ef3932a6

    Conditions for Jane Doe (patient 1) matching the transcript:
      58  I10 Essential (primary) hypertension [active]
      59  E119 Type 2 diabetes mellitus without complications [active]
       1  Mixed hyperlipidemia [active]
      48  M25561 Pain in right knee [active]

Plugin endpoint: POST /plugin-io/api/ccm_call_ingestor/ccm-ingest/calls

Run:
    CCM_API_KEY=test-ccm-key-2026 uv run python test_live_call.py
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CANVAS_INSTANCE = os.environ.get("CANVAS_INSTANCE", "sentinumhealth-sandbox")
BASE_URL = f"https://{CANVAS_INSTANCE}.canvasmedical.com"
CLIENT_ID = "jYsMMb2QU04UCXDXi8J9k19T86dntCFswimOvGay"
CLIENT_SECRET = (
    "kRygTNiYJBYISlTaf919TVOnqRQ6w607rHvWr7puB5tIra27yD413AJsEroSCQQ07Z9P7BVqJxRCxq0MoBCgY"
    "jXXXJ4ghB5sdyV6Nq5lzi4IIlb3Qw46PfTVYpflO5ts"
)

CCM_API_KEY = os.environ.get("CCM_API_KEY", "test-ccm-key-2026")
# Jane Doe (patient 1 on sentinumhealth-sandbox) — change for other patients/instances
PATIENT_ID = os.environ.get("PATIENT_ID", "a02f8379f7814821afec304c193dbfa1")
# Richard Wilson MD (staff 3 on sentinumhealth-sandbox)
PROVIDER_ID = os.environ.get("PROVIDER_ID", "e766816672f34a5b866771c773e38f3c")
PRACTICE_LOCATION_ID = os.environ.get(
    "PRACTICE_LOCATION_ID", "d1eacdb5-9ead-47ce-855a-c8c6ef3932a6"
)

# Plugin endpoint path (uses plugin manifest name with underscores)
PLUGIN_ENDPOINT = "/plugin-io/api/ccm_call_ingestor/ccm-ingest/calls"

# Conditions from patient 1 that match the CCM call topics.
# These are Canvas condition IDs (integer strings).
# To update: check FHIR API GET /api/Condition/?patient=Patient/1
# or replace with actual condition IDs from the real patient.
CONDITIONS = [
    {
        "condition_id": "58",           # I10 Essential (primary) hypertension [active]
        "status": "stable",
        "narrative": (
            "Patient reports home BP readings averaging 128/75 mmHg with proper measurement "
            "technique (sitting quietly 5-10 min, arm supported). Isolated pharmacy reading of "
            "140/85 attributed to exertion and time pressure. No headaches or dizziness. "
            "Adhering to low-sodium diet and daily walking. Continues Amlodipine 10mg QD and "
            "Ramipril 10mg QD as prescribed."
        ),
    },
    {
        "condition_id": "59",           # E119 Type 2 diabetes mellitus without complications [active]
        "status": "stable",
        "narrative": (
            "Patient confirms taking Metformin 500mg BID with meals. Uses a pill box organizer "
            "and reports no missed doses. Monitoring blood sugar. No hypoglycemic symptoms reported."
        ),
    },
    {
        "condition_id": "1",            # 267434003 Mixed hyperlipidemia [active]
        "status": "stable",
        "narrative": (
            "Patient confirms taking Atorvastatin 20mg QHS as part of nightly routine. "
            "No muscle pain or weakness reported. Continuing heart-healthy diet."
        ),
    },
    {
        "condition_id": "48",           # M25561 Pain in right knee [active]
        "status": "stable",
        "narrative": (
            "Patient using Diclofenac Sodium 1% gel as needed for knee stiffness, typically "
            "mornings or after prolonged activity. Reports good relief. New stretching/yoga goal "
            "established to improve joint flexibility."
        ),
    },
]


# ---------------------------------------------------------------------------
# CCM Call Payload (Call ID 4279 — Dorrie's call, 2026-02-05)
# ---------------------------------------------------------------------------

CALL_SUMMARY = """CCM phone check-in completed for call ID 4279 (2026-02-05).

Patient verified identity (DOB year: 1949). Consented to call recording and documentation.

BLOOD PRESSURE: Home readings averaging 128/75 mmHg. Patient uses proper technique (sits quietly 5–10 min before measurement, arm supported). Isolated pharmacy reading of 140/85 on a day the patient was rushed and had walked; patient felt fine, no symptoms. No headaches or dizziness reported. Monitoring BP before coffee each morning.

DIET: Continuing low-sodium diet. Cooking at home with salt-free spices. Occasional small takeout portion (granddaughter brought food); BP remained stable the following morning. Patient checks food labels diligently.

MEDICATIONS REVIEWED — all confirmed correct and adherent:
• Diclofenac Sodium 1% Gel (as needed for knee stiffness)
• Metformin 500 mg BID with meals
• Amlodipine Besylate 10 mg QD (morning)
• Atorvastatin 20 mg QHS (bedtime)
• Ramipril 10 mg QD (morning)
No new medications, no stopped medications, no dose changes. No vitamins or supplements.

PRIOR GOAL REVIEW: "Add 15 minutes to daily walk at least 3×/week." Mostly achieved — hit target most weeks (sometimes 4×). One week missed due to rain + knee stiffness; made up the following week.

NEW GOAL SET: "I will do 15 minutes of light stretching or gentle yoga every morning, at least 5 times a week, for the next month."

PATIENT SATISFACTION: 10/10. Patient found call efficient and thorough.

SCHEDULING REQUEST: Patient requested appointment next month; prefers Tuesday or Thursday."""

CARE_PLAN = """TYPE 2 DIABETES MELLITUS WITHOUT COMPLICATIONS (E11.9):
• Confirmed Metformin 500 mg BID with meals — continue.
• Advise continued regular blood glucose monitoring.
• Instruct patient to recognize hypoglycemia symptoms (shakiness, confusion).
• Counsel on consistent carbohydrate intake for stable glucose.

PURE HYPERCHOLESTEROLEMIA / MIXED HYPERLIPIDEMIA:
• Confirmed Atorvastatin 20 mg QHS — continue.
• Educate on Atorvastatin's role in reducing cardiovascular risk.
• Recommend heart-healthy diet low in saturated fats.
• Monitor for unexplained muscle pain or weakness; report to provider if noted.

ESSENTIAL (PRIMARY) HYPERTENSION (I10):
• Reviewed home BP monitoring technique and recent readings (avg 128/75).
• Continue limiting sodium; read labels for hidden salt content.
• Keep a log of home BP readings to review at next office visit.
• Maintain daily walking routine for cardiovascular health.
• Monitor for orthostatic hypotension symptoms (dizziness when standing).
• Emphasize medication adherence even when readings are within normal range.

KNEE PAIN / OSTEOARTHRITIS:
• Reviewed Diclofenac 1% gel use — continue as needed.
• Patient's new stretching goal supports joint flexibility improvement.
• Encourage balanced activity and rest to manage joint discomfort.
• Advise warm compresses for morning stiffness.
• Monitor for skin irritation at application site.
• Encourage supportive footwear for stability during daily activities.

SAFETY NOTE: Patient informed that CCM call is supplementary — not a substitute for direct medical care. Advised to call 911 in any medical emergency. No diagnoses established during this call.

MEDICATION RECONCILIATION COMPLETED:
Diclofenac Sodium 1% Gel (PRN), Metformin 500mg BID, Amlodipine Besylate 10mg QD,
Atorvastatin 20mg QHS, Ramipril 10mg QD.
Additional meds on chart: Artificial Tears (TID), Ammonium Lactate 12% Lotion (BID),
Alendronate 70mg QWK, Calcium Citrate 950mg Q12H, HCTZ 25mg QD.

SDOH: Patient lives independently, mobile, walks daily. Noted wobbly step stool when reaching high shelves — safety concern raised. No other SDOH barriers identified.

NEXT REVIEW: ~30 days. Earlier review triggered if BP consistently exceeds target or joint pain worsens."""

ACTION_ITEMS = [
    {
        "title": (
            "Contact patient to schedule or confirm appointment for next month; "
            "availability: Tuesday or Thursday"
        ),
        "assignee": PROVIDER_ID,
    }
]

GOALS = [
    "I will do 15 minutes of light stretching or gentle yoga every morning, at least 5 times a week, for the next month.",
    "Maintain home blood pressure readings within the target range as discussed with the provider.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
    ).encode()
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
        return {"error": e.code, "body": e.read().decode()[:200]}


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
            return e.code, {"raw": body_text if "body_text" in dir() else ""}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("CCM Call Ingestor — Live Test")
    print(f"Instance : {CANVAS_INSTANCE}")
    print(f"Patient  : {PATIENT_ID}")
    print(f"Provider : {PROVIDER_ID}")
    print(f"Location : {PRACTICE_LOCATION_ID}")
    print("=" * 60)

    if not CCM_API_KEY:
        print(
            "\n[ERROR] CCM_API_KEY is not set.\n"
            "Set it via the env var or update the default in this script:\n"
            "\n    CCM_API_KEY=your-key uv run python test_live_call.py\n"
        )
        sys.exit(1)

    print(f"Endpoint : {PLUGIN_ENDPOINT}")

    print("\n[1/3] Fetching OAuth token...")
    try:
        token = get_token()
        print("      OK")
    except Exception as exc:
        print(f"      FAILED: {exc}")
        sys.exit(1)

    print(f"\n[2/3] Patient key: {PATIENT_ID[:8]}... (skipping FHIR lookup — using 32-char key)")

    print("\n[3/3] Sending CCM call payload to plugin...")
    payload = {
        "patient_id": PATIENT_ID,
        "provider_id": PROVIDER_ID,
        "practice_location_id": PRACTICE_LOCATION_ID,
        "datetime_of_service": "2026-02-05T19:05:27Z",
        "call_summary": CALL_SUMMARY,
        "care_plan": CARE_PLAN,
        "conditions": CONDITIONS,
        "goals": GOALS,
        "action_items": ACTION_ITEMS,
    }

    print("\nPayload preview:")
    preview = {k: (v if not isinstance(v, str) else v[:80] + "...") for k, v in payload.items()}
    print(json.dumps(preview, indent=2))

    print("\nPOST /plugin-io/api/ccm-call-ingestor/ccm-ingest/calls")
    status, response = post_plugin(CCM_API_KEY, payload)

    print(f"\nHTTP {status}")
    print(json.dumps(response, indent=2))

    if status == 201:
        note_id = response.get("note_id", "")
        print(
            f"\n[SUCCESS] Encounter note created: {note_id}\n"
            f"View it at: {BASE_URL}/patient/{PATIENT_ID}/chart"
        )
    elif status == 401:
        print(
            "\n[FAIL] Authentication failed — check that CCM_API_KEY matches the "
            "'simpleapi-api-key' secret configured in Canvas Admin for this plugin."
        )
    elif status == 404:
        print(
            f"\n[FAIL] Patient {PATIENT_ID} not found in Canvas. "
            "Update PATIENT_ID to a valid canvas patient ID."
        )
    elif status == 422:
        print("\n[FAIL] Validation error — check the payload fields above.")
    elif status == 500:
        print(
            "\n[FAIL] Server error — note type may not be configured. "
            "Set the NOTE_TYPE_ID secret in Canvas Admin, or ensure an 'Office visit' note type exists."
        )
    else:
        print(f"\n[FAIL] Unexpected status {status}")


if __name__ == "__main__":
    main()
