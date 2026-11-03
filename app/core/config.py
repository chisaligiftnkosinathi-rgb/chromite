import json
import os
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised, validated application configuration."""

    # Application
    PROJECT_NAME: str = "Chromite API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    APP_ENV: Literal[
        "development",
        "testing",
        "staging",
        "production",
    ] = "development"

    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000

    LOG_LEVEL: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    # Security / browser access
    # Accepts a JSON list ('["https://a.example"]') or a comma-separated
    # string ('https://a.example,https://b.example').
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    CORS_ALLOW_CREDENTIALS: bool = True

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: SecretStr

    # Only load this key in services that genuinely require
    # privileged database operations.
    SUPABASE_SERVICE_ROLE_KEY: SecretStr | None = None

    # Optional direct PostgreSQL connection.
    # Keep this separate from Supabase API credentials.
    DATABASE_URL: SecretStr | None = None

    model_config = SettingsConfigDict(
        # CHROMITE_ENV_FILE lets tests point away from the real .env.
        env_file=os.environ.get("CHROMITE_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
        env_ignore_empty=True,
    )

    @field_validator("SUPABASE_URL")
    @classmethod
    def validate_supabase_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")

        parsed = urlparse(value)

        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("SUPABASE_URL must be a valid HTTP(S) URL")

        # HTTP is only acceptable for local development.
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
        }:
            raise ValueError(
                "SUPABASE_URL must use HTTPS outside localhost"
            )

        return value

    @field_validator("SUPABASE_KEY")
    @classmethod
    def validate_supabase_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("SUPABASE_KEY cannot be empty")

        return value

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()

            if not text:
                return []

            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError("CORS_ORIGINS is not valid JSON") from exc

                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON must be a list")

                return parsed

            return [part for part in text.split(",")]

        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        cleaned = []

        for origin in origins:
            origin = origin.strip().rstrip("/")

            if not origin:
                continue

            if origin != "*":
                parsed = urlparse(origin)

                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(
                        f"Invalid CORS origin: {origin}"
                    )

            cleaned.append(origin)

        return list(dict.fromkeys(cleaned))

    @field_validator("API_V1_STR")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        value = value.strip()

        if not value.startswith("/"):
            raise ValueError("API_V1_STR must start with '/'")

        return value.rstrip("/") or "/"

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.APP_ENV == "production":
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "Wildcard CORS origins are not permitted in production"
                )

            if self.CORS_ALLOW_CREDENTIALS and not self.CORS_ORIGINS:
                raise ValueError(
                    "Explicit CORS_ORIGINS are required in production "
                    "when credentials are enabled"
                )

        if self.CORS_ALLOW_CREDENTIALS and "*" in self.CORS_ORIGINS:
            raise ValueError(
                "Wildcard CORS origins cannot be combined with "
                "CORS_ALLOW_CREDENTIALS=true"
            )

        return self


settings = Settings()
