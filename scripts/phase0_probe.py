"""Real Phase 0 service checks. Never generates audio or pledge transcripts.

Run from any directory; credentials stay in the project's ignored .env.
Outputs are recorded under docs/evidence/phase-0 with secrets redacted.
"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
import wave

import httpx
import websockets
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
SECRETS = []
PROMPT = "English speech: a master of ceremonies announces invented donor names and pledged amounts in naira at a Nigerian fundraiser."
TERMS = ["Chief Emeka Okonkwo"]


def clean(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in {"token", "api_key", "authorization"} else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        for secret in SECRETS:
            value = value.replace(secret, "[REDACTED]")
    return value


def body(response):
    try:
        return response.json()
    except ValueError:
        return {"non_json_body": response.text[:4000]}


async def http_check(client, name, method, url, **kwargs):
    started = time.perf_counter()
    result = {"check": name, "method": method, "url": url}
    try:
        response = await client.request(method, url, **kwargs)
        data = body(response)
        result.update(http_status=response.status_code, response=clean(data))
        result["ok"] = response.is_success
    except (httpx.HTTPError, OSError) as exc:
        result.update(ok=False, error_type=type(exc).__name__, error=clean(str(exc)))
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


async def realtime(key, audio=None):
    query = {"speech_model": "universal-3-5-pro", "sample_rate": 16000,
             "prompt": PROMPT, "keyterms_prompt": json.dumps(TERMS)}
    result = {"check": "realtime_audio" if audio else "realtime_handshake",
              "url": "wss://streaming.assemblyai.com/v3/ws", "query": query,
              "audio_sent": audio is not None, "events": [], "sent_messages": []}
    started = time.perf_counter()
    try:
        async with websockets.connect(result["url"] + "?" + urlencode(query),
                additional_headers={"Authorization": key}, open_timeout=15, close_timeout=3) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 15))
            first["observed_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            result["events"].append(first)
            if first.get("type") != "Begin":
                raise RuntimeError("Server did not begin the streaming session")
            update = {"type": "UpdateConfiguration", "keyterms_prompt": TERMS + ["Aisha Bello"]}
            await ws.send(json.dumps(update))
            result["sent_messages"].append(update)

            async def receive():
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 20))
                    event["observed_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    result["events"].append(event)
                    if event.get("type") == "Termination":
                        return

            receiver = asyncio.create_task(receive())
            try:
                if audio:
                    with wave.open(str(audio), "rb") as wav:
                        origin = time.perf_counter()
                        sent_frames = 0
                        while True:
                            frames = wav.readframes(1600)
                            if not frames:
                                break
                            await ws.send(frames)
                            sent_frames += len(frames) // 2
                            await asyncio.sleep(max(0, origin + sent_frames / 16000 - time.perf_counter()))
                    # Wait for final turns without fabricating additional silence audio.
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(0.5)
                await ws.send(json.dumps({"type": "Terminate"}))
                result["sent_messages"].append({"type": "Terminate"})
                await receiver
            finally:
                if not receiver.done():
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
            result["ok"] = any(e.get("type") == "Termination" for e in result["events"])
            if any(e.get("type") == "Error" or e.get("error") for e in result["events"]):
                result["ok"] = False
            result["limits"] = "Without spoken audio this verifies connection only, not recognition or the effect of updating names."
    except Exception as exc:
        result.update(ok=False, error_type=type(exc).__name__, error=clean(str(exc)))
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


async def main(args):
    key = dotenv_values(ROOT / ".env").get("ASSEMBLYAI_API_KEY")
    if not key:
        raise SystemExit("ASSEMBLYAI_API_KEY is missing from the local .env")
    SECRETS.append(key)
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "command": ["python3", "scripts/phase0_probe.py", *sys.argv[1:]],
              "purpose": "Live verification only; invented test name; no synthetic audio.",
              "packages": {name: importlib.metadata.version(name) for name in ("httpx", "websockets", "python-dotenv")},
              "checks": []}
    async with httpx.AsyncClient(timeout=90) as client:
        if args.mode in {"accounts", "gateway"}:
            if args.mode == "accounts":
                voice = await http_check(client, "voice_agent_token", "GET",
                    "https://agents.assemblyai.com/v1/token",
                    headers={"Authorization": "Bearer " + key},
                    params={"expires_in_seconds": 60, "max_session_duration_seconds": 60})
                voice["limits"] = "Token creation only; no synthesized voice, call, or session started. Token redacted."
                report["checks"].append(voice)
                report["checks"].append(await realtime(key))
            payload = {"model": args.model or "gemini-2.5-flash-lite", "max_tokens": 32,
                "messages": [{"role": "user", "content": "Return a JSON object with ok set to true."}],
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "access_check", "strict": True, "schema": {"type": "object",
                    "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}}}}
            if args.no_schema:
                payload.pop("response_format")
            gateway = await http_check(client, "gateway_documented_example_model", "POST",
                "https://llm-gateway.assemblyai.com/v1/chat/completions",
                headers={"Authorization": key}, json=payload)
            gateway["request_body"] = payload
            report["checks"].append(gateway)
        else:
            if not args.audio:
                raise SystemExit("Audio checks require --audio (a human recording).")
            audio = Path(args.audio).resolve()
            with wave.open(str(audio), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                if args.mode == "audio" and (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                    raise SystemExit("Convert a copy of the real recording to mono 16-bit 16 kHz WAV first; retain the original.")
                if args.mode == "audio" and not 5 <= duration <= 15:
                    raise SystemExit("Phase 0's paired checks require a real 5–15 second clip.")
                if args.mode == "sync" and not 0.08 <= duration <= 120:
                    raise SystemExit("Sync accepts only short recordings up to 120 seconds.")
            report["recording"] = {"file": audio.name, "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                                   "duration_seconds": duration, "expected_words": args.expected,
                                   "notice": "Real human voice supplied by Jenny; spoken content is unverified until manually checked."}
            config = {"prompt": PROMPT, "keyterms_prompt": TERMS, "timestamps": True}
            with audio.open("rb") as handle:
                result = await http_check(client, "sync_real_audio", "POST",
                    "https://sync.assemblyai.com/v1/transcribe",
                    headers={"Authorization": key, "X-AAI-Model": "universal-3-5-pro"},
                    files={"audio": (audio.name, handle, "audio/wav"),
                           "config": (None, json.dumps(config), "application/json")})
            result["config"] = config
            report["checks"].append(result)
            if args.mode == "audio":
                report["checks"].append(await realtime(key, audio))
    evidence_dir = ROOT / ("docs/evidence/phase-0" if args.mode == "accounts" else "eval/private/phase-0")
    target = evidence_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.mode + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    report = clean(report)
    target.write_text(json.dumps(report, indent=2) + "\n")
    for check in report["checks"]:
        if args.mode in {"accounts", "gateway"}:
            print(json.dumps(check, ensure_ascii=False))
        else:
            output = {k: check.get(k) for k in ("check", "http_status", "ok", "elapsed_ms", "error_type", "error") if k in check}
            response = check.get("response", {})
            if isinstance(response, dict):
                output["response_keys"] = list(response.keys())
                output["request_time_ms"] = response.get("request_time_ms")
                output["audio_duration_ms"] = response.get("audio_duration_ms")
                output["word_count"] = len(response.get("words") or [])
            if check["check"] == "realtime_audio":
                output["event_types"] = [event.get("type") for event in check.get("events", [])]
            print(json.dumps(output, ensure_ascii=False))
    print("Evidence:", target.relative_to(ROOT))
    return 0 if all(c["ok"] for c in report["checks"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["accounts", "gateway", "sync", "audio"])
    parser.add_argument("--audio")
    parser.add_argument("--expected")
    parser.add_argument("--model")
    parser.add_argument("--no-schema", action="store_true", help="Check basic model access separately from structured-output support")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
