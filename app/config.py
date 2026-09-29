from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


def _int(values: dict, key: str, default: int) -> int:
    try:
        return int(str(values.get(key) or default).strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    assemblyai_api_key: str
    paystack_secret_key: str
    data_dir: Path
    host: str
    port: int
    public_url: str
    sample_audio_path: Path | None
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    daily_audio_minutes: int = 240
    daily_assistant_sessions: int = 30
    daily_events: int = 30
    daily_emails: int = 200

    @classmethod
    def load(cls) -> "Settings":
        values = {**dotenv_values(ROOT / ".env"), **os.environ}
        data_dir = Path(values.get("PLEDGEBOOK_DATA_DIR") or ROOT / "data")
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        sample_audio = (values.get("PLEDGEBOOK_SAMPLE_AUDIO") or "").strip()
        sample_audio_path = Path(sample_audio) if sample_audio else None
        if sample_audio_path and not sample_audio_path.is_absolute():
            sample_audio_path = ROOT / sample_audio_path
        return cls(
            assemblyai_api_key=(values.get("ASSEMBLYAI_API_KEY") or "").strip(),
            paystack_secret_key=(values.get("PAYSTACK_SECRET_KEY") or "").strip(),
            data_dir=data_dir,
            host=values.get("PLEDGEBOOK_HOST") or "127.0.0.1",
            port=_int(values, "PLEDGEBOOK_PORT", 8000),
            public_url=(values.get("PLEDGEBOOK_PUBLIC_URL") or "").strip().rstrip("/"),
            sample_audio_path=sample_audio_path,
            smtp_host=(values.get("SMTP_HOST") or "").strip(),
            smtp_port=_int(values, "SMTP_PORT", 587),
            smtp_user=(values.get("SMTP_USER") or "").strip(),
            smtp_password=(values.get("SMTP_PASSWORD") or "").strip(),
            smtp_from=(values.get("SMTP_FROM") or "").strip(),
            daily_audio_minutes=_int(values, "PLEDGEBOOK_DAILY_AUDIO_MINUTES", 240),
            daily_assistant_sessions=_int(values, "PLEDGEBOOK_DAILY_ASSISTANT_SESSIONS", 30),
            daily_events=_int(values, "PLEDGEBOOK_DAILY_EVENTS", 30),
            daily_emails=_int(values, "PLEDGEBOOK_DAILY_EMAILS", 200),
        )

    def require_assemblyai(self) -> str:
        if not self.assemblyai_api_key:
            raise RuntimeError("ASSEMBLYAI_API_KEY is not configured")
        return self.assemblyai_api_key

    @property
    def paystack_mode(self) -> str:
        """Report whether the configured Paystack key moves real money."""

        if not self.paystack_secret_key:
            return "off"
        return "live" if self.paystack_secret_key.startswith("sk_live_") else "test"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")
