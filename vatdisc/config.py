"""Central settings, read from environment variables (optionally a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    user_agent: str
    seed: int
    hmrc_base_url: str
    hmrc_client_id: str
    hmrc_client_secret: str
    hmrc_scope: str
    hmrc_rps: float
    hmrc_max_calls: int
    http_delay: float
    http_timeout: float
    max_pages_per_site: int


def get_settings() -> Settings:
    data_dir = Path(os.getenv("VATDISC_DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    contact = os.getenv("VATDISC_CONTACT", "you@example.com")
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "vatdisc.sqlite",
        user_agent=f"VATDiscoveryResearchBot/0.1 (research prototype; contact: {contact})",
        seed=int(os.getenv("VATDISC_SEED", "42")),
        hmrc_base_url=os.getenv("HMRC_BASE_URL", "https://test-api.service.hmrc.gov.uk").rstrip("/"),
        hmrc_client_id=os.getenv("HMRC_CLIENT_ID", ""),
        hmrc_client_secret=os.getenv("HMRC_CLIENT_SECRET", ""),
        hmrc_scope=os.getenv("HMRC_SCOPE", ""),
        hmrc_rps=float(os.getenv("HMRC_RPS", "2")),
        hmrc_max_calls=int(os.getenv("HMRC_MAX_CALLS", "2000")),
        http_delay=float(os.getenv("VATDISC_HTTP_DELAY", "1.0")),
        http_timeout=float(os.getenv("VATDISC_HTTP_TIMEOUT", "10")),
        max_pages_per_site=int(os.getenv("VATDISC_MAX_PAGES_PER_SITE", "8")),
    )
