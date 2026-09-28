"""Thin, real AssemblyAI integrations used by the server."""

import asyncio
import base64
import json
from pathlib import Path
import time
from typing import AsyncIterator
from urllib.parse import urlencode
import wave

import httpx
import websockets

from .config import Settings


SITUATION_PROMPT = (
    "English speech at a Nigerian church fundraising launching. A master of "
    "ceremonies announces donor titles, names, and pledged amounts. Praise "
    "music and short Pidgin, Yoruba, or Igbo interjections may be present."
)


class AssemblyAIError(RuntimeError):
    pass


def realtime_url(keyterms: list[str]) -> str:
    query = {
        "speech_model": "universal-3-5-pro",
        "sample_rate": "16000",
        "prompt": SITUATION_PROMPT,
        "keyterms_prompt": json.dumps(keyterms),
    }
    return "wss://streaming.assemblyai.com/v3/ws?" + urlencode(query)


async def open_realtime(settings: Settings, keyterms: list[str]):
    key = settings.require_assemblyai()
    try:
        ws = await websockets.connect(
            realtime_url(keyterms),
            additional_headers={"Authorization": key},
            open_timeout=15,
            close_timeout=3,
            max_size=2_000_000,
        )
        first = json.loads(await asyncio.wait_for(ws.recv(), 15))
        if first.get("type") != "Begin":
            await ws.close()
            raise AssemblyAIError(f"AssemblyAI Realtime did not begin: {first}")
        return ws, first
    except Exception as exc:
        if isinstance(exc, AssemblyAIError):
            raise
        raise AssemblyAIError(f"Realtime connection failed: {exc}") from exc


async def sync_transcribe(settings: Settings, audio_path: Path, keyterms: list[str]) -> tuple[dict, float]:
    key = settings.require_assemblyai()
    config = {
        "prompt": SITUATION_PROMPT,
        "keyterms_prompt": keyterms[:100],
        "timestamps": True,
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            with audio_path.open("rb") as handle:
                response = await client.post(
                    "https://sync.assemblyai.com/v1/transcribe",
                    headers={"Authorization": key, "X-AAI-Model": "universal-3-5-pro"},
                    files={
                        "audio": (audio_path.name, handle, "audio/wav"),
                        "config": (None, json.dumps(config), "application/json"),
                    },
                )
        if response.status_code >= 400:
            raise AssemblyAIError(f"Sync returned HTTP {response.status_code}: {response.text[:500]}")
        return response.json(), round((time.perf_counter() - started) * 1000, 2)
    except AssemblyAIError:
        raise
    except Exception as exc:
        raise AssemblyAIError(f"Sync request failed: {exc}") from exc


async def voice_token(settings: Settings) -> str:
    key = settings.require_assemblyai()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://agents.assemblyai.com/v1/token",
                headers={"Authorization": "Bearer " + key},
                params={"expires_in_seconds": 300, "max_session_duration_seconds": 300},
            )
        if response.status_code >= 400:
            raise AssemblyAIError(f"Voice Agent token returned HTTP {response.status_code}: {response.text[:500]}")
        return response.json()["token"]
    except AssemblyAIError:
        raise
    except Exception as exc:
        raise AssemblyAIError(f"Voice Agent token request failed: {exc}") from exc


async def paced_pcm16(path: Path, sample_rate: int = 16000, chunk_ms: int = 50) -> AsyncIterator[bytes]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != sample_rate:
            raise ValueError(f"Audio must be mono PCM16 {sample_rate} Hz")
        frames = int(sample_rate * chunk_ms / 1000)
        while True:
            chunk = wav.readframes(frames)
            if not chunk:
                break
            yield chunk
            await asyncio.sleep(chunk_ms / 1000)


def pcm16_b64(chunk: bytes) -> str:
    return base64.b64encode(chunk).decode("ascii")
