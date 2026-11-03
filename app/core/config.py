
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    CORS_ORIGINS: list[str] = []

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
        env_file=".env",
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

        return self


settings = Settings()
