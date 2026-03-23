"""
JSON schemas for all 33 Canvas command types.
Each schema describes the parameters the LLM should extract from the transcript.
"""

COMMAND_SCHEMAS: dict[str, dict] = {
    "HistoryOfPresentIllnessCommand": {
        "description": "Document the history of present illness narrative.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "narrative": {"type": "string", "description": "Full HPI narrative text"},
        },
        "required": ["note_uuid", "narrative"],
    },
    "ReasonForVisitCommand": {
        "description": "Document the reason for the visit.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "comment": {"type": "string", "description": "Reason for visit text"},
        },
        "required": ["note_uuid", "comment"],
    },
    "AssessCommand": {
        "description": "Assess an existing condition with status and narrative.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "condition_id": {"type": "string", "description": "UUID of the existing condition"},
            "background": {"type": "string", "description": "Clinical background/narrative"},
            "status": {
                "type": "string",
                "enum": ["stable", "improved", "deteriorated", "worsened"],
                "description": "Current status of the condition",
            },
            "narrative": {"type": "string", "description": "Assessment narrative"},
        },
        "required": ["note_uuid", "narrative"],
    },
    "DiagnoseCommand": {
        "description": "Add a new diagnosis to the note.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "icd10_code": {"type": "string", "description": "ICD-10 code (e.g. J06.9)"},
            "background": {"type": "string", "description": "Clinical rationale for the diagnosis"},
            "approximate_date_of_onset": {"type": "string", "description": "Approximate date of onset (YYYY-MM-DD)"},
            "today_assessment": {"type": "string", "description": "Assessment narrative for today"},
        },
        "required": ["note_uuid", "icd10_code"],
    },
    "UpdateDiagnosisCommand": {
        "description": "Update an existing diagnosis.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "condition_id": {"type": "string", "description": "UUID of existing condition to update"},
            "icd10_code": {"type": "string", "description": "New ICD-10 code if changing"},
            "background": {"type": "string", "description": "Updated background/rationale"},
            "today_assessment": {"type": "string", "description": "Updated assessment for today"},
        },
        "required": ["note_uuid", "condition_id"],
    },
    "ResolveConditionCommand": {
        "description": "Mark an existing condition as resolved.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "condition_id": {"type": "string", "description": "UUID of the condition to resolve"},
            "narrative": {"type": "string", "description": "Reason for resolving"},
        },
        "required": ["note_uuid", "condition_id"],
    },
    "PlanCommand": {
        "description": "Document the treatment plan narrative.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "narrative": {"type": "string", "description": "Plan narrative text"},
        },
        "required": ["note_uuid", "narrative"],
    },
    "PrescribeCommand": {
        "description": "Prescribe a new medication.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "fdb_code": {"type": "string", "description": "FDB medication code"},
            "sig": {"type": "string", "description": "Prescription instructions (sig)"},
            "days_supply": {"type": "integer", "description": "Days supply"},
            "quantity_to_dispense": {"type": "number", "description": "Quantity to dispense"},
            "refills": {"type": "integer", "description": "Number of refills"},
            "substitutions": {"type": "string", "enum": ["allowed", "not_allowed"], "description": "Substitution policy"},
            "pharmacy_note": {"type": "string", "description": "Note to pharmacy"},
            "prescriber_note": {"type": "string", "description": "Note from prescriber"},
            "note_to_patient": {"type": "string", "description": "Note to patient"},
        },
        "required": ["note_uuid", "fdb_code", "sig"],
    },
    "RefillCommand": {
        "description": "Refill an existing prescription.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "medication_id": {"type": "string", "description": "UUID of the existing medication to refill"},
            "sig": {"type": "string", "description": "Updated sig if changed"},
            "days_supply": {"type": "integer", "description": "Days supply"},
            "quantity_to_dispense": {"type": "number", "description": "Quantity to dispense"},
            "refills": {"type": "integer", "description": "Number of refills"},
        },
        "required": ["note_uuid", "medication_id"],
    },
    "AdjustPrescriptionCommand": {
        "description": "Adjust an existing prescription (dose, frequency, etc.).",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "medication_id": {"type": "string", "description": "UUID of the medication to adjust"},
            "sig": {"type": "string", "description": "New sig"},
            "days_supply": {"type": "integer", "description": "Days supply"},
            "quantity_to_dispense": {"type": "number", "description": "Quantity to dispense"},
            "refills": {"type": "integer", "description": "Number of refills"},
        },
        "required": ["note_uuid", "medication_id"],
    },
    "StopMedicationCommand": {
        "description": "Stop/discontinue a medication.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "medication_id": {"type": "string", "description": "UUID of the medication to stop"},
            "rationale": {"type": "string", "description": "Reason for stopping the medication"},
        },
        "required": ["note_uuid", "medication_id"],
    },
    "MedicationStatementCommand": {
        "description": "Record a medication the patient is taking (not prescribed here).",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "fdb_code": {"type": "string", "description": "FDB code for the medication"},
            "sig": {"type": "string", "description": "Dosing instructions"},
            "clinical_quantity": {"type": "string", "description": "Clinical quantity"},
        },
        "required": ["note_uuid", "fdb_code"],
    },
    "AllergyCommand": {
        "description": "Record a new allergy.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "allergy": {"type": "string", "description": "Name of allergen"},
            "severity": {"type": "string", "description": "Severity (mild, moderate, severe)"},
            "narrative": {"type": "string", "description": "Reaction description"},
        },
        "required": ["note_uuid", "allergy"],
    },
    "RemoveAllergyCommand": {
        "description": "Remove an existing allergy entry.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "allergy_id": {"type": "string", "description": "UUID of the allergy to remove"},
            "narrative": {"type": "string", "description": "Reason for removal"},
        },
        "required": ["note_uuid", "allergy_id"],
    },
    "LabOrderCommand": {
        "description": "Order lab tests.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "lab_partner_id": {"type": "string", "description": "Lab partner UUID"},
            "tests": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of test names or codes to order",
            },
            "ordering_provider_id": {"type": "string", "description": "Ordering provider UUID"},
            "diagnosis_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ICD-10 codes indicating reason for lab",
            },
            "fasting_required": {"type": "boolean", "description": "Whether fasting is required"},
            "note_to_patient": {"type": "string", "description": "Instructions for patient"},
        },
        "required": ["note_uuid", "tests"],
    },
    "ImagingOrderCommand": {
        "description": "Order imaging studies.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "imaging_center_id": {"type": "string", "description": "Imaging center UUID"},
            "study": {"type": "string", "description": "Type of imaging study (e.g. 'X-ray chest PA')"},
            "ordering_provider_id": {"type": "string", "description": "Ordering provider UUID"},
            "diagnosis_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ICD-10 codes",
            },
            "clinical_information": {"type": "string", "description": "Clinical information for radiologist"},
            "note_to_patient": {"type": "string", "description": "Instructions for patient"},
        },
        "required": ["note_uuid", "study"],
    },
    "ReferCommand": {
        "description": "Refer patient to a specialist or service.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "refer_to": {"type": "string", "description": "Specialty or provider to refer to"},
            "priority": {"type": "string", "enum": ["routine", "urgent", "emergent"], "description": "Referral priority"},
            "diagnosis_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ICD-10 codes",
            },
            "notes": {"type": "string", "description": "Clinical notes for the referral"},
        },
        "required": ["note_uuid", "refer_to"],
    },
    "FollowUpCommand": {
        "description": "Schedule a follow-up appointment.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "note": {"type": "string", "description": "Follow-up instructions"},
            "requested_date": {"type": "string", "description": "Requested date (YYYY-MM-DD)"},
        },
        "required": ["note_uuid"],
    },
    "InstructCommand": {
        "description": "Give patient education/instructions.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "instruction": {"type": "string", "description": "Patient instruction text"},
        },
        "required": ["note_uuid", "instruction"],
    },
    "PerformCommand": {
        "description": "Record an in-office procedure performed.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "cpt_code": {"type": "string", "description": "CPT procedure code"},
            "notes": {"type": "string", "description": "Procedure notes"},
        },
        "required": ["note_uuid", "cpt_code"],
    },
    "VitalsCommand": {
        "description": "Record patient vital signs.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "blood_pressure_systolic": {"type": "integer", "description": "Systolic BP (mmHg)"},
            "blood_pressure_diastolic": {"type": "integer", "description": "Diastolic BP (mmHg)"},
            "pulse": {"type": "integer", "description": "Heart rate (bpm)"},
            "temperature": {"type": "number", "description": "Temperature (Fahrenheit)"},
            "weight_lbs": {"type": "number", "description": "Weight (lbs)"},
            "height_in": {"type": "number", "description": "Height (inches)"},
            "oxygen_saturation": {"type": "number", "description": "SpO2 (%)"},
            "respirations": {"type": "integer", "description": "Respiratory rate (breaths/min)"},
        },
        "required": ["note_uuid"],
    },
    "GoalCommand": {
        "description": "Set a new clinical goal for the patient.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "goal_statement": {"type": "string", "description": "Goal statement text"},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            "due_date": {"type": "string", "description": "Target date (YYYY-MM-DD)"},
            "achievement_status": {"type": "string", "description": "Current achievement status"},
        },
        "required": ["note_uuid", "goal_statement"],
    },
    "UpdateGoalCommand": {
        "description": "Update an existing clinical goal.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "goal_id": {"type": "string", "description": "UUID of the goal to update"},
            "goal_statement": {"type": "string", "description": "Updated goal statement"},
            "achievement_status": {"type": "string", "description": "Updated achievement status"},
            "due_date": {"type": "string", "description": "Updated due date (YYYY-MM-DD)"},
        },
        "required": ["note_uuid", "goal_id"],
    },
    "CloseGoalCommand": {
        "description": "Close/complete a clinical goal.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "goal_id": {"type": "string", "description": "UUID of the goal to close"},
            "achievement_status": {"type": "string", "description": "Final achievement status"},
        },
        "required": ["note_uuid", "goal_id"],
    },
    "MedicalHistoryCommand": {
        "description": "Add to the patient's medical history.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "icd10_code": {"type": "string", "description": "ICD-10 code"},
            "approximate_start_date": {"type": "string", "description": "Approximate start date"},
            "comments": {"type": "string", "description": "Additional comments"},
        },
        "required": ["note_uuid", "icd10_code"],
    },
    "PastSurgicalHistoryCommand": {
        "description": "Add a past surgical procedure to history.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "past_surgical_history": {"type": "string", "description": "Description of the surgical procedure"},
            "approximate_date": {"type": "string", "description": "Approximate date of surgery"},
            "comment": {"type": "string", "description": "Additional comments"},
        },
        "required": ["note_uuid", "past_surgical_history"],
    },
    "FamilyHistoryCommand": {
        "description": "Record family medical history.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "relative": {"type": "string", "description": "Family member (e.g. mother, father)"},
            "icd10_code": {"type": "string", "description": "ICD-10 code for the condition"},
            "note": {"type": "string", "description": "Additional notes"},
        },
        "required": ["note_uuid", "relative", "icd10_code"],
    },
    "ImmunizationStatementCommand": {
        "description": "Record an immunization.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "vaccine_code": {"type": "string", "description": "CVX vaccine code"},
            "date_administered": {"type": "string", "description": "Date administered (YYYY-MM-DD)"},
            "note": {"type": "string", "description": "Additional notes"},
        },
        "required": ["note_uuid", "vaccine_code"],
    },
    "TaskCommand": {
        "description": "Create a task in the patient chart.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "title": {"type": "string", "description": "Task title/description"},
            "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)"},
            "comment": {"type": "string", "description": "Task comment"},
        },
        "required": ["note_uuid", "title"],
    },
    "ReviewOfSystemsCommand": {
        "description": "Document review of systems.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "command_uuid": {"type": "string", "description": "UUID of existing ROS command if updating"},
            "questions": {"type": "object", "description": "Question name → response mapping"},
        },
        "required": ["note_uuid"],
    },
    "PhysicalExamCommand": {
        "description": "Document physical examination findings.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "command_uuid": {"type": "string", "description": "UUID of existing exam command if updating"},
            "questions": {"type": "object", "description": "Question name → response mapping"},
        },
        "required": ["note_uuid"],
    },
    "StructuredAssessmentCommand": {
        "description": "Document a structured assessment questionnaire.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "command_uuid": {"type": "string", "description": "UUID of existing command if updating"},
            "questions": {"type": "object", "description": "Question name → response mapping"},
        },
        "required": ["note_uuid"],
    },
    "QuestionnaireCommand": {
        "description": "Document a patient questionnaire.",
        "fields": {
            "note_uuid": {"type": "string", "description": "Note UUID (provided)"},
            "command_uuid": {"type": "string", "description": "UUID of existing command if updating"},
            "questions": {"type": "object", "description": "Question name → response mapping"},
        },
        "required": ["note_uuid"],
    },
}
