from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    assemblyai_api_key: str
    paystack_secret_key: str
    data_dir: Path
    host: str
    port: int

    @classmethod
    def load(cls) -> "Settings":
        values = {**dotenv_values(ROOT / ".env"), **os.environ}
        data_dir = Path(values.get("PLEDGEBOOK_DATA_DIR") or ROOT / "data")
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        return cls(
            assemblyai_api_key=(values.get("ASSEMBLYAI_API_KEY") or "").strip(),
            paystack_secret_key=(values.get("PAYSTACK_SECRET_KEY") or "").strip(),
            data_dir=data_dir,
            host=values.get("PLEDGEBOOK_HOST") or "127.0.0.1",
            port=int(values.get("PLEDGEBOOK_PORT") or "8000"),
        )

    def require_assemblyai(self) -> str:
        if not self.assemblyai_api_key:
            raise RuntimeError("ASSEMBLYAI_API_KEY is not configured")
        return self.assemblyai_api_key
