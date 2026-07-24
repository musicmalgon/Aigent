from enum import StrEnum

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = "sqlite:///./remind.db"
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=10080)
    sqladmin_enabled: bool = False
    sqladmin_path: str = "/admin"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            make_url(value)
        except Exception as exc:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from exc
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be HS256, HS384, or HS512")
        return value

    @field_validator("sqladmin_path")
    @classmethod
    def validate_sqladmin_path(cls, value: str) -> str:
        if not value.startswith("/") or value == "/":
            raise ValueError("SQLADMIN_PATH must be an absolute non-root path")
        normalized = value.rstrip("/")
        if normalized in {"/docs", "/redoc", "/openapi.json"}:
            raise ValueError("SQLADMIN_PATH cannot shadow an application route")
        return normalized

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if (
            self.sqladmin_enabled
            and self.app_env is not AppEnvironment.DEVELOPMENT
        ):
            raise ValueError(
                "unauthenticated SQLAdmin can only be enabled in development"
            )
        if self.app_env is AppEnvironment.PRODUCTION:
            secret = self.jwt_secret_key.get_secret_value().strip().lower()
            insecure_markers = (
                "secret",
                "changeme",
                "your-secret-key",
                "development-secret",
                "default",
                "change-this",
                "change-me",
                "replace-with",
                "example",
                "development",
            )
            if any(marker in secret for marker in insecure_markers):
                raise ValueError(
                    "production JWT_SECRET_KEY cannot use a public placeholder"
                )
        return self

    @property
    def database_url_for_logging(self) -> str:
        return make_url(self.database_url).render_as_string(hide_password=True)


settings = Settings()  # type: ignore[call-arg]


__all__ = ["AppEnvironment", "Settings", "settings"]
