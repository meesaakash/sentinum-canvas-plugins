import json
from hashlib import sha256
from time import time
from urllib.parse import urlencode

import httpx


def _presigned_url(secret: str, base_url: str, params: dict) -> str:
    timestamp = str(int(time()))
    hash_arg = f"{timestamp}{secret}"
    sig = sha256(hash_arg.encode("utf-8")).hexdigest()
    full_params = params | {"ts": timestamp, "sig": sig}
    return f"{base_url}?{urlencode(full_params)}"


async def post_progress(
    canvas_instance: str,
    note_uuid: str,
    signing_key: str,
    section: str,
    message: str,
) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    url = _presigned_url(
        signing_key,
        f"{canvas_instance}/plugin-io/api/hyperscribe/progress",
        {"note_id": note_uuid},
    )
    payload = [{"time": now, "message": message, "section": section}]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload, headers={"Content-Type": "application/json"})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"post_progress failed: {exc}")


async def post_commands(
    canvas_instance: str,
    note_uuid: str,
    patient_uuid: str,
    provider_uuid: str,
    signing_key: str,
    commands: list[dict],
) -> None:
    url = _presigned_url(
        signing_key,
        f"{canvas_instance}/plugin-io/api/hyperscribe/case_builder",
        {
            "note_uuid": note_uuid,
            "patient_uuid": patient_uuid,
            "provider_uuid": provider_uuid,
        },
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(url, json=commands, headers={"Content-Type": "application/json"})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"post_commands failed: {exc}")
