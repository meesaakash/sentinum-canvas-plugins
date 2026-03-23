import asyncio
import json
import logging
import os

from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.plugins import deepgram

from canvas_client import post_progress, post_commands
from pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("agent")


async def entrypoint(ctx: JobContext):
    logger.info("=== entrypoint called, room: %s ===", ctx.room.name)

    # Parse and validate room metadata
    raw_metadata = ctx.room.metadata or "{}"
    logger.info("room metadata raw: %s", raw_metadata)
    try:
        metadata = json.loads(raw_metadata)
    except json.JSONDecodeError as e:
        logger.error("failed to parse room metadata: %s", e)
        return

    note_uuid = metadata.get("note_uuid", "")
    patient_uuid = metadata.get("patient_uuid", "")
    provider_uuid = metadata.get("provider_uuid", "")
    canvas_instance = metadata.get("canvas_instance", "")
    api_signing_key = metadata.get("api_signing_key", "")

    logger.info(
        "metadata parsed — note=%s patient=%s canvas_instance=%s signing_key_present=%s",
        note_uuid, patient_uuid, canvas_instance, bool(api_signing_key),
    )

    if not note_uuid or not canvas_instance or not api_signing_key:
        logger.error("missing required metadata fields, aborting")
        return

    # Log all participants already in room
    for p in ctx.room.remote_participants.values():
        logger.info("existing participant: identity=%s name=%s", p.identity, p.name)

    # Watch for new participants
    @ctx.room.on("participant_connected")
    def on_participant_connected(participant):
        logger.info("participant connected: identity=%s name=%s", participant.identity, participant.name)

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logger.info("participant disconnected: identity=%s", participant.identity)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info("agent connected to room, local identity=%s", ctx.room.local_participant.identity)

    await post_progress(canvas_instance, note_uuid, api_signing_key,
                        "EVENTS", "Agent connected — listening...")

    stt = deepgram.STT(model="nova-3")
    logger.info("deepgram STT initialized with model=nova-3")

    transcript_lines: list[str] = []
    track_tasks: list[asyncio.Task] = []

    async def transcribe_track(track: rtc.AudioTrack, participant_identity: str) -> None:
        logger.info("transcribe_track started for participant=%s track_sid=%s", participant_identity, track.sid)
        stt_stream = stt.stream()
        audio_stream = rtc.AudioStream(track)
        frame_count = 0

        async def push_audio():
            nonlocal frame_count
            async for frame_event in audio_stream:
                stt_stream.push_frame(frame_event.frame)
                frame_count += 1
                if frame_count % 100 == 0:
                    logger.info("audio frames pushed: %d (participant=%s)", frame_count, participant_identity)
            logger.info("audio stream ended for participant=%s, total frames=%d", participant_identity, frame_count)
            await stt_stream.aclose()

        async def receive_transcripts():
            event_count = 0
            async for event in stt_stream:
                event_count += 1
                logger.info("stt event #%d type=%s", event_count, event.type)
                if event.type == "final_transcript" and event.alternatives:
                    text = event.alternatives[0].text.strip()
                    logger.info("final transcript: %r", text)
                    if text:
                        transcript_lines.append(text)
                        await post_progress(canvas_instance, note_uuid, api_signing_key,
                                            "TRANSCRIPT", text)
                elif event.type == "interim_transcript" and event.alternatives:
                    text = event.alternatives[0].text.strip()
                    if text:
                        logger.info("interim: %r", text)
            logger.info("stt stream exhausted after %d events", event_count)

        await asyncio.gather(push_audio(), receive_transcripts())
        logger.info("transcribe_track complete for participant=%s", participant_identity)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        logger.info(
            "track_subscribed: kind=%s participant=%s track_sid=%s",
            track.kind, participant.identity, track.sid,
        )
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info("starting transcription task for audio track participant=%s", participant.identity)
            task = asyncio.ensure_future(transcribe_track(track, participant.identity))
            track_tasks.append(task)
        else:
            logger.info("ignoring non-audio track kind=%s", track.kind)

    @ctx.room.on("track_unsubscribed")
    def on_track_unsubscribed(track, publication, participant):
        logger.info("track_unsubscribed: participant=%s track_sid=%s", participant.identity, track.sid)

    # Wait for disconnect
    disconnect_event = asyncio.Event()

    @ctx.room.on("disconnected")
    def on_disconnected(*args):
        logger.info("room disconnected, wrapping up")
        disconnect_event.set()

    logger.info("waiting for room disconnect (timeout=3600s)...")
    try:
        await asyncio.wait_for(disconnect_event.wait(), timeout=3600)
    except asyncio.TimeoutError:
        logger.warning("session timed out after 1 hour")

    logger.info("waiting for %d transcription task(s) to complete", len(track_tasks))
    if track_tasks:
        results = await asyncio.gather(*track_tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("transcription task %d raised: %s", i, r)

    full_transcript = " ".join(transcript_lines)
    logger.info("full transcript (%d segments, %d chars): %r", len(transcript_lines), len(full_transcript), full_transcript[:200])

    await post_progress(canvas_instance, note_uuid, api_signing_key,
                        "EVENTS", "Transcription complete. Running AI pipeline...")

    logger.info("running pipeline...")
    commands = await run_pipeline(
        full_transcript, note_uuid, patient_uuid, provider_uuid, api_signing_key
    )
    logger.info("pipeline returned %d commands", len(commands))

    await post_commands(canvas_instance, note_uuid, patient_uuid,
                        provider_uuid, api_signing_key, commands)
    await post_progress(canvas_instance, note_uuid, api_signing_key,
                        "EVENTS", f"Done — {len(commands)} commands applied.")
    logger.info("=== entrypoint complete for note=%s ===", note_uuid)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
