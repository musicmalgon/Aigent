from enum import StrEnum
from urllib.parse import urlsplit

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
    ai_service_base_url: str = "http://127.0.0.1:8001"
    ai_service_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=300,
    )
    ai_service_read_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
    )
    ai_service_write_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=300,
    )
    ai_service_pool_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=300,
    )
    ai_service_auth_token: SecretStr | None = None
    # Stage 2 remains opt-in until the deployed artifact is present and
    # calibration policy approves using its signals for recovery ranking.
    stage2_burnout_signals_enabled: bool = False

    # --- Google OAuth ---
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # 로그인 성공 후 프론트로 되돌려보낼 때 붙일 base URL (쿼리스트링으로 토큰 전달)
    google_oauth_frontend_redirect_url: str = "http://localhost:5173/oauth/callback"

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

    @field_validator("ai_service_base_url")
    @classmethod
    def validate_ai_service_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            not normalized
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError(
                "AI_SERVICE_BASE_URL must be an HTTP(S) URL without "
                "credentials, query, or fragment"
            )
        return normalized

    @field_validator("ai_service_auth_token", mode="before")
    @classmethod
    def normalize_ai_service_auth_token(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("google_redirect_uri", "google_oauth_frontend_redirect_url")
    @classmethod
    def validate_google_urls(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            not normalized
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError("must be a valid HTTP(S) URL")
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
