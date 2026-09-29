"""Verify AssemblyAI Voice Agent events with Jenny's real human recording.

The disclosed agent may generate speech under Jenny's 2026-09-28 decision.
No pledge, payment, or follow-up record is created by this script.
"""

import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import wave

import httpx
import websockets
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


async def run(audio: Path):
    key = dotenv_values(ROOT / ".env").get("ASSEMBLYAI_API_KEY")
    if not key:
        raise RuntimeError("The local AssemblyAI key is missing")
    with wave.open(str(audio), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 24000, "NONE"):
            raise RuntimeError("Use a copy of a real human recording in mono PCM16 24 kHz WAV")
        audio_seconds = wav.getnframes() / wav.getframerate()
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": {"file": audio.name, "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                   "duration_seconds": audio_seconds, "human_voice": True},
        "authorization": "Jenny approved generated speech for the disclosed assistant only on 2026-09-28",
        "events": [], "tool_observations": [], "sent": [], "assistant_audio_frames": 0}
    started = time.perf_counter()
    token = None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://agents.assemblyai.com/v1/token",
                headers={"Authorization": "Bearer " + key},
                params={"expires_in_seconds": 60, "max_session_duration_seconds": 60})
            report["token_http_status"] = response.status_code
            response.raise_for_status()
            token = response.json()["token"]
        url = "wss://agents.assemblyai.com/v1/ws?token=" + token
        async with websockets.connect(url, open_timeout=15, close_timeout=3, max_size=4_000_000) as ws:
            config = {"type": "session.update", "session": {
                "system_prompt": "You are the disclosed automated Pledgebook assistant in an API verification session. Listen for a person's full name in the real recording. If you hear one, call record_heard_name with exactly the name you heard. Do not infer a name, create a pledge, mention money, or offer a payment link. After the tool result, briefly acknowledge the test and stop.",
                "greeting": "Hello. I am the automated Pledgebook assistant.",
                "input": {"format": {"encoding": "audio/pcm"}, "keyterms": ["Chief Emeka Okonkwo"]},
                "output": {"voice": "anna", "format": {"encoding": "audio/pcm"}},
                "tools": [{"type": "function", "name": "record_heard_name",
                    "description": "Record the name actually heard during this verification session. This creates no donor or pledge record.",
                    "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                                   "required": ["name"], "additionalProperties": False}}]}}
            await ws.send(json.dumps(config))
            report["sent"].append({"type": "session.update", "config": config["session"]})
            ready = asyncio.Event()
            greeting_done = asyncio.Event()
            stopped = asyncio.Event()
            pending = []

            async def receive():
                try:
                    async for raw in ws:
                        event = json.loads(raw)
                        event_type = event.get("type")
                        event["observed_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        # The voice is generated only for this authorized assistant.
                        # Store event metadata, not synthesized audio or short-lived secrets.
                        if event_type == "reply.audio":
                            report["assistant_audio_frames"] += 1
                            event = {"type": event_type, "observed_elapsed_ms": event["observed_elapsed_ms"],
                                     "audio_base64_length": len(event.get("data") or "")}
                        if event_type == "session.ready":
                            event.pop("resume_token", None)
                            ready.set()
                        report["events"].append(event)
                        if event_type == "tool.call":
                            pending.append(event)
                        if event_type == "reply.done":
                            greeting_done.set()
                            while pending:
                                call = pending.pop(0)
                                if call.get("name") != "record_heard_name":
                                    answer = {"error": "Unexpected tool; no action taken"}
                                    is_error = True
                                else:
                                    name = call.get("arguments", {}).get("name")
                                    if isinstance(name, str) and name.strip():
                                        report["tool_observations"].append({"name_heard": name.strip(),
                                            "call_id": call.get("call_id")})
                                        answer = {"name_heard": name.strip(), "saved_in_verification_evidence": True}
                                        is_error = False
                                    else:
                                        answer = {"error": "No name was supplied; no action taken"}
                                        is_error = True
                                result = {"type": "tool.result", "call_id": call["call_id"],
                                          "result": json.dumps(answer), "is_error": is_error}
                                await ws.send(json.dumps(result))
                                report["sent"].append(result)
                        if event_type == "session.ended":
                            stopped.set()
                            return
                finally:
                    stopped.set()

            receiver = asyncio.create_task(receive())
            try:
                await asyncio.wait_for(ready.wait(), 15)
                try:
                    await asyncio.wait_for(greeting_done.wait(), 10)
                except asyncio.TimeoutError:
                    report["greeting_wait_timeout"] = True
                with wave.open(str(audio), "rb") as wav:
                    sent_frames = 0
                    send_start = time.perf_counter()
                    while True:
                        chunk = wav.readframes(2400)
                        if not chunk:
                            break
                        await ws.send(json.dumps({"type": "input.audio",
                            "audio": base64.b64encode(chunk).decode("ascii")}))
                        sent_frames += len(chunk) // 2
                        await asyncio.sleep(max(0, send_start + sent_frames / 24000 - time.perf_counter()))
                report["sent"].append({"type": "input.audio", "frames": sent_frames})
                await asyncio.sleep(10)
                await ws.send(json.dumps({"type": "session.end"}))
                report["sent"].append({"type": "session.end"})
                await asyncio.wait_for(stopped.wait(), 8)
            finally:
                if not receiver.done():
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
        report["ok"] = any(x.get("type") == "session.ready" for x in report["events"]) and any(
            x.get("type") == "session.ended" for x in report["events"])
    except Exception as exc:
        report["ok"] = False
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc).replace(key, "[REDACTED]").replace(token or "", "[REDACTED]") if token else str(exc).replace(key, "[REDACTED]")
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    destination = ROOT / "eval/private/service-checks" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-voice.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": report["ok"], "token_http_status": report.get("token_http_status"),
        "event_counts": dict(Counter(x.get("type") for x in report["events"])),
        "assistant_audio_frames": report["assistant_audio_frames"],
        "tool_calls": len(report["tool_observations"]), "error_type": report.get("error_type"),
        "error": report.get("error"), "elapsed_ms": report["elapsed_ms"]}))
    print("Evidence:", destination.relative_to(ROOT))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True)
    options = parser.parse_args()
    raise SystemExit(asyncio.run(run(Path(options.audio).resolve())))
