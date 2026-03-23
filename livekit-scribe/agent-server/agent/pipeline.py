"""
4-stage LLM pipeline mirroring hyperscribe's AudioInterpreter.

Stage 1: STT — done by LiveKit (transcript passed in)
Stage 2: Instruction detection — Gemini identifies which Canvas commands are needed
Stage 3: Parameter extraction — Gemini extracts structured params for each command
Stage 4: Build command dicts — format as [{"class": ..., "attributes": {...}}, ...]
"""

import asyncio
import json
import logging
import os
from http import HTTPStatus

import httpx

from schemas import COMMAND_SCHEMAS

logger = logging.getLogger(__name__)

GEMINI_MODEL = "models/gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_CONTEXT = """You are an AI medical scribe assistant helping a licensed clinician document patient encounters.
You analyze transcripts of clinical conversations and extract structured medical documentation commands.
Be precise, use medical terminology appropriately, and only document what was explicitly discussed.
Always return valid JSON as specified in the prompt."""


async def call_gemini(prompt: str, temperature: float = 0.0, max_retries: int = 3) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": SYSTEM_CONTEXT}]},
            {"role": "model", "parts": [{"text": "Understood. I will analyze clinical transcripts and return valid JSON as requested."}]},
            {"role": "user", "parts": [{"text": prompt}]},
        ],
        "generationConfig": {"temperature": temperature},
    }

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            if response.status_code == HTTPStatus.OK:
                content = response.json()
                text = (
                    content.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                return text.strip()
            else:
                logger.warning(f"Gemini HTTP {response.status_code}: {response.text[:200]}")
        except Exception as exc:
            logger.warning(f"Gemini call attempt {attempt + 1} failed: {exc}")
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)

    return ""


def extract_json(text: str) -> str:
    """Strip markdown code fences and return raw JSON string."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:] if lines[0].startswith("```") else lines
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def detect_instructions(transcript: str) -> list[dict]:
    """
    Stage 2: Ask Gemini what Canvas commands the transcript implies.
    Returns list of {"instruction": <command_class_name>, "information": <relevant excerpt>}
    """
    available_commands = "\n".join(f"- {name}: {schema['description']}"
                                   for name, schema in COMMAND_SCHEMAS.items())

    prompt = f"""You are analyzing a clinical encounter transcript to determine what EHR documentation commands should be created.

Available Canvas EHR commands:
{available_commands}

Transcript:
\"\"\"
{transcript}
\"\"\"

Based on this transcript, list every clinical action that should be documented in the EHR.
Return a JSON array of objects, each with:
- "instruction": the exact command class name from the list above
- "information": the relevant excerpt from the transcript that supports this command

Return ONLY a JSON array. No explanation. Example:
[
  {{"instruction": "HistoryOfPresentIllnessCommand", "information": "Patient presents with 3-day history of..."}},
  {{"instruction": "DiagnoseCommand", "information": "I'm diagnosing her with acute sinusitis..."}}
]"""

    raw = await call_gemini(prompt)
    try:
        data = json.loads(extract_json(raw))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"detect_instructions JSON parse failed: {exc}\nRaw: {raw[:500]}")
    return []


async def extract_parameters(
    instruction: str,
    information: str,
    note_uuid: str,
    patient_uuid: str,
    provider_uuid: str,
    max_retries: int = 3,
) -> dict | None:
    """
    Stage 3: Extract structured parameters for a single command.
    """
    schema = COMMAND_SCHEMAS.get(instruction)
    if schema is None:
        logger.warning(f"No schema for command: {instruction}")
        return None

    fields_desc = "\n".join(
        f"- {name} ({spec.get('type', 'string')}{'*' if name in schema.get('required', []) else ''}): {spec.get('description', '')}"
        for name, spec in schema["fields"].items()
        if name != "note_uuid"
    )

    prompt = f"""You are extracting structured parameters for a Canvas EHR command from a clinical transcript excerpt.

Command: {instruction}
Description: {schema['description']}

Fields to extract (* = required):
{fields_desc}

Clinical excerpt:
\"\"\"
{information}
\"\"\"

Extract the relevant parameters and return a JSON object with the field names as keys.
- Set "note_uuid" to "{note_uuid}"
- Omit fields that cannot be determined from the excerpt
- For ICD-10 codes, use standard codes (e.g. "J06.9" for acute upper respiratory infection)
- For UUIDs of existing records (condition_id, medication_id, etc.), use null if not known

Return ONLY a JSON object. No explanation."""

    for attempt in range(max_retries):
        raw = await call_gemini(prompt)
        try:
            data = json.loads(extract_json(raw))
            if isinstance(data, dict):
                data["note_uuid"] = note_uuid
                # Remove null values for unknown UUIDs
                data = {k: v for k, v in data.items() if v is not None}
                return data
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"extract_parameters attempt {attempt + 1} failed for {instruction}: {exc}")
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    return None


async def run_pipeline(
    transcript: str,
    note_uuid: str,
    patient_uuid: str,
    provider_uuid: str,
    api_signing_key: str,
) -> list[dict]:
    """
    Run the full 4-stage pipeline and return a list of command dicts.
    """
    if not transcript.strip():
        logger.info("Empty transcript — skipping pipeline")
        return []

    # Stage 2: Instruction detection
    instructions = await detect_instructions(transcript)
    logger.info(f"Detected {len(instructions)} instructions")

    if not instructions:
        return []

    # Stage 3 + 4: Extract parameters and build command dicts concurrently
    async def process_instruction(item: dict) -> dict | None:
        instruction = item.get("instruction", "")
        information = item.get("information", "")
        if instruction not in COMMAND_SCHEMAS:
            logger.warning(f"Unknown instruction: {instruction}")
            return None
        attributes = await extract_parameters(
            instruction, information, note_uuid, patient_uuid, provider_uuid
        )
        if attributes:
            return {"class": instruction, "attributes": attributes}
        return None

    tasks = [process_instruction(item) for item in instructions]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    commands = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Pipeline error: {result}")
        elif result is not None:
            commands.append(result)

    logger.info(f"Pipeline produced {len(commands)} commands")
    return commands
