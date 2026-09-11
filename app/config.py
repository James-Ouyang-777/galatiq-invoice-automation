from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: Path = ROOT / "inventory.db"
    invoices_dir: Path = ROOT / "data" / "invoices"
    uploads_dir: Path = ROOT / "data" / "uploads"
    high_value_threshold: float = 10_000.0
    math_tolerance: float = 1.0

    xai_api_key: str | None = None
    xai_model: str = "grok-3"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    google_api_key: str | None = None
    google_model: str = "gemini-2.0-flash"

    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
